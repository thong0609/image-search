# Mô hình dữ liệu — 9 bảng SQL

Cập nhật 06/11/2026 theo C13: thay schema 24 bảng bằng 9 bảng dưới đây. Schema này đã có migration đầu tiên ở migrations/versions/0001_initial.py và SQLAlchemy metadata trong adapters/postgres/schema.py; các ràng buộc workflow/JSON ở service sẽ triển khai theo phase. UUID dùng cho định danh; thời gian UTC. Vector/search metadata nằm ở Qdrant, entity/relations ở graph store, ảnh và artifacts ở object storage. Không tính các cấu trúc ngoài SQL vào số bảng này.

## 1. Danh sách và quan hệ

| Bảng | Trách nhiệm |
| --- | --- |
| users | Tài khoản, role, trạng thái và auth_version |
| refresh_tokens | Token hash, chuỗi rotation và thu hồi theo lần login |
| collections | Phân loại/bộ lọc ảnh, không ACL |
| images | Danh tính, source identity, lifecycle và con trỏ version |
| image_versions | Object/artifact references, hashes và trạng thái chỉ mục theo version |
| jobs | Import, xử lý, outbox đồng bộ từng target, retry, purge và rebuild |
| search_configs | Cấu hình versioned của encoder, vector/graph, fusion và VLM; cấu hình active |
| search_sessions | Snapshot thứ tự kết quả hữu hạn và phân trang |
| audit_events | Lịch sử thao tác quản trị và thay đổi cấu hình |

```mermaid
erDiagram
    USERS ||--o{ REFRESH_TOKENS : owns
    REFRESH_TOKENS o|--o{ REFRESH_TOKENS : rotates
    COLLECTIONS ||--o{ IMAGES : contains
    IMAGES ||--o{ IMAGE_VERSIONS : versions
    JOBS o|--o{ JOBS : groups
    IMAGES o|--o{ JOBS : processes
    SEARCH_CONFIGS ||--o{ SEARCH_SESSIONS : pins
    USERS o|--o{ SEARCH_SESSIONS : starts
    USERS o|--o{ AUDIT_EVENTS : acts
```

Không có bảng riêng cho source, refresh family, import/item, projection/published pointer, generation registry hoặc search items. Các khái niệm cần thiết vẫn tồn tại dưới dạng trường, job type hoặc artifact; không bỏ bảo đảm chỉ để giảm số bảng.

## 2. Tài khoản và refresh token

`users`: id, email_normalized unique, password_hash, display_name, role=user/admin, status=active/disabled, revision, auth_version, created_at, updated_at. Visitor không có users record. Không lưu raw password/token.

`refresh_tokens`: id, user_id, family_id, parent_id nullable, token_hash unique, auth_version, expires_at, consumed_at nullable, revoked_at nullable, revoke_reason nullable, created_at.

- Mỗi login tạo một root row: family_id=id, parent_id=null. Root giữ auth_version tại login, deadline tuyệt đối (đề xuất 7 ngày) và trạng thái thu hồi chung qua revoked_at/revoke_reason.
- Mỗi rotation thêm một row cùng user_id/family_id/auth_version/deadline; parent_id trỏ token trước đó. Root FK tự tham chiếu được kiểm tra trong transaction insert. Unique parent_id khi khác null bảo đảm mỗi token chỉ có một hậu duệ trực tiếp.
- Root có thể đã consumed sau refresh đầu tiên nhưng nhóm vẫn active nếu root chưa revoked/chưa hết hạn. Protected request kiểm tra root theo JWT family_id, không từ chối chỉ vì root consumed.
- Login/refresh/logout và thay đổi account cùng khóa user trước; refresh tiếp tục khóa root rồi token được trình (không khóa lặp khi token chính là root). Kiểm tra consumed và tạo successor trong cùng transaction. Reuse thu hồi root; mọi hậu duệ bị chặn bởi root check, không cần cập nhật từng row.
- Logout thu hồi root; logout-all/password/role/status đổi tăng users.auth_version và thu hồi mọi root của user cùng transaction. Access JWT luôn kiểm tra user/version/root hiện hành để giữ cam kết thu hồi sau commit.
- Giữ cả root và token đã consumed đến deadline nhóm cộng access TTL/clock skew; cleanup cả nhóm khi đủ điều kiện, không xóa root trước hậu duệ. Hash không ghi đè khi rotate vì cần nhận diện token cũ.

