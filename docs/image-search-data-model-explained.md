# Giải thích các bảng trong `docs/data-model.md` --- Image Search

Tài liệu này giải thích mô hình dữ liệu trong repository
`thong0609/image-search`, dựa trên file `docs/data-model.md` cập nhật
ngày 05/11/2026.

> **Lưu ý:** Đây là logical schema (mô hình dữ liệu logic), chưa phải
> migration SQL hay cấu trúc database đã triển khai.

## 1. Nhìn tổng thể kiến trúc database

Hệ thống không sử dụng PostgreSQL để lưu tất cả dữ liệu. Nó chia dữ liệu
thành ba nhóm lưu trữ:

``` text
                  Image Search System
                          |
             +------------+------------+
             |            |            |
             v            v            v
        PostgreSQL      Qdrant      S3 / MinIO
        Relational      Vector      Object Storage
        Database        Database
             |            |            |
             |            |            +-- Ảnh gốc
             |            |            +-- Thumbnail
             |            |            +-- Metadata snapshot
             |            |
             |            +-- Vector embedding
             |            +-- Search payload
             |
             +-- Users / Authentication
             +-- Images / Collections
             +-- Import / Ingestion Jobs
             +-- Search Sessions
             +-- Index Management
             +-- Audit Events
```

  -----------------------------------------------------------------------
  Thành phần                          Trách nhiệm
  ----------------------------------- -----------------------------------
  PostgreSQL                          Dữ liệu quan hệ, transaction, trạng
                                      thái, authentication

  Qdrant                              Vector similarity search và
                                      filtering trên payload

  S3 / MinIO                          Lưu trữ file ảnh và các artifact
  -----------------------------------------------------------------------

Ví dụ khi người dùng tìm kiếm ảnh một chiếc ô tô màu đỏ:

1.  Qdrant tìm các vector ảnh tương đồng với query.
2.  Qdrant trả về các `image_id`.
3.  Backend kiểm tra trạng thái ảnh trong PostgreSQL.
4.  Backend lấy thông tin ảnh và object key.
5.  Object Storage cung cấp ảnh hoặc thumbnail.

Đây là nền tảng để hiểu các bảng phía dưới.

# 2. Nhóm Account và Catalog

Nhóm này quản lý người dùng, nguồn dữ liệu và các ảnh được đưa vào hệ
thống.

## 2.1. `collections`

**Mục đích:** Phân nhóm ảnh trong hệ thống.

  Field        Ý nghĩa
  ------------ ----------------------------
  id           ID của collection
  name         Tên collection
  status       Trạng thái active/disabled
  created_at   Thời điểm tạo

Ví dụ:

``` text
Image Search
│
├── Nature
│   ├── forest.jpg
│   └── mountain.jpg
│
├── Technology
│   ├── laptop.jpg
│   └── robot.jpg
│
└── Animals
    ├── cat.jpg
    └── dog.jpg
```

Mỗi collection là một nhóm chứa các ảnh.

Một điểm đáng chú ý: Trong MVP, mỗi image chỉ thuộc một collection.

Collection chỉ dùng để tổ chức dữ liệu, không phải cơ chế phân quyền.
Người dùng có thể tìm kiếm trên toàn bộ kho ảnh đã được công bố.

## 2.2. `users`

**Mục đích:** Lưu thông tin tài khoản người dùng.

  Field              Ý nghĩa
  ------------------ -----------------------------
  id                 ID người dùng
  email_normalized   Email đã chuẩn hóa, unique
  password_hash      Mật khẩu đã hash
  display_name       Tên hiển thị
  role               user hoặc admin
  status             active hoặc disabled
  revision           Phiên bản dữ liệu tài khoản
  auth_version       Phiên bản authentication
  created_at         Thời điểm tạo
  updated_at         Thời điểm cập nhật

Có ba trường cần hiểu kỹ:

### `role`

Xác định quyền của người dùng:

-   `user`: Người dùng thông thường.
-   `admin`: Quản trị viên.

### `revision`

Đây là phiên bản của dữ liệu tài khoản.

Ví dụ: Admin cập nhật thông tin người dùng từ revision 1 lên revision 2.
Nếu một request vẫn gửi thông tin dựa trên revision 1, hệ thống có thể
phát hiện dữ liệu đã cũ và tránh ghi đè nhầm.

Đây là cách tiếp cận liên quan đến **Optimistic Concurrency Control**.

### `auth_version`

