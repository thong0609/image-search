# Thiết kế Qdrant và ranh giới với DB quan hệ

Cập nhật: 05/11/2026. Đã xác nhận: dùng Qdrant lưu vector và metadata tìm kiếm, tách khỏi database quan hệ; không dùng pgvector. PostgreSQL đã được chọn cho DB quan hệ. Chi tiết schema, consistency và topology dưới đây là thiết kế cần kiểm chứng khi triển khai.

Thiết kế truy cập cập nhật: không ACL theo ảnh/collection, không feedback; tài khoản/role theo [auth-design.md](auth-design.md).

Cập nhật C13: SQL còn 9 bảng; references/hashes/trạng thái projection nằm trong image_versions.index_state, con trỏ công bố là images.current_version, active config lấy từ search_configs và jobs đóng vai trò outbox. Không có projection/generation/published-pointer tables riêng.

## 1. Phân chia trách nhiệm dữ liệu

| Hệ lưu trữ | Dữ liệu | Vai trò |
| --- | --- | --- |
| Qdrant | Image vector; payload title, tags, kích thước, hướng ảnh, source, license, version và các trường tìm/lọc | Nguồn phục vụ vector search và search metadata |
| DB quan hệ | Identity ảnh, object references, phiên bản, tombstone, users/roles/refresh token registry, typed jobs kiêm outbox, image_versions.index_state/current_version, search_configs, search snapshots, audit | Nguồn chuẩn cho vòng đời, xác thực/phân quyền chức năng và quy trình nghiệp vụ |
| Graph storage adapter | Entity/aliases, relations có provenance, image_id/content_version/projection_revision và shared fact revisions | Nhánh graph search; engine chưa chốt, không thay Qdrant hoặc catalog |
| Object storage | Ảnh gốc, thumbnail, metadata snapshot bất biến, manifest và embedding artifact khi cần replay | Dữ liệu media và đầu vào tái dựng projection |

Không tạo bảng embedding hoặc bản sao đầy đủ search metadata trong SQL. Metadata snapshot trong object storage phục vụ rebuild/audit, không phải đường đọc metadata cho search. Các ID/version tồn tại ở hai hệ để liên kết và kiểm chứng, không có foreign key xuyên hệ.

Cập nhật 06/11/2026: graph search và VLM rerank thuộc phạm vi. [Thiết kế graph/rerank](graph-reranking-design.md) bổ sung đồng bộ hai projection và công bố chung; quy tắc point dưới đây tiếp tục áp dụng cho nhánh Qdrant.

Khi tìm kiếm, API lấy vector neighbors và payload từ Qdrant; DB quan hệ batch-check trạng thái và pointer đã công bố, không lọc theo người dùng. Detail đọc payload từ đúng point hiện tại sau kiểm tra access token hợp lệ và trạng thái thu hồi và catalog; search/thumbnail public, detail/download cần login. Nếu Qdrant lỗi, không giả định SQL có đủ metadata để thay thế.

## 2. Collections và point identity

Một generation ứng với một collection vật lý, ví dụ `images_g001`. Vector name đề xuất `image`; dimension và distance lấy từ search config, không cố định 768 cho mọi model. Một collection chứa nhiều business collections, tách bằng payload `collection_id`. Không tạo một collection Qdrant cho từng người dùng hoặc thư mục.

Point ID là UUID xác định từ generation_id + image_id + content_version + projection_revision. Cùng projection luôn có cùng vector/payload hash; retry upsert cùng ID phải gửi cùng nội dung. Nếu nội dung/payload cần sửa thì tạo revision/point mới, không ghi đè point đã công bố. ID khác giữa hai revision để write trễ của worker cũ không thể đè metadata mới.

projection_revision là bản dựng snapshot tìm kiếm, được cấp bền vững trước enqueue. Metadata-only update tạo content version mới nhưng có thể dùng lại vector nếu byte hash/model/processor trùng. Lease token không tham gia point identity, tránh tạo bản trùng chỉ vì retry worker.

## 3. Payload đề xuất

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

C14–C18 bổ sung payload source_type=web_import cho ảnh web đã nhập kho (private vẫn hợp lệ), description/source_description/description_vi nullable, place_ids/aliases và provenance/attribution theo [MVP địa danh](landmark-mvp-plan.md). Chỉ index description/title/tags thực sự dùng lexical; relations/facts vẫn ở graph artifacts, không thêm SQL table.

Không lưu secret, signed URL, mật khẩu/access hoặc refresh token hoặc raw user query trong payload. Object keys do catalog quản lý; API xác thực khi cấp preview/download URL. Thumbnail là public ở mức sản phẩm. Caption/OCR chỉ thêm khi có pipeline, provenance và phiên bản rõ ràng. Lifecycle nếu mirror vào payload chỉ là tín hiệu tối ưu, không phải nguồn quyết định xóa hoặc trạng thái tài khoản.