Chi tiết cookie, access/refresh transport và races ở [xác thực và phân quyền](api-contract.md#auth).

## 3. Collections, images và image_versions

`collections`: id, name, status, created_at. Mỗi image thuộc một collection; mọi người tìm cùng toàn kho. Không tự gộp ảnh khác source identity chỉ vì cùng checksum.

`images`: id, collection_id, source_id, source_item_key, latest_input_revision, lifecycle=active/deleted, current_version nullable, desired_version, metadata_revision, created_at, updated_at, deleted_at nullable. Unique(source_id, source_item_key); version references phải thuộc đúng image. current_version chỉ đổi bằng compare-and-set sau khi đủ điều kiện publish.

Source definitions nằm trong manifest cấu hình nguồn versioned ở object storage/config deployment: source_id ổn định, collection_id, allowed prefix, connector_config_ref, provenance và revision/hash. Không có bảng nguồn; images giữ identity, image_versions/jobs pin source_config_ref/hash để replay. Không thay nghĩa source_id hoặc tái sử dụng ID cho nguồn khác; secret chỉ là reference.

`image_versions`: image_id, version, input_revision, input_payload_hash, source_config_ref/hash, source_object_version, object_key, thumbnail_key, metadata_snapshot_key/hash, sha256, byte_size, processing_status, index_state JSON, created_at. Unique(image_id, version); version tăng đơn điệu; metadata-only update cũng tạo version mới nhưng có thể tái sử dụng embedding đúng byte/model/processor hash.

Index_state có schema versioned, chỉ chứa references/hashes/trạng thái, không vector hoặc toàn bộ metadata/graph:

```json
{
  "schema_version": 1,
  "vector": {
    "vg001": {
      "projection_revision": 1,
      "point_id": "point-example",
      "payload_hash": "sha256:example",
      "embedding_artifact_key": "artifacts/image-1/v1/embedding",
      "state": "ready"
    }
  },
  "graph": {
    "gg001": {
      "projection_revision": 1,
      "artifact_key": "artifacts/image-1/v1/graph.json",
      "artifact_hash": "sha256:example",
      "state": "ready"
    }
  }
}
```

Keys là generation ID nội bộ lấy từ search_configs; mỗi entry đi từ pending/applying tới ready/failed và giữ ID/hash bất biến sau khi enqueue. Entry ready của version đang current không được sửa refs/hashes; thay nội dung projection trong cùng generation phải tạo content version mới, kể cả dùng lại ảnh/embedding. Rebuild dùng generation mới. Không ghi đè point đã công bố. Schema validation, CAS revision và khóa row ngắn ngăn worker sửa mất entry của target khác. JSON nhỏ và giới hạn active/build/retained generations theo retention, không nhét lịch sử vô hạn.

Con trỏ công bố được suy từ images.current_version + index_state của version đó + generation của active search_configs. Ready entry của desired_version chưa current vẫn là staging. Publish kiểm tra cả vector và graph đúng generation ready, desired_version/lifecycle/lease còn hợp lệ, rồi đổi current_version cùng tăng graph_revision của config active trong transaction. Graph rỗng đã xác minh là ready; graph lỗi không phải rỗng. Final check theo các trường này thay cho bảng published pointers.

Title/tags/license/kích thước và metadata hiển thị đọc từ đúng Qdrant point; snapshot object storage dùng rebuild/audit. Tombstone chặn response mới ngay; purge mọi target/generation và artifacts không còn tham chiếu theo retention, không xóa shared entity còn được dùng.

## 4. jobs — hàng đợi bền vững và transactional outbox

`jobs`: id, parent_id nullable, type, status, image_id nullable, content_version nullable, config_id nullable, target_type nullable, target_generation nullable, dedupe_key unique, idempotency_key nullable, request_hash nullable, payload JSON, depends_on JSON, result JSON, attempts, next_attempt_at, lease_token, lease_until, created_by nullable, created_at, updated_at, last_error nullable.

| Job type | Vai trò |
| --- | --- |
| crawl / crawl_item / fetch_media | Thu thập nguồn cấu hình/metadata/facts, validate/download có checkpoint, xuất manifest rồi chuyển import pipeline |
| import | Job cha: manifest/source refs, request idempotency, tổng tiến độ |
| import_item | Một dòng manifest, line_number/source key/input revision, lỗi hoặc kết quả riêng |
| prepare_image | Validate/decode, thumbnail, immutable snapshots/artifacts và encoder |
| sync_vector / sync_graph | Một target/generation cụ thể; chính là outbox delivery |
| publish_image | Chờ hai target ready, CAS current_version và hoàn tất item |
| sync_facts | Stage shared graph facts/manifest và công bố revision |
| purge / reconcile / rebuild | Xóa, kiểm tra integrity hoặc dựng chỉ mục trong maintenance |

Import root ID chính là import_id; import_item job ID chính là item_id trên API. Child processing jobs tham chiếu import_item; không tạo riêng bảng imports/items. Item invalid có thể failed mà chưa có image_id. Parser streaming dùng dedupe_key(root_id, line_number), payload hash và checkpoint để replay không nhân đôi dòng; trùng source key/revision trong manifest được phân loại theo quy tắc ingestion. Counts tính từ import_item children, không đếm các job sync; chỉ kết thúc import sau khi đối soát parser và item states.

Khi catalog đổi desired_version/tombstone hoặc khi artifact refs được chốt, tạo các jobs xử lý/sync/purge tương ứng trong cùng transaction SQL. Không ghi DB rồi enqueue bằng một bước rời; jobs thay cả queue và outbox. Unique dedupe_key gồm type/identity/version/target generation/projection revision hoặc source fact revision. Parent/depends_on phải tồn tại, không chu trình; worker chỉ claim khi dependencies succeeded. Payload/result có schema theo type, không chứa vector, raw secret hoặc ảnh lớn.

Claim dùng transaction ngắn, lease/fencing; I/O ngoài transaction. Worker chỉ cập nhật target state khi lease/desired_version còn đúng; write ngoài SQL đã bay đi được bảo vệ bằng identity bất biến và final catalog check. Retry target graph lỗi không chạy lại vector đã ready. Failed dependency phải làm item failed hoặc bị superseded/cancelled theo catalog; không để import treo vô hạn. Admin retry item reset/enqueue đúng các bước lỗi có thể retry cùng transaction, giữ ID/hash của projection không đổi và không đánh dấu thành công bước chưa chạy.

## 5. search_configs — cấu hình và vòng đời chỉ mục

`search_configs`: id, revision, status=building/validating/active/retired/failed, encoder_config JSON, vector_index JSON, keyword_config JSON, graph_config JSON, fusion_config JSON, reranker_config JSON, failure_policy JSON, source_config_ref/hash, graph_revision, graph_manifest_key/hash, maintenance JSON, created_at, activated_at nullable.

Vector_index chứa generation ID, physical collection, dimension/normalization/metric. Graph_config chứa generation/location, schema/linker revisions, traversal templates/budgets và graph scoring. Reranker_config pin VLM/model/processor/prompt/schema/decoding, rendition và window. Active row là nguồn cấu hình đọc duy nhất, lấy bằng status=active; unique constraint phù hợp engine bảo đảm tối đa một active. Không nhận collection/graph endpoint từ client.

Các trường định nghĩa model/index/ranking bất biến khi dùng; runtime fields status, graph_revision, manifest pointer, maintenance có thể cập nhật bằng CAS/transaction và audit. Đổi định nghĩa tạo row mới. Config VLM/prompt mới có thể tái sử dụng vector/graph generation tương thích; khi activation phải mang theo graph_manifest và graph_revision hiện hành dưới khóa điều phối, không phục hồi manifest cũ của bản config đã retired.

Shared facts có immutable source revision/provenance trong graph store và artifacts. sync_facts stage dữ liệu rồi publish manifest key/hash + tăng graph_revision trong active config; adapter chỉ traversal tập fact revisions thuộc manifest đã công bố. Graph không hỗ trợ view này phải dùng maintenance để thay snapshot, không đọc staging. Không có registry facts SQL riêng.

Activation mới vô hiệu hóa mọi snapshot config cũ; active config và maintenance gates không được cache làm mất kiểm tra sau commit. MVP hỗ trợ một cấu hình active và tối đa một bản build tại một thời điểm. Đổi encoder/graph schema dùng maintenance: chặn mới các ghi catalog/fact/import/delete, drain writers/jobs, dựng index trên dữ liệu đứng yên, đối soát và chuyển active nguyên tử. Search có thể tiếp tục trên bản cũ trong build nếu tài nguyên đủ; cutover tạm dừng/drain search và vô hiệu hóa snapshot cũ. Tạm dừng ghi do bảo trì được lưu bền trong runtime config, kiểm tra cả API và worker. Không hứa dual-write/catch-up hoặc rollback online tự động. Runbook đầy đủ ở [operations.md](operations.md).

## 6. Search snapshots và audit

`search_sessions`: id, user_id nullable, owner_key_hash, query_hash, query_text nullable theo retention, filters JSON, config_id, graph_revision, hard_graph_constraints JSON, query_plan JSON, items JSON, degraded, degradation_reason, expires_at, created_at.

C18 query_plan giữ mode/targets/counts/statuses và evidence refs; target_ids trong items giữ grouping, dedup top-level image ID nhưng cho phép nhiều nhóm tham chiếu. Không thêm bảng target/result riêng. Items là mảng có thứ tự tối đa 200 phần tử `{image_id, content_version, point_id, target_ids}`; validate không trùng ID và đúng version/point. Chỉ chứa shortlist đã rerank hoặc fusion shortlist khi fallback tường minh; ví dụ window=50 thì tối đa 50. Không có bảng item riêng. Mỗi trang duyệt theo vị trí, final-check current_version/index_state/lifecycle, không rerank lại. Cursor pin owner/config/position; config active đổi hoặc graph revision đổi với hard constraint trả SEARCH_EXPIRED. X-Search-Owner không phải login hoặc ACL.

`audit_events`: id, actor_id nullable cho tác vụ hệ thống, action, resource_type, resource_id, safe_context JSON, created_at. Thay đổi quản trị tài khoản/catalog/config và maintenance phải có audit trong cùng transaction thích hợp. Không lưu password/token/signed URL/ảnh hoặc tùy tiện ghi raw query.

## 7. Index, retention và kiểm chứng

- Unique email_normalized; token_hash; parent_id khác null. Index refresh_tokens(user_id), family_id, expires_at; FK parent/root cùng user/family được validate trong transaction.
- Unique images(source_id, source_item_key), image_versions(image_id, version). Index lifecycle, collection_id, jobs(parent_id, type, status), jobs(status, next_attempt_at), lease_until và dedupe_key. Không index mọi JSON field.
- Unique active search config; index search_sessions.expires_at và audit timestamp/resource. CAS/row locks bảo vệ index_state, config epoch và publish.
- Snapshot TTL đề xuất 15 phút; query logging mặc định tắt; root/token history, jobs/idempotency, tombstones, artifacts và audit dọn theo Q09. Job root giữ ít nhất cửa sổ idempotency; job/artifact đang cần retry/rebuild không được cleanup.
- Reconcile so catalog/index_state với Qdrant/graph/object hashes, requeue jobs thiếu, dọn orphan sau grace period; không tự publish chỉ vì thấy point/edge. Backup/restore gồm SQL và các artifacts/config nguồn versioned.

Đánh đổi C13: ít bảng hơn nhưng cần validate JSON/job types trong ứng dụng, source administration qua cấu hình, reindex có maintenance window và chưa hỗ trợ nhiều generation ghi song song. Giữ 9 bảng này làm schema hiện hành; sơ đồ chi tiết cũ 24 bảng đã được thay thế, đã có migration schema ban đầu, chưa có dữ liệu thực tế để chuyển đổi.

C14–C18: FastAPI/PostgreSQL đã chọn. Source type đề xuất private hoặc web_import theo source config, pin external ID/version, original page/media URLs và attribution vào snapshots/Qdrant payload. Crawl root/result lưu manifest_ref/import_id, items/jobs không chứa toàn bộ HTML hoặc ảnh; external web data được sanitize/validate trước inference/hiển thị. Metadata địa danh và local resource budget ở [MVP địa danh](../planning/landmark-mvp-plan.md).


## Qdrant


Cập nhật: 05/11/2026. Đã xác nhận: dùng Qdrant lưu vector và metadata tìm kiếm, tách khỏi database quan hệ; không dùng pgvector. PostgreSQL đã được chọn cho DB quan hệ. Chi tiết schema, consistency và topology dưới đây là thiết kế cần kiểm chứng khi triển khai.

Thiết kế truy cập cập nhật: không ACL theo ảnh/collection, không feedback; tài khoản/role theo [xác thực và phân quyền](api-contract.md#auth).

Cập nhật C13: SQL còn 9 bảng; references/hashes/trạng thái projection nằm trong image_versions.index_state, con trỏ công bố là images.current_version, active config lấy từ search_configs và jobs đóng vai trò outbox. Không có projection/generation/published-pointer tables riêng.

### 1. Phân chia trách nhiệm dữ liệu

| Hệ lưu trữ | Dữ liệu | Vai trò |
| --- | --- | --- |
| Qdrant | Image vector; payload title, tags, kích thước, hướng ảnh, source, license, version và các trường tìm/lọc | Nguồn phục vụ vector search và search metadata |
| DB quan hệ | Identity ảnh, object references, phiên bản, tombstone, users/roles/refresh token registry, typed jobs kiêm outbox, image_versions.index_state/current_version, search_configs, search snapshots, audit | Nguồn chuẩn cho vòng đời, xác thực/phân quyền chức năng và quy trình nghiệp vụ |
| Graph storage adapter | Entity/aliases, relations có provenance, image_id/content_version/projection_revision và shared fact revisions | Nhánh graph search; engine chưa chốt, không thay Qdrant hoặc catalog |
| Object storage | Ảnh gốc, thumbnail, metadata snapshot bất biến, manifest và embedding artifact khi cần replay | Dữ liệu media và đầu vào tái dựng projection |

Không tạo bảng embedding hoặc bản sao đầy đủ search metadata trong SQL. Metadata snapshot trong object storage phục vụ rebuild/audit, không phải đường đọc metadata cho search. Các ID/version tồn tại ở hai hệ để liên kết và kiểm chứng, không có foreign key xuyên hệ.

Cập nhật 06/11/2026: graph search và VLM rerank thuộc phạm vi. [Thiết kế graph/rerank](graph-reranking-design.md) bổ sung đồng bộ hai projection và công bố chung; quy tắc point dưới đây tiếp tục áp dụng cho nhánh Qdrant.

Khi tìm kiếm, API lấy vector neighbors và payload từ Qdrant; DB quan hệ batch-check trạng thái và pointer đã công bố, không lọc theo người dùng. Detail đọc payload từ đúng point hiện tại sau kiểm tra access token hợp lệ và trạng thái thu hồi và catalog; search/thumbnail public, detail/download cần login. Nếu Qdrant lỗi, không giả định SQL có đủ metadata để thay thế.

### 2. Collections và point identity

Một generation ứng với một collection vật lý, ví dụ `images_g001`. Vector name đề xuất `image`; dimension và distance lấy từ search config, không cố định 768 cho mọi model. Một collection chứa nhiều business collections, tách bằng payload `collection_id`. Không tạo một collection Qdrant cho từng người dùng hoặc thư mục.

Point ID là UUID xác định từ generation_id + image_id + content_version + projection_revision. Cùng projection luôn có cùng vector/payload hash; retry upsert cùng ID phải gửi cùng nội dung. Nếu nội dung/payload cần sửa thì tạo revision/point mới, không ghi đè point đã công bố. ID khác giữa hai revision để write trễ của worker cũ không thể đè metadata mới.

projection_revision là bản dựng snapshot tìm kiếm, được cấp bền vững trước enqueue. Metadata-only update tạo content version mới nhưng có thể dùng lại vector nếu byte hash/model/processor trùng. Lease token không tham gia point identity, tránh tạo bản trùng chỉ vì retry worker.

### 3. Payload đề xuất

Ví dụ payload, không phải toàn bộ request upsert; vector không xuất hiện trong ví dụ:

```json
{
  "schema_version": 1,
  "image_id": "33333333-3333-4333-8333-333333333333",
  "collection_id": "11111111-1111-4111-8111-111111111111",
  "source_id": "44444444-4444-4444-8444-444444444444",
  "source_type": "private",
  "content_version": 1,
  "projection_revision": 1,
  "generation_id": "g001",
  "title": "Không gian cà phê",
  "tags": ["nội thất", "ánh sáng tự nhiên"],
  "width": 1600,
  "height": 1000,
  "orientation": "landscape",
  "mime_type": "image/jpeg",
  "license": null,
  "source_name": "Kho nội bộ",
  "provenance": null,
  "created_at": "2026-11-05T03:00:00Z"
}
```

C14–C18 bổ sung payload source_type=web_import cho ảnh web đã nhập kho (private vẫn hợp lệ), description/source_description/description_vi nullable, place_ids/aliases và provenance/attribution theo [MVP địa danh](../planning/landmark-mvp-plan.md). Chỉ index description/title/tags thực sự dùng lexical; relations/facts vẫn ở graph artifacts, không thêm SQL table.

Không lưu secret, signed URL, mật khẩu/access hoặc refresh token hoặc raw user query trong payload. Object keys do catalog quản lý; API xác thực khi cấp preview/download URL. Thumbnail là public ở mức sản phẩm. Caption/OCR chỉ thêm khi có pipeline, provenance và phiên bản rõ ràng. Lifecycle nếu mirror vào payload chỉ là tín hiệu tối ưu, không phải nguồn quyết định xóa hoặc trạng thái tài khoản.

Qdrant hỗ trợ payload và indexes theo trường; exact match chuỗi và tìm nội dung văn bản có cách đánh index khác nhau. [Payload](https://qdrant.tech/documentation/concepts/payload/), [payload indexing](https://qdrant.tech/documentation/manage-data/indexing/).

### 4. Payload indexes và truy vấn

| Trường | Loại index đề xuất | Nhu cầu |
| --- | --- | --- |
| collection_id | keyword | Phân loại, filter người dùng tùy chọn; không ACL |
| image_id | keyword | Đối soát và purge mọi version của ảnh |
| source_id/source_type | keyword khi bật filter nguồn | Nguồn ảnh và mở rộng |
| orientation | keyword | Landscape/portrait/square |
| width/height | integer | Range filter kích thước |
| tags | keyword nếu có filter tag | Khớp tag chuẩn hóa |
| title/caption/ocr_text | text khi thực sự dùng nhánh văn bản | Cần đánh giá tokenizer tiếng Việt |

Không index mọi payload field mặc định. Full-text filter không tự đồng nghĩa với lexical ranking/BM25; nhánh từ khóa phải đặc tả cách sinh score, phiên bản Qdrant và cấu hình fusion trong retrieval profile rồi benchmark riêng.

API chọn generation/profile, tìm toàn kho và chỉ đưa filters người dùng chọn vào Qdrant, yêu cầu payload fields cần dùng và không trả vector ra client. Sau retrieval, loại candidate nếu không khớp published point/version, deleted hoặc chưa công bố trong DB quan hệ. Overfetch có giới hạn để bù point chưa công bố/cũ; nếu cần, trả ít kết quả thay vì bỏ filters. Theo dõi tỷ lệ candidate bị loại để phát hiện sync lag hoặc cleanup chậm.

### 5. Outbox và công bố dữ liệu

1. Transaction DB quan hệ tạo desired_version, index_state entry, snapshot/artifact references và sync jobs theo target/generation. Metadata snapshot được ghi bất biến trước commit; embedding có thể lưu artifact để retry không phải inference lại.
2. Worker claim sync job với lease/fencing; đọc snapshot/artifact theo hash, kiểm tra lifecycle/version trước gửi.
3. Upsert vector + payload Qdrant cùng một point, chờ thao tác áp dụng và kiểm tra khả năng đọc theo cấu hình consistency đã chọn. Timeout chưa rõ kết quả được retry cùng ID/nội dung, không sinh projection mới.
4. Chờ graph projection cùng version đã được xác minh theo [graph consistency](graph-reranking-design.md). Transaction DB quan hệ so lease, desired_version, generation và lifecycle; nếu hợp lệ đánh dấu cả hai index_state entries ready, cập nhật images.current_version, tăng search_configs.graph_revision và hoàn tất publish/item jobs. Target jobs chỉ ghi ready entry sau xác minh; ready entry chưa thuộc current_version vẫn là staging. Nếu graph chưa ready, giữ point staging và retry target graph, không công bố version mới. Nếu không hợp lệ, point thành artifact chưa công bố, đưa vào cleanup.
5. Chỉ sau bước 4 ảnh được coi searchable. Không cần một payload flag ready để thay cho pointer SQL; point có thể được Qdrant tìm thấy trước commit nhưng API phải loại.

Write Qdrant đã bay đi có thể hoàn tất sau khi lease mất hoặc ảnh bị xóa. Fencing SQL không ngăn được việc đó. Bảo vệ bằng point revision bất biến + pointer công bố có điều kiện + final catalog check; purge/reconciliation lặp lại để dọn point xuất hiện trễ. Không tuyên bố có transaction nguyên tử giữa hai hệ.

`wait`, write ordering và read consistency của Qdrant cần cấu hình, kiểm chứng theo topology/version được pin; chúng không tạo transaction với DB quan hệ. Với replica, không chỉ dựa vào một ACK để kết luận mọi đường đọc đã thấy point. [Qdrant consistency guarantees](https://qdrant.tech/documentation/scaling/consistency-guarantees/).

### 6. Cập nhật, xóa và phục hồi

Update: tạo version/projection mới, upsert, xác minh rồi công bố pointer; version cũ tiếp tục phục vụ cho tới khi mới sẵn sàng. Sau công bố, point cũ không còn hợp lệ cho response mới, được dọn theo retention. Session snapshot chỉ giữ ID/version/point_id; mỗi trang vẫn kiểm tra pointer và lifecycle hiện tại.

Delete: commit tombstone cùng outbox trước; API chặn ngay theo catalog, không đợi Qdrant delete. Worker xóa mọi point của image_id ở tất cả generation còn tồn tại, không chỉ current point; dọn lại khi tác vụ cũ kết thúc và trong reconciliation. Không báo physical purge complete khi còn writer/lease chưa được giải quyết. TTL signed URL đã cấp vẫn tuân theo API contract.

Reconciliation: catalog ready thiếu point → replay từ artifact hoặc snapshot/model đã pin; Qdrant point không có intent/pointer hợp lệ → dọn sau grace period; payload hash lệch → cảnh báo, không âm thầm chấp nhận; deleted image còn point → enqueue purge. Scan theo batch/checkpoint, không nạp toàn kho vào RAM.

### 7. Reindex, backup và cấu hình scale

Tạo collection generation mới trong search_configs building; dùng maintenance window chặn/drain ghi catalog và shared graph facts, rồi backfill/reconcile trên dữ liệu đứng yên. Mỗi image_versions giữ entries cho bản cũ/mới trong index_state. Trước cutover tạm dừng/drain search, đổi active config nguyên tử và vô hiệu hóa search_sessions cũ. Chưa có dual-write/catch-up hoặc rollback online tự động. Alias Qdrant không được là nguồn cấu hình đọc thứ hai. [Runbook maintenance](operations.md) quy định gate mở lại ghi và rollback khi dữ liệu đã đổi.

Backup gồm DB quan hệ, Qdrant snapshot, graph snapshot hoặc artifacts đủ rebuild và object storage/metadata snapshots. Graph pointers/shared facts và graph_revision phải được đối soát trước phục vụ. Restore cách ly, đối soát generations/pointers/tombstones/payload hashes rồi mới phục vụ; snapshot các hệ không mặc định cùng một thời điểm. Không cho rebuild hoặc replay làm sống lại ảnh đã xóa.

Số shard, replication factor, on-disk vector/payload và quantization chưa chốt. Benchmark 100k/1M phải đo riêng vector index, payload index, sync backlog và API catalog recheck. Đếm cả version cũ, point chưa công bố, hai generation và metadata snapshots khi dự toán dung lượng. Không tạo cluster chỉ vì đạt một triệu ảnh.