Đây là phiên bản liên quan đến authentication.

Ví dụ:

1.  Người dùng đang đăng nhập trên hai thiết bị.
2.  Người dùng đổi mật khẩu.
3.  Hệ thống tăng `auth_version`.
4.  Những refresh token family thuộc phiên bản cũ bị thu hồi.

Như vậy, hệ thống có thể vô hiệu hóa các phiên đăng nhập cũ.

**Lưu ý:** Visitor không được lưu trong bảng `users`. Visitor là khách
chưa có tài khoản.

## 2.3. `refresh_token_families`

**Mục đích:** Quản lý một nhóm refresh token được sinh ra từ một lần
đăng nhập.

Đây là bảng liên quan đến cơ chế JWT Authentication.

Khi người dùng đăng nhập:

-   Backend cấp Access Token.
-   Backend cấp Refresh Token.

Access Token thường có thời hạn ngắn. Khi Access Token hết hạn, client
sử dụng Refresh Token để xin Access Token mới.

Nhưng mỗi lần refresh, hệ thống có thể cấp một Refresh Token mới và vô
hiệu hóa token cũ. Đây gọi là **Refresh Token Rotation**.

`refresh_token_families` quản lý toàn bộ vòng đời của nhóm token đó.

  Field           Ý nghĩa
  --------------- ----------------------------
  id              ID của family
  user_id         Người sở hữu
  auth_version    Phiên bản authentication
  created_at      Thời điểm tạo
  expires_at      Hạn hết hiệu lực tuyệt đối
  revoked_at      Thời điểm thu hồi
  revoke_reason   Lý do thu hồi

Ví dụ:

``` text
User A đăng nhập trên Laptop
          |
          v
Refresh Token Family #1
          |
          ├── Refresh Token 1
          ├── Refresh Token 2
          └── Refresh Token 3
```

Một family tương ứng với một lần đăng nhập.

Điểm đáng chú ý là `expires_at` không được trượt theo mỗi lần refresh.

Ví dụ family được tạo lúc 8:00 và hết hạn lúc 8:00 ngày hôm sau. Dù
người dùng refresh liên tục, deadline tuyệt đối vẫn không thay đổi.

## 2.4. `refresh_tokens`

**Mục đích:** Lưu từng refresh token trong một family.

  Field                  Ý nghĩa
  ---------------------- ---------------------------------
  id                     ID token
  family_id              Family chứa token
  token_hash             Hash của token
  parent_token_id        Token trước đó
  replaced_by_token_id   Token thay thế
  created_at             Thời điểm tạo
  expires_at             Thời điểm hết hạn
  consumed_at            Thời điểm token đã được sử dụng
  revoked_at             Thời điểm thu hồi

Ví dụ:

``` text
Refresh Token Rotation

Token A (Consumed)
       |
       | Replaced by
       v
Token B (Consumed)
       |
       | Replaced by
       v
Token C (Current Token)
```

Tại sao phải lưu `parent_token_id` và `replaced_by_token_id`?

Để theo dõi lịch sử thay thế token.

Một tình huống bảo mật quan trọng:

-   Token A đã được sử dụng để lấy Token B.
-   Kẻ tấn công vẫn giữ Token A.
-   Kẻ tấn công tiếp tục sử dụng Token A.

Backend phát hiện Token A đã bị consume nhưng lại được sử dụng lần nữa.
Đây có thể là dấu hiệu token bị đánh cắp. Hệ thống có thể thu hồi toàn
bộ family.

**Lưu ý:** Database không lưu refresh token nguyên bản mà chỉ lưu hash.
Đây là một biện pháp bảo mật quan trọng.

## 2.5. `sources`

**Mục đích:** Quản lý nguồn cung cấp ảnh.

  Field                  Ý nghĩa
  ---------------------- -------------------------------
  id                     ID nguồn
  collection_id          Collection mà nguồn thuộc về
  type                   Loại nguồn
  name                   Tên nguồn
  connector_config_ref   Tham chiếu cấu hình connector
  provenance             Thông tin xuất xứ
  created_at             Thời điểm tạo

Ví dụ:

``` text
Sources
│
├── Internal Upload
├── Company Image Repository
└── Private Image Dataset
```

Tại sao cần bảng này?

Giả sử sau này có 100.000 ảnh đến từ 5 nguồn khác nhau. Khi cần kiểm tra
ảnh đến từ đâu, được import từ nguồn nào, hoặc cần đồng bộ lại nguồn
nào, hệ thống có thể truy xuất thông tin tập trung từ `sources`.