Qdrant hỗ trợ payload và indexes theo trường; exact match chuỗi và tìm nội dung văn bản có cách đánh index khác nhau. [Payload](https://qdrant.tech/documentation/concepts/payload/), [payload indexing](https://qdrant.tech/documentation/manage-data/indexing/).

## 4. Payload indexes và truy vấn

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

## 5. Outbox và công bố dữ liệu

1. Transaction DB quan hệ tạo desired_version, index_state entry, snapshot/artifact references và sync jobs theo target/generation. Metadata snapshot được ghi bất biến trước commit; embedding có thể lưu artifact để retry không phải inference lại.
2. Worker claim sync job với lease/fencing; đọc snapshot/artifact theo hash, kiểm tra lifecycle/version trước gửi.
3. Upsert vector + payload Qdrant cùng một point, chờ thao tác áp dụng và kiểm tra khả năng đọc theo cấu hình consistency đã chọn. Timeout chưa rõ kết quả được retry cùng ID/nội dung, không sinh projection mới.
4. Chờ graph projection cùng version đã được xác minh theo [graph consistency](graph-reranking-design.md). Transaction DB quan hệ so lease, desired_version, generation và lifecycle; nếu hợp lệ đánh dấu cả hai index_state entries ready, cập nhật images.current_version, tăng search_configs.graph_revision và hoàn tất publish/item jobs. Target jobs chỉ ghi ready entry sau xác minh; ready entry chưa thuộc current_version vẫn là staging. Nếu graph chưa ready, giữ point staging và retry target graph, không công bố version mới. Nếu không hợp lệ, point thành artifact chưa công bố, đưa vào cleanup.
5. Chỉ sau bước 4 ảnh được coi searchable. Không cần một payload flag ready để thay cho pointer SQL; point có thể được Qdrant tìm thấy trước commit nhưng API phải loại.

Write Qdrant đã bay đi có thể hoàn tất sau khi lease mất hoặc ảnh bị xóa. Fencing SQL không ngăn được việc đó. Bảo vệ bằng point revision bất biến + pointer công bố có điều kiện + final catalog check; purge/reconciliation lặp lại để dọn point xuất hiện trễ. Không tuyên bố có transaction nguyên tử giữa hai hệ.

`wait`, write ordering và read consistency của Qdrant cần cấu hình, kiểm chứng theo topology/version được pin; chúng không tạo transaction với DB quan hệ. Với replica, không chỉ dựa vào một ACK để kết luận mọi đường đọc đã thấy point. [Qdrant consistency guarantees](https://qdrant.tech/documentation/scaling/consistency-guarantees/).

## 6. Cập nhật, xóa và phục hồi

Update: tạo version/projection mới, upsert, xác minh rồi công bố pointer; version cũ tiếp tục phục vụ cho tới khi mới sẵn sàng. Sau công bố, point cũ không còn hợp lệ cho response mới, được dọn theo retention. Session snapshot chỉ giữ ID/version/point_id; mỗi trang vẫn kiểm tra pointer và lifecycle hiện tại.

Delete: commit tombstone cùng outbox trước; API chặn ngay theo catalog, không đợi Qdrant delete. Worker xóa mọi point của image_id ở tất cả generation còn tồn tại, không chỉ current point; dọn lại khi tác vụ cũ kết thúc và trong reconciliation. Không báo physical purge complete khi còn writer/lease chưa được giải quyết. TTL signed URL đã cấp vẫn tuân theo API contract.

Reconciliation: catalog ready thiếu point → replay từ artifact hoặc snapshot/model đã pin; Qdrant point không có intent/pointer hợp lệ → dọn sau grace period; payload hash lệch → cảnh báo, không âm thầm chấp nhận; deleted image còn point → enqueue purge. Scan theo batch/checkpoint, không nạp toàn kho vào RAM.

## 7. Reindex, backup và cấu hình scale

Tạo collection generation mới trong search_configs building; dùng maintenance window chặn/drain ghi catalog và shared graph facts, rồi backfill/reconcile trên dữ liệu đứng yên. Mỗi image_versions giữ entries cho bản cũ/mới trong index_state. Trước cutover tạm dừng/drain search, đổi active config nguyên tử và vô hiệu hóa search_sessions cũ. Chưa có dual-write/catch-up hoặc rollback online tự động. Alias Qdrant không được là nguồn cấu hình đọc thứ hai. [Runbook maintenance](operations.md) quy định gate mở lại ghi và rollback khi dữ liệu đã đổi.

Backup gồm DB quan hệ, Qdrant snapshot, graph snapshot hoặc artifacts đủ rebuild và object storage/metadata snapshots. Graph pointers/shared facts và graph_revision phải được đối soát trước phục vụ. Restore cách ly, đối soát generations/pointers/tombstones/payload hashes rồi mới phục vụ; snapshot các hệ không mặc định cùng một thời điểm. Không cho rebuild hoặc replay làm sống lại ảnh đã xóa.

Số shard, replication factor, on-disk vector/payload và quantization chưa chốt. Benchmark 100k/1M phải đo riêng vector index, payload index, sync backlog và API catalog recheck. Đếm cả version cũ, point chưa công bố, hai generation và metadata snapshots khi dự toán dung lượng. Không tạo cluster chỉ vì đạt một triệu ảnh.