Một điểm đáng chú ý: `connector_config_ref` chỉ tham chiếu đến cấu hình,
không lưu trực tiếp API key hay secret.

## 2.6. `images`

**Bảng trung tâm của Catalog.**

**Mục đích:** Quản lý danh tính và trạng thái của từng ảnh.

  Field                   Ý nghĩa
  ----------------------- -------------------------------
  id                      ID ảnh
  collection_id           Collection chứa ảnh
  source_id               Nguồn cung cấp ảnh
  source_item_key         ID ảnh ở nguồn gốc
  latest_input_revision   Phiên bản input mới nhất
  lifecycle               active/deleted
  current_version         Version hiện đang phục vụ
  desired_version         Version mới nhất được yêu cầu
  metadata_revision       Phiên bản metadata
  created_at              Thời điểm tạo
  updated_at              Thời điểm cập nhật
  deleted_at              Thời điểm xóa

Đây là một trong những bảng quan trọng nhất của toàn bộ hệ thống.

Cần phân biệt `images` và `image_versions`:

-   `images`: Đại diện cho danh tính của một ảnh.
-   `image_versions`: Đại diện cho từng phiên bản của ảnh đó.

Ví dụ:

``` text
Image: laptop.jpg
ID: img_001

       images
          |
          v
    image_versions
          |
     ┌────┼────┐
     v    v    v
    v1   v2   v3
```

Tại sao phải tách như vậy?

Giả sử người dùng upload một ảnh laptop, sau đó cập nhật metadata hoặc
thay đổi nội dung ảnh. Nếu chỉ có một bảng `images`, việc theo dõi lịch
sử thay đổi sẽ khó khăn.

Với thiết kế này, hệ thống giữ được danh tính ảnh ổn định và theo dõi
các phiên bản riêng biệt.

Một quyết định thiết kế đáng chú ý:

`source_item_key` được sử dụng để định danh ảnh cùng với `source_id`.

Unique constraint:

``` sql
UNIQUE(source_id, source_item_key)
```

Tại sao không sử dụng SHA256 làm ID?

Bởi vì hai nguồn khác nhau có thể cung cấp cùng một file ảnh:

``` text
Source A ──┐
           ├── Same image bytes
Source B ──┘
```

Hai ảnh có cùng checksum nhưng vẫn là hai bản ghi nguồn khác nhau.

Vì vậy, checksum chỉ dùng để nhận diện nội dung giống nhau, không dùng
làm danh tính nghiệp vụ.

## 2.7. `image_versions`

**Mục đích:** Lưu thông tin từng phiên bản của ảnh.

  Field                    Ý nghĩa
  ------------------------ ---------------------------------
  image_id                 Ảnh gốc
  version                  Số phiên bản
  input_revision           Phiên bản input
  input_payload_hash       Hash của input payload
  source_object_version    Version của object nguồn
  object_key               Đường dẫn ảnh gốc trong storage
  thumbnail_key            Đường dẫn thumbnail
  metadata_snapshot_key    Đường dẫn metadata snapshot
  metadata_snapshot_hash   Hash metadata snapshot
  sha256                   Checksum ảnh
  byte_size                Dung lượng ảnh
  processing_status        Trạng thái xử lý
  created_at               Thời điểm tạo

Đây là bảng liên kết giữa Catalog và Object Storage.

Ví dụ:

``` text
images
  |
  └── img_001
        |
        ├── version 1
        │     ├── object_key
        │     ├── thumbnail_key
        │     └── metadata_snapshot_key
        │
        ├── version 2
        │     ├── object_key
        │     ├── thumbnail_key
        │     └── metadata_snapshot_key
        │
        └── version 3
              ├── object_key
              ├── thumbnail_key
              └── metadata_snapshot_key
```

Database không trực tiếp lưu file ảnh. Nó chỉ lưu các key để truy xuất
file trong Object Storage.

Đây là mô hình khá phổ biến trong các hệ thống xử lý media quy mô lớn.

# 3. Nhóm Model và Vector Index

Đây là nhóm quan trọng nhất đối với chức năng Image Search.

Có 5 bảng.

Trước tiên cần hiểu vấn đề: Embedding model có thể thay đổi.

Ví dụ:

-   Ban đầu dùng CLIP.
-   Sau đó muốn chuyển sang một image-text embedding model khác.
-   Model mới có số chiều vector khác.
-   Cần xây dựng lại vector index.

Nếu chỉ có một Qdrant collection duy nhất và ghi đè dữ liệu cũ, việc
chuyển đổi sẽ rất rủi ro.

Vì vậy, tài liệu thiết kế sử dụng khái niệm **Index Generation**.

## 3.1. `retrieval_profiles`

**Mục đích:** Lưu cấu hình của một hệ thống retrieval.

  Field                Ý nghĩa
  -------------------- ------------------------------
  id                   ID profile
  model_id             Tên embedding model
  model_revision       Phiên bản model
  processor_revision   Phiên bản image processor
  dimension            Số chiều embedding
  normalization        Cấu hình chuẩn hóa vector
  distance_metric      Cosine, Dot, Euclidean...
  ranking_version      Phiên bản thuật toán ranking
  keyword_config       Cấu hình tìm kiếm keyword
  created_at           Thời điểm tạo

Ví dụ:

``` text
Retrieval Profile A
├── model_id: CLIP
├── dimension: 512
├── distance_metric: cosine
└── ranking_version: v1
```

Tại sao cần bảng này?

Vì vector không thể được so sánh tùy ý giữa các model khác nhau.

Ví dụ:

``` text
Model A → 512 dimensions
Model B → 768 dimensions
```

Hai loại vector này không thể đưa vào cùng một phép so sánh similarity
thông thường.

Do đó, profile giúp hệ thống biết vector được tạo bằng model nào, phiên
bản nào và phải truy vấn theo metric nào.

Điểm quan trọng: Profile được thiết kế bất biến sau khi đã sử dụng. Nếu
thay đổi cấu hình retrieval, nên tạo profile mới.

## 3.2. `index_generations`

**Mục đích:** Quản lý từng thế hệ của vector index.

  Field               Ý nghĩa
  ------------------- --------------------------------
  id                  ID generation
  profile_id          Retrieval profile
  physical_location   Vị trí Qdrant collection/index
  status              Trạng thái generation
  source_watermark    Mốc dữ liệu nguồn
  created_at          Thời điểm tạo
  activated_at        Thời điểm kích hoạt

Ví dụ:

``` text
Index Generations
│
├── Generation 1
│   ├── Profile CLIP-v1
│   └── Status: retired
│
└── Generation 2
    ├── Profile CLIP-v2
    └── Status: active
```

Tại sao không cập nhật trực tiếp vector index?

Vì việc xây dựng lại hàng trăm nghìn hoặc hàng triệu vector có thể mất
thời gian. Trong lúc đó, hệ thống vẫn cần phục vụ tìm kiếm.

Đây là lúc Index Generation phát huy tác dụng.

Quy trình:

1.  Generation 1 đang phục vụ người dùng.
2.  Tạo Generation 2.
3.  Xây dựng vector mới trong Generation 2.
4.  Validate dữ liệu.
5.  Chuyển Generation 2 thành active.
6.  Generation 1 trở thành retired.

Cách tiếp cận này liên quan đến kỹ thuật **Blue-Green Deployment** ở
tầng search index.

## 3.3. `active_search_config`

**Mục đích:** Lưu cấu hình generation đang được sử dụng để tìm kiếm.

  Field           Ý nghĩa
  --------------- ------------------------
  config_key      Khóa cấu hình
  generation_id   Generation đang active
  revision        Phiên bản cấu hình

Hãy tưởng tượng có hai generation:

``` text
Generation 1: retired
Generation 2: active
```

Backend cần biết generation nào đang được sử dụng.

Thay vì hardcode tên Qdrant collection trong code, backend đọc cấu hình
active.

Ví dụ:

``` text
active_search_config
--------------------
config_key    = default
generation_id = generation_2
revision      = 2
```

Khi chuyển generation, chỉ cần cập nhật pointer này cùng với việc cập
nhật trạng thái generation trong transaction hoặc cơ chế điều phối tương
đương. Điều này giúp giảm rủi ro khi triển khai model mới.

## 3.4. `search_projections`

**Mục đích:** Theo dõi việc một phiên bản ảnh đã được đưa vào một
generation hay chưa.

  Field                 Ý nghĩa
  --------------------- -----------------------
  generation_id         Generation đích
  image_id              Ảnh
  content_version       Version nội dung ảnh
  projection_revision   Phiên bản projection
  point_id              ID point trong Qdrant
  payload_hash          Hash payload
  state                 Trạng thái projection
  applied_at            Thời điểm áp dụng

Đây là bảng có vai trò rất quan trọng trong việc đồng bộ PostgreSQL và
Qdrant.

Cần phân biệt: `search_projections` **không lưu vector embedding**. Nó
chỉ lưu thông tin theo dõi trạng thái projection.

Ví dụ:

``` text
PostgreSQL
    |
    v
search_projections
    |
    ├── image_id: img_001
    ├── generation_id: gen_002
    ├── point_id: point_123
    └── state: applied
             |
             v
          Qdrant
             |
             └── point_123
                  ├── Vector
                  └── Payload
```

Tại sao cần bảng này?

Giả sử Qdrant bị lỗi khi upsert. Nếu không có bảng theo dõi, hệ thống
khó biết ảnh nào đã được index và ảnh nào chưa.

`search_projections` cho phép kiểm tra trạng thái, retry và reconcile.

## 3.5. `published_projections`

**Mục đích:** Lưu những projection đã được xác minh và công bố.

  Field             Ý nghĩa
  ----------------- --------------------
  generation_id     Generation
  image_id          Ảnh
  point_id          Point ID
  content_version   Phiên bản nội dung

Bảng này có unique constraint:

``` sql
UNIQUE(generation_id, image_id)
```

Điểm khác biệt với `search_projections`:

-   `search_projections`: Theo dõi quá trình tạo và áp dụng projection.
-   `published_projections`: Xác nhận projection nào đã được công bố và
    có thể sử dụng.

Hãy hình dung:

``` text
Image
  |
  v
search_projections
  |
  | Đã upsert Qdrant
  | Đã kiểm tra hợp lệ
  v
published_projections
  |
  v
Được xem là projection đã publish
```

Đây là một lớp kiểm soát tính nhất quán giữa PostgreSQL và Qdrant.

# 4. Nhóm Imports và Ingestion Jobs

Đây là nhóm quản lý quá trình đưa ảnh vào hệ thống.

Có 5 bảng.

Để dễ hiểu, hãy tưởng tượng bạn upload một dataset gồm 10.000 ảnh.

Hệ thống phải:

1.  Nhận yêu cầu import.
2.  Kiểm tra dữ liệu.
3.  Lưu ảnh vào S3.
4.  Tạo metadata.
5.  Tiền xử lý ảnh.
6.  Sinh embedding.
7.  Đưa vector lên Qdrant.

Không thể thực hiện tất cả những công việc này trong một HTTP request
duy nhất.

Vì vậy, hệ thống cần cơ chế **background processing**.

## 4.1. `imports`

**Mục đích:** Đại diện cho một lần import dữ liệu.

  Field             Ý nghĩa
  ----------------- ------------------------
  id                ID import
  collection_id     Collection đích
  source_id         Nguồn dữ liệu
  manifest_key      Vị trí manifest
  idempotency_key   Khóa chống xử lý trùng
  request_hash      Hash yêu cầu
  status            Trạng thái import
  counters          Thống kê tiến trình
  created_by        Người thực hiện
  created_at        Thời điểm tạo

Ví dụ:

Người dùng upload 1.000 ảnh. Hệ thống tạo một import:

``` text
Import #001
├── Total: 1000
├── Succeeded: 800
├── Failed: 100
└── Processing: 100
```

Một điểm đáng chú ý là `idempotency_key`.

Giả sử client gửi request import hai lần do timeout. Nếu không có
idempotency, hệ thống có thể tạo hai import khác nhau và xử lý trùng dữ
liệu.

Idempotency key giúp nhận diện request đã được gửi trước đó.

Nếu cùng key nhưng nội dung request khác nhau (`request_hash` khác), hệ
thống trả conflict.

## 4.2. `import_items`

**Mục đích:** Theo dõi từng ảnh trong một lần import.

  Field               Ý nghĩa
  ------------------- ----------------------
  id                  ID item
  import_id           Import cha
  source_item_key     ID ảnh nguồn
  input_revision      Phiên bản input
  image_id            ID ảnh trong catalog
  content_version     Version nội dung
  status              Trạng thái
  error_code          Mã lỗi
  safe_error_detail   Chi tiết lỗi an toàn

Quan hệ:

``` text
imports
   |
   └── Import #001
          |
          ├── import_item_001
          ├── import_item_002
          ├── import_item_003
          ├── ...
          └── import_item_1000
```

Tại sao phải có bảng này?

Vì trạng thái import tổng thể không thể hiện được từng ảnh.

Ví dụ:

-   Ảnh 1: Thành công.
-   Ảnh 2: File lỗi.
-   Ảnh 3: Không hỗ trợ định dạng.
-   Ảnh 4: Đang xử lý.

Bảng này giúp retry hoặc báo lỗi chính xác theo từng ảnh.

## 4.3. `ingestion_jobs`

**Bảng quan trọng trong Background Processing.**

**Mục đích:** Quản lý từng công việc xử lý ảnh.

  Field              Ý nghĩa
  ------------------ -----------------------
  id                 ID job
  import_item_id     Import item liên quan
  image_id           Ảnh cần xử lý
  content_version    Version ảnh
  generation_id      Generation cần index
  pipeline_version   Phiên bản pipeline
  status             Trạng thái job
  attempts           Số lần thử
  next_attempt_at    Thời điểm retry
  lease_token        Token sở hữu job
  lease_until        Hạn lease
  last_error         Lỗi gần nhất

Ví dụ:

``` text
Image Upload
     |
     v
Import Item
     |
     v
Ingestion Job
     |
     ├── Validate Image
     ├── Generate Thumbnail
     ├── Generate Embedding
     ├── Upload Artifact
     └── Upsert Qdrant
```

Tại sao không xử lý tất cả trong `import_items`?

Vì một import item có thể sinh ra nhiều job.

Ví dụ khi reindex:

``` text
Image img_001
      |
      ├── Job 1 → Generation 1
      |
      └── Job 2 → Generation 2
```

Đây là điều rất quan trọng khi triển khai nhiều generation đồng thời.

Một số khái niệm trong bảng này:

-   `attempts`: Đếm số lần xử lý.
-   `next_attempt_at`: Hỗ trợ retry có trì hoãn.
-   `lease_token`: Xác định worker đang sở hữu job.
-   `lease_until`: Thời hạn worker được phép xử lý.

Lease giúp hệ thống xử lý trường hợp worker bị crash giữa chừng.

Ví dụ:

1.  Worker A nhận job.
2.  Worker A bị crash.
3.  Lease hết hạn.
4.  Worker B có thể nhận lại job.

Đây là cách tiếp cận thường thấy trong distributed job processing.

## 4.4. `catalog_changes`

**Mục đích:** Ghi nhận các thay đổi của catalog để đồng bộ sang Qdrant.

Bảng này triển khai ý tưởng **Transactional Outbox Pattern**.

Các trường:

  Field               Ý nghĩa
  ------------------- -------------------
  event_id            ID event
  image_id            Ảnh được thay đổi
  content_version     Version nội dung
  metadata_revision   Revision metadata
  event_type          Loại sự kiện
  created_at          Thời điểm tạo

Tại sao cần bảng này?

Giả sử backend cập nhật metadata ảnh trong PostgreSQL và cần cập nhật
Qdrant.

Có hai thao tác:

``` text
1. UPDATE PostgreSQL
2. UPSERT Qdrant
```

Vấn đề là PostgreSQL và Qdrant không nằm trong cùng một transaction.

Tình huống lỗi:

``` text
PostgreSQL UPDATE: SUCCESS
Qdrant UPSERT:     FAILED
```

Khi đó dữ liệu hai hệ thống không còn đồng bộ.

Transactional Outbox giải quyết bằng cách:

``` text
PostgreSQL Transaction
       |
       ├── UPDATE images
       |
       └── INSERT catalog_changes
                    |
                    v
               COMMIT
                    |
                    v
              Event Consumer
                    |
                    v
                  Qdrant
```

Điểm quan trọng: Thay đổi catalog và ghi event được thực hiện trong cùng
transaction PostgreSQL.

Nếu transaction rollback thì cả hai cùng rollback.

Nếu commit thành công thì event được lưu lại để consumer xử lý sau.

Đây là một pattern rất đáng học khi xây dựng microservices hoặc hệ thống
phân tán.

## 4.5. `generation_change_deliveries`

**Mục đích:** Theo dõi việc từng event đã được áp dụng vào generation
nào.

  Field           Ý nghĩa
  --------------- ---------------------
  generation_id   Generation đích
  event_id        Event cần xử lý
  status          Trạng thái delivery
  applied_at      Thời điểm áp dụng

Ví dụ:

``` text
catalog_changes
      |
      └── Event #100
              |
              ├── Generation 1 → Applied
              |
              └── Generation 2 → Pending
```

Tại sao cần bảng này?

Vì trong thời gian reindex, một event có thể cần được gửi đến nhiều
generation.

Ví dụ:

-   Generation 1 đang phục vụ.
-   Generation 2 đang xây dựng.
-   Người dùng cập nhật metadata một ảnh.

Cả hai generation có thể cần nhận thay đổi đó.

Bảng delivery giúp theo dõi từng lần đồng bộ riêng biệt và hỗ trợ retry
an toàn.

# 5. Nhóm Search Session và Audit

Có 3 bảng.

## 5.1. `search_sessions`

**Mục đích:** Lưu trạng thái của một phiên tìm kiếm.

  Field             Ý nghĩa
  ----------------- -----------------------------
  id                ID session
  user_id           Người tìm kiếm, có thể null
  owner_key_hash    Hash của khóa sở hữu
  query_hash        Hash query
  query_text        Nội dung query
  filters           Các bộ lọc
  generation_id     Generation đã sử dụng
  ranking_version   Phiên bản ranking
  expires_at        Thời điểm hết hạn
  created_at        Thời điểm tạo

Ví dụ:

Người dùng tìm kiếm:

``` text
Query: red sports car
Filters:
  - category: vehicle
  - license: commercial
```

Backend trả về 100 kết quả, nhưng frontend chỉ hiển thị 20 kết quả đầu
tiên.

Khi người dùng bấm Next Page, hệ thống cần biết:

-   Query ban đầu là gì?
-   Filter ban đầu là gì?
-   Đang sử dụng generation nào?
-   Ranking version nào?
-   Các kết quả đã được trả về là gì?

Đó là lý do cần `search_sessions`.

Điểm quan trọng: Search session không phải session đăng nhập. Nó chỉ
phục vụ pagination và snapshot kết quả tìm kiếm.

## 5.2. `search_items`

**Mục đích:** Lưu danh sách kết quả của một search session.

  Field             Ý nghĩa
  ----------------- --------------------
  session_id        Search session
  position          Vị trí kết quả
  image_id          ID ảnh
  content_version   Version ảnh
  point_id          Point trong Qdrant

Ví dụ:

``` text
search_sessions
      |
      └── Session #001
              |
              ├── Position 1 → Image A
              ├── Position 2 → Image B
              ├── Position 3 → Image C
              └── Position 4 → Image D
```

Tại sao không truy vấn lại Qdrant mỗi khi người dùng chuyển trang?

Vì kết quả có thể thay đổi theo thời gian:

-   Có ảnh mới được upload.
-   Có ảnh bị xóa.
-   Vector index được cập nhật.
-   Ranking thay đổi.

Lưu `search_items` giúp giữ snapshot kết quả ổn định hơn giữa các lần
phân trang.

## 5.3. `audit_events`

**Mục đích:** Lưu lịch sử hoạt động quan trọng trong hệ thống.

  Field           Ý nghĩa
  --------------- ------------------
  id              ID event
  actor_id        Người thực hiện
  action          Hành động
  resource_type   Loại tài nguyên
  resource_id     ID tài nguyên
  safe_context    Context an toàn
  timestamp       Thời điểm xảy ra

Ví dụ:

``` text
Audit Events
│
├── Admin updated user role
├── User uploaded images
├── Admin disabled account
├── Image deleted
└── Search configuration changed
```

Bảng này phục vụ:

-   Kiểm tra lịch sử thay đổi.
-   Điều tra sự cố.
-   Theo dõi thao tác quản trị.
-   Phục vụ audit bảo mật.

**Lưu ý:** Không lưu mật khẩu hay token vào audit log.

# 6. Tổng hợp toàn bộ 20 bảng

  Nhóm              Bảng                             Vai trò
  ----------------- -------------------------------- ------------------------------
  Catalog           `collections`                    Nhóm ảnh
  Catalog           `sources`                        Nguồn cung cấp ảnh
  Catalog           `images`                         Danh tính ảnh
  Catalog           `image_versions`                 Lịch sử phiên bản ảnh
  Account           `users`                          Tài khoản
  Account           `refresh_token_families`         Nhóm refresh token
  Account           `refresh_tokens`                 Từng refresh token
  Retrieval         `retrieval_profiles`             Cấu hình embedding/retrieval
  Retrieval         `index_generations`              Các thế hệ index
  Retrieval         `active_search_config`           Generation đang phục vụ
  Retrieval         `search_projections`             Theo dõi projection
  Retrieval         `published_projections`          Projection đã công bố
  Ingestion         `imports`                        Một lần import
  Ingestion         `import_items`                   Từng ảnh trong import
  Ingestion         `ingestion_jobs`                 Công việc xử lý ảnh
  Synchronization   `catalog_changes`                Outbox events
  Synchronization   `generation_change_deliveries`   Theo dõi đồng bộ
  Search            `search_sessions`                Phiên tìm kiếm
  Search            `search_items`                   Kết quả tìm kiếm
  Audit             `audit_events`                   Lịch sử hoạt động

# 7. Ghép tất cả thành một luồng hoạt động thực tế

Đây là phần quan trọng nhất: Cần hiểu các bảng phối hợp với nhau như thế
nào, thay vì chỉ nhớ từng bảng riêng lẻ.

## Luồng upload và indexing ảnh

``` text
1. Người dùng upload ảnh
   |
   └── users xác định người upload
          |
2. Tạo import
   |
   └── imports tạo một phiên import
          |
3. Phân rã thành từng ảnh
   |
   └── import_items theo dõi từng ảnh
          |
4. Tạo danh tính ảnh
   |
   └── sources, collections, images, image_versions
          |
5. Xử lý ảnh bất đồng bộ
   |
   └── ingestion_jobs quản lý các công việc xử lý
          |
6. Sinh embedding và ghi Qdrant
   |
   └── retrieval_profiles, index_generations,
       search_projections quản lý quá trình index
          |
7. Công bố kết quả index
   |
   └── published_projections xác nhận projection
       đã sẵn sàng
          |
8. Ghi nhận thay đổi
   |
   └── catalog_changes, generation_change_deliveries
       phục vụ đồng bộ và đối soát
```

## Luồng search

``` text
1. Người dùng nhập query
   |
   └── Backend sử dụng active_search_config
       để xác định generation
          |
2. Tìm kiếm trên Qdrant
   |
   └── Qdrant thực hiện vector retrieval và filtering
          |
3. Kiểm tra catalog
   |
   └── Backend kiểm tra ảnh còn active và projection
       được công bố hợp lệ
          |
4. Tạo search snapshot
   |
   └── search_sessions và search_items lưu kết quả
          |
5. Trả kết quả
   |
   └── Backend trả metadata và đường dẫn thumbnail
       cho frontend
```

# 8. Góc nhìn kiến trúc: Những điểm đáng chú ý nhất

Nếu nhìn schema dưới góc độ Senior Backend Engineer hoặc Software
Architect, có 5 quyết định thiết kế đáng chú ý.

  -----------------------------------------------------------------------
  Thiết kế                            Vấn đề giải quyết
  ----------------------------------- -----------------------------------
  Image + Image Versions              Quản lý lịch sử thay đổi và giữ
                                      identity ổn định

  Index Generations                   Reindex không làm gián đoạn search

  Transactional Outbox                Đồng bộ PostgreSQL và Qdrant đáng
                                      tin cậy hơn

  Job Lease + Retry                   Xử lý worker crash và retry

  Search Snapshot                     Giữ kết quả phân trang nhất quán
  -----------------------------------------------------------------------

Đặc biệt, có ba vấn đề nên đào sâu tiếp:

### 1. Index Generation và Search Projection

Đây là thiết kế đặc thù của hệ thống vector search. Cần hiểu tại sao có
cả `search_projections` và `published_projections`, thay vì chỉ lưu
vector trong Qdrant.

### 2. Transactional Outbox và Delivery

Đây là một vấn đề distributed systems thực sự. PostgreSQL và Qdrant
không có distributed transaction chung, nên cần một cơ chế đồng bộ có
khả năng retry và reconcile.

### 3. Image Versioning

Đây là nền tảng để xử lý ảnh được cập nhật, re-embedding, thay đổi
metadata và tránh worker cũ ghi đè kết quả mới.

------------------------------------------------------------------------

## Hướng đọc tiếp

Nên đọc `docs/qdrant-design.md` để hiểu sâu hơn cách
`search_projections`, `published_projections`, `index_generations` tương
tác với Qdrant, đặc biệt là luồng đồng bộ và reindex.

Đây là phần nối trực tiếp từ database schema sang kiến trúc thực thi của
Image Search System.
