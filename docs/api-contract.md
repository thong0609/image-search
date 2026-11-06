# Hợp đồng API MVP

Trạng thái: đặc tả đề xuất v0.1, chưa phải API đã triển khai. Prefix `/v1`; JSON UTF-8; thời gian ISO 8601 UTC. Giới hạn cấu hình được nêu để review, không phải giá trị đã benchmark.

Cập nhật 05/11/2026: search metadata đọc từ Qdrant payload; DB quan hệ kiểm tra lifecycle/published point và tài khoản/role theo chức năng. Thiết kế lưu trữ thay đổi không làm đổi public request/response dưới đây.

Cập nhật 06/11/2026: pipeline gồm vector/keyword/graph → fusion → VLM rerank. Client vẫn gửi query/filters; không gửi raw graph query, tên model hoặc credentials. Server chọn active row trong search_configs đã version; SQL hiện hành gồm 9 bảng theo C13. Chi tiết ở [graph và reranking](graph-reranking-design.md).

## 1. Quy ước chung

Search/thumbnail public; detail/download cần access token hợp lệ; admin endpoints cần admin. Login/logout, account và role theo [auth-design.md](auth-design.md). Không có collection grants hoặc ACL theo ảnh. Không tin user_id hoặc role tự khai trong JSON. UUID được biểu diễn bằng chuỗi; timestamp và ID trong ví dụ là minh họa.

Mỗi response có header `X-Request-ID`; body JSON có request_id. Request ID dùng truy vết HTTP; search_id nhận diện snapshot kết quả qua nhiều trang. Frontend không hiển thị raw similarity như xác suất.

Request có trường không được hỗ trợ bị từ chối bằng 422. Các API ghi có thể nhận `Idempotency-Key`; bắt buộc cho tạo import. Key được scope theo principal/endpoint, giữ tối thiểu 24 giờ ở thiết kế pilot. Retry cùng body trả cùng tài nguyên; cùng key khác body trả 409. Sau thời hạn này client phải tra tài nguyên trước khi tạo lại.

Lỗi có cấu trúc:

```json
{
  "request_id": "req-example",
  "error": {
    "code": "INVALID_QUERY",
    "message": "Nội dung tìm kiếm không được để trống.",
    "details": [{"field": "query", "reason": "blank"}],
    "retryable": false
  }
}
```

| HTTP | Code tiêu biểu | Hành vi client |
| --- | --- | --- |
| 400 | INVALID_CURSOR, INVALID_JSON | Sửa request; không retry nguyên trạng |
| 401 | UNAUTHENTICATED, ACCESS_TOKEN_EXPIRED, INVALID_ACCESS_TOKEN, TOKEN_REVOKED, INVALID_REFRESH_TOKEN, TOKEN_REUSE_DETECTED | Chỉ refresh với ACCESS_TOKEN_EXPIRED; các lỗi còn lại xử lý theo auth-design, không lặp vô hạn |
| 403 | FORBIDDEN_ROLE, AUTH_ORIGIN_REJECTED | Kiểm tra role hoặc Origin/custom header của auth endpoints; không liên quan ACL ảnh |
| 404 | RESOURCE_NOT_FOUND | Tài nguyên không tồn tại, chưa công bố hoặc đã xóa |
| 409 | IDEMPOTENCY_CONFLICT, STALE_VERSION, JOB_NOT_RETRYABLE | Đọc lại trạng thái trước khi thao tác |
| 410 | SEARCH_EXPIRED | Tìm lại từ trang đầu |
| 422 | INVALID_QUERY, INVALID_FILTER, INVALID_MANIFEST, TOKEN_LIMIT_EXCEEDED | Hiển thị lỗi theo field |
| 429 | RATE_LIMITED | Chờ theo Retry-After; retry có giới hạn |
| 503 | SEARCH_UNAVAILABLE, DEPENDENCY_UNAVAILABLE, MAINTENANCE_MODE | Retry có giới hạn, giữ query; bảo trì có Retry-After, không lặp mù thao tác ghi |
| 504 | SEARCH_TIMEOUT | Thông báo timeout, cho tìm lại |

Lỗi không đưa stack trace, đường dẫn nội bộ, token, credentials hoặc signed URL vào details. Unexpected error trả 500 INTERNAL_ERROR với request_id.

## 2. POST /v1/search

Public, không yêu cầu đăng nhập. Tạo snapshot tìm kiếm trên toàn bộ kho ảnh đã công bố. Search response chỉ có thumbnail, không có original/preview/download URL.

```json
{
  "query": "quán cà phê có nội thất gỗ và ánh sáng tự nhiên",
  "filters": {
    "collection_ids": ["11111111-1111-4111-8111-111111111111"],
    "orientation": "landscape",
    "min_width": 1200,
    "min_height": 800
  },
  "limit": 20
}
```

- query: bắt buộc, trim và chuẩn hóa Unicode NFC, 1–500 ký tự Unicode sau chuẩn hóa. Kiểm tra thêm giới hạn token của profile, không âm thầm cắt câu.
- filters: tùy chọn; collection_ids nếu có phải là danh sách ID phân loại không rỗng, không trùng; không có thì tìm toàn kho. Đây là lựa chọn lọc, không phải quyền. ID hợp lệ nhưng không có ảnh cho kết quả rỗng, không trả lỗi quyền.
- orientation: landscape khi width > height; portrait khi height > width; square khi bằng nhau. Không dùng dung sai ngầm.
- min_width/min_height: integer dương nếu có. Các filters kết hợp AND; collection_ids kết hợp OR trong chính danh sách.
- limit: mặc định 20, từ 1 đến 50. Không nhận bộ lọc tenant/principal do client tự định nghĩa.

Response 200:

```json
{
  "request_id": "req-example",
  "search_id": "22222222-2222-4222-8222-222222222222",
  "items": [
    {
      "id": "33333333-3333-4333-8333-333333333333",
      "content_version": 1,
      "title": "Không gian cà phê",
      "width": 1600,
      "height": 1000,
      "thumbnail_url": "https://media.example.com/signed-thumbnail",
      "url_expires_at": "2026-11-04T10:05:00Z",
      "source": {"type": "private", "name": "Kho nội bộ"}
    }
  ],
  "next_cursor": null,
  "expires_at": "2026-11-04T10:15:00Z",
  "degraded": false,
  "degradation_reason": null
}
```

Title có thể null; không suy diễn caption. Kết quả rỗng hợp lệ: items=[], next_cursor=null và HTTP 200. Không trả total_count vì đây là danh sách xếp hạng hữu hạn, không phải đếm toàn bộ ảnh phù hợp. Thông số encoder, vector/graph generation, graph revision, entity-linker, fusion và VLM model/processor/prompt/failure policy được lưu server-side để truy vết.

Graph query dùng thực thể/quan hệ trích từ query theo taxonomy; không thêm graph query language hoặc endpoint graph công khai. Query không có ý định quan hệ có thể skip graph theo profile mà không degraded. Điều kiện quan hệ bắt buộc luôn phải được kiểm chứng; entity không tồn tại cho kết quả rỗng hợp lệ, entity mơ hồ không giải được trả 422 INVALID_QUERY với details.field=query.

Strict là mặc định. Graph/VLM dependency lỗi trả 503 SEARCH_UNAVAILABLE, deadline trả 504 SEARCH_TIMEOUT; không giả thành items rỗng. Nếu profile cho phép fallback, degraded=true và degradation_reason thuộc GRAPH_UNAVAILABLE, GRAPH_BUDGET_EXCEEDED, RERANK_TIMEOUT, RERANK_INVALID_OUTPUT, RERANK_UNAVAILABLE hoặc MULTIPLE_COMPONENT_FAILURES. Không fallback bỏ hard graph constraint. Bỏ toàn bộ output VLM khi rerank lỗi, dùng fusion order của shortlist đã kiểm chứng. Không thể đọc catalog/Qdrant thì luôn fail. Revision graph đổi trong lúc tìm kiếm được retry hữu hạn trong deadline; hết budget trả 503 SEARCH_UNAVAILABLE. UI hiển thị thông báo ngắn khi degraded, không cần lộ model/hạ tầng.

## 3. Phân trang: POST /v1/search với cursor

Request tiếp theo chỉ chứa `cursor` và tùy chọn `limit`; không được đồng thời chứa query hoặc filters. Cursor được ký hoặc là token ngẫu nhiên opaque, ràng buộc search_id, hash owner_key từ X-Search-Owner và vị trí; TTL đề xuất 15 phút từ lúc tạo phiên. Client coi cursor là opaque, không tự giải mã/sửa.

Server lưu items JSON trong search_sessions, tối đa 200 ID/version/point_id đã xếp hạng mỗi phiên làm cửa sổ kết quả ban đầu. Với VLM, chỉ lưu shortlist đã rerank: ví dụ rerank_window=50 thì snapshot tối đa 50 dù trần API là 200; không nối tail chưa được chấm. Với chế độ duyệt, window cấu hình ít nhất bằng limit request; với count hữu hạn theo mục 13, window đủ số ảnh cần trả và có thể nhỏ hơn limit trang; ít ứng viên hợp lệ hơn thì trả số có được. Không gọi lại VLM hoặc chạy lại retrieval khi đọc cursor. Snapshot giữ degraded/degradation_reason từ lúc tạo cho mọi trang. Mỗi trang kiểm tra lại trạng thái/published point, bỏ item bị xóa, chưa công bố hoặc đổi version, tiến tiếp trong snapshot để lấp trang. Không đưa ảnh mới vào snapshot. next_cursor=null khi hết cửa sổ, kể cả kho vẫn còn ảnh; UI chỉ nói đã hết kết quả của lượt tìm này.

Cùng cursor và limit trả cùng vị trí logic, nhưng response có thể ít item hơn khi dữ liệu thay đổi. Thumbnail URL được cấp mới theo request. Trang nối tiếp không lặp ID trong một chuỗi cursor. Cursor khác owner_key hoặc bị sửa trả 400 INVALID_CURSOR; snapshot hết hạn hoặc config_id không còn active trả 410 SEARCH_EXPIRED. Nếu query có hard graph constraint và published graph_revision đổi, trả 410 SEARCH_EXPIRED và yêu cầu tìm lại; không tiếp tục trả ảnh dựa trên quan hệ cũ. Query chỉ dùng graph để boost giữ thứ tự snapshot, vẫn kiểm tra catalog/pointers. TTL và cửa sổ được benchmark để cân bằng chi phí lưu snapshot. X-Search-Owner là giá trị ngẫu nhiên tối thiểu 128 bit client giữ trong memory và gửi trên request tạo/đọc snapshot; server lưu hash, không dùng làm filter ảnh. Thiếu/không đúng định dạng key trả 400 INVALID_SEARCH_OWNER; key không khớp cursor trả INVALID_CURSOR. Không có cookie/session đăng nhập cho search; khi login/logout bắt đầu snapshot mới, refresh access token không đổi owner key.

## 4. GET /v1/images/{image_id}

Trả 200 với image metadata hiện tại: id, content_version, title, tags nếu có, width, height, mime_type, source, license nếu có, thumbnail_url, preview_url, url_expires_at và request_id. Bắt buộc Authorization: Bearer access_token, thiếu/không hợp lệ/hết hạn/đã thu hồi trả 401 với code cụ thể. Kiểm tra catalog rồi đọc payload từ đúng published point Qdrant; URL được tạo từ object references của version tương ứng. Trả 404 nếu ảnh chưa sẵn sàng, đã xóa. Catalog đã ready nhưng point mất/lỗi Qdrant trả 503 DEPENDENCY_UNAVAILABLE và kích hoạt đối soát, không giả thành 404 hoặc rỗng. Không nhận content_version tùy ý để truy cập bản lịch sử trong MVP.

Thumbnail được cấp qua search mà không login. Preview và download URL chỉ cấp sau xác thực, tối đa 5 phút ở thiết kế đề xuất. Signed URL đã cấp có thể dùng/chia sẻ đến hết TTL; không đảm bảo login được kiểm tra mỗi lần storage nhận request. Nếu cần điều đó, chọn media proxy theo Q05. Bucket ảnh gốc không public.

## 5. POST /v1/images/{image_id}/download

Bắt buộc Authorization: Bearer access_token hợp lệ; refresh cookie không đủ quyền gọi endpoint này. 401 nếu chưa login; 404 nếu ảnh chưa công bố/đã xóa. Mọi tài khoản active được tải mọi ảnh đang hiển thị, không kiểm tra collection grants. Response 200 gồm request_id, download_url và expires_at; URL ký dành cho ảnh gốc với Content-Disposition attachment, TTL đề xuất tối đa 5 phút. Không trả object_key hoặc credential. Không có endpoint feedback trong MVP.

## 6. POST /v1/admin/imports

Cần role admin toàn hệ thống; bắt buộc Idempotency-Key. Body gồm collection_id, source_id, manifest_key. manifest_key là object trong vùng nhập đã đăng ký; không chấp nhận URL tùy ý hoặc đường dẫn máy chủ từ client. source_id phải thuộc collection_id.

Manifest JSONL, mỗi dòng gồm source_item_key ổn định, input_revision integer tăng đơn điệu theo item, object_key thuộc nguồn được phép và metadata tùy chọn. Chi tiết validation ở [ingestion-design.md](ingestion-design.md). Revision nhỏ hơn bản đã nhận là superseded; cùng revision khác nội dung là conflict.

202 trả request_id, import_id, status=queued và status_url. Import root là row jobs type=import; mỗi item là row jobs type=import_item. API giữ nguyên import_id/item_id; không có bảng import/item riêng. Tạo import không đồng nghĩa ảnh đã searchable. Lỗi cấu trúc request trả đồng bộ; lỗi từng dòng manifest sau khi chạy parser được ghi trong result của import_item jobs, kể cả khi chưa tạo image_id. Giới hạn manifest đề xuất 10.000 dòng và 10 MiB mỗi import; một triệu ảnh chia nhiều import có manifest/checkpoint riêng.

## 7. GET /v1/admin/imports/{import_id}

200 gồm request_id, import_id, status, total_items nullable khi đang parse, counts theo từng trạng thái, created_at, updated_at. Status: queued/parsing/running/completed/completed_with_errors/failed.

Counts lấy từ child jobs type import_item, không đếm processing/sync jobs thành ảnh riêng.

GET `/v1/admin/imports/{import_id}/items?status=failed&limit=100&cursor=...` trả lỗi từng item theo ID tăng dần, cursor opaque; limit 1–100. Cần admin; user thường trả 403, chưa login trả 401. Error detail được làm sạch, không chứa dữ liệu bí mật.

## 8. POST /v1/admin/imports/{import_id}/retry

Body item_ids: 1–100 UUID không trùng, thuộc import và đang failed do nguyên nhân có thể thử lại sau khi quản trị sửa điều kiện. Tất cả item được kiểm tra trong một transaction; item không hợp lệ trả 409 và không reset/enqueue một phần. Chỉ retry bước lỗi có thể phục hồi, giữ target đã ready và projection identity/hash; cập nhật item/root progress cùng transaction. Retry không hồi sinh ảnh tombstone hoặc version đã superseded. Thành công 202 trả queued_item_count và request_id; gọi lại khi job pending/running trả 409 JOB_NOT_RETRYABLE.

Sửa ảnh hoặc metadata thực hiện qua import revision mới; không thêm endpoint update riêng khi chưa có nhu cầu chỉnh từng ảnh trên UI.

## 9. DELETE /v1/admin/images/{image_id}

Cần admin; user thường trả 403, chưa login trả 401. Header If-Match bắt buộc chứa metadata_revision do admin đọc từ import item/catalog quản trị; thiếu trả 428 PRECONDITION_REQUIRED, lệch trả 409 STALE_VERSION. Response 202 có request_id, image_id, lifecycle=deleted, purge_status=pending và metadata_revision mới.

Tombstone có hiệu lực với response mới sau commit; response hoặc URL đã cấp trước đó có thể còn dùng tới TTL. Lặp delete với revision hiện tại là no-op 202; không tạo lại purge job. Purge vật lý theo retention và backlog, trạng thái được xem ở GET `/v1/admin/images/{image_id}`.

## 10. GET /v1/admin/images/{image_id}

Cần admin. Trạng thái projection được suy từ image_versions.index_state đúng active config. Trả trạng thái cả ảnh active và deleted: image_id, collection_id, lifecycle, current_version, desired_version, metadata_revision, processing_status, vector_projection_status, graph_projection_status, purge_status, updated_at, request_id; header ETag chứa metadata_revision dạng quoted string. Không đủ role trả 403; chưa login trả 401.

## 11. Tài khoản và xác thực

Visitor là khách không đăng nhập, không tạo users record hoặc nhận role visitor từ API quản trị. Các trường role trong POST/PATCH user chỉ nhận user/admin; giá trị khác trả 422 INVALID_ROLE; POST mặc định user nếu bỏ role.

Theo [auth-design.md](auth-design.md), response tài khoản chỉ chứa id/email/display_name/role/status, revision và request_id; không trả hash hoặc refresh secret.

Mọi API protected chỉ nhận access JWT qua Authorization: Bearer; không dùng refresh cookie để xác thực tài nguyên. Refresh family không có bảng riêng: token root nằm trong refresh_tokens; JWT family_id trỏ root để kiểm tra revoke/deadline. Giữ nguyên hành vi rotation/reuse và access revocation. Các auth endpoints dùng cookie (login/refresh/logout) yêu cầu Origin allowlist, JSON và X-Auth-Request: 1 theo auth-design. Không có GET /auth/csrf hoặc cookie session.

| Endpoint | Hành vi | Quyền |
| --- | --- | --- |
| POST /v1/auth/login | email/password; 200 user + access_token/token_type/expires_in, Set-Cookie refresh; sai/disabled 401 INVALID_CREDENTIALS | Public, auth Origin/header policy |
| POST /v1/auth/refresh | Body {}; refresh cookie; 200 access token mới và rotate refresh cookie; token sai/hết hạn 401 INVALID_REFRESH_TOKEN, reuse 401 TOKEN_REUSE_DETECTED và revoke family | Refresh cookie, auth Origin/header policy; không đòi access còn hạn |
| GET /v1/auth/me | 200 user hiện tại hoặc 401 | Bearer access hợp lệ |
| POST /v1/auth/logout | Body {}; revoke family từ refresh cookie, xóa cookie; 200 logged_out=true idempotent nếu thiếu/token không tồn tại; lỗi ghi revoke 503 | Auth Origin/header policy; access hết hạn vẫn logout được |
| POST /v1/auth/logout-all | Body {}; tăng auth_version, revoke mọi family, xóa refresh cookie, 200 logged_out=true | Bearer access hợp lệ |
| POST /v1/auth/change-password | current_password/new_password; 200, tăng auth_version, revoke mọi family, xóa refresh cookie; sai current 401 INVALID_CREDENTIALS | Bearer access hợp lệ |
| POST /v1/admin/users | email/display_name/role/initial_password; 201 user; email trùng 409; không trả lại password | Bearer access, admin |
| GET /v1/admin/users | limit 1–100/cursor; trả revision, không hash/token | Bearer access, admin |
| PATCH /v1/admin/users/{id} | role/status/display_name; If-Match, thiếu 428/lệch 409; tăng auth_version và revoke families khi role/status đổi | Bearer access, admin |

Ví dụ JSON login/refresh thành công (refresh token chỉ ở Set-Cookie, không trong JSON):

```json
{
  "request_id": "req-auth-example",
  "access_token": "<signed-access-jwt>",
  "token_type": "Bearer",
  "expires_in": 900,
  "user": {
    "id": "55555555-5555-4555-8555-555555555555",
    "email": "user@example.com",
    "display_name": "Người dùng",
    "role": "user",
    "status": "active",
    "revision": 1
  }
}
```

Access TTL 900 giây và refresh family tuyệt đối 7 ngày là đề xuất. API kiểm tra chữ ký/claims, user active/auth_version và family chưa thu hồi trước protected action; JWT cũ không tiếp tục được dùng sau logout/đổi role theo chính sách này. Auth responses no-store; cookie refresh Secure/HttpOnly/SameSite=Strict/Path=/v1/auth. Không tự retry refresh sau response timeout vì token cũ có thể đã consumed; client phối hợp single-flight và login lại nếu mất kết quả rotation.

Import/retry/delete và mọi API quản trị cần bearer access + role admin; không yêu cầu synchronizer CSRF token gắn session. PATCH user không được vô hiệu hóa admin active cuối cùng, lỗi 409 LAST_ADMIN_REQUIRED. Không tự bật đăng ký công khai/gửi email; quy trình cấp tài khoản/recovery chờ Q12. TTL, JWT signing/key rotation và cookie transport còn là đề xuất cần chốt khi triển khai.

## 12. Health và versioning

`GET /health/live`: kiểm tra process còn hoạt động, không chạm dependency; `GET /health/ready`: 200 khi instance phục vụ được, 503 nếu encoder, Qdrant collection/profile, DB quan hệ, graph generation/revision hoặc VLM bắt buộc theo active profile chưa sẵn sàng. Readiness kiểm tra model/config đã nạp và dependency bằng probe nhẹ, không chạy full VLM rerank trên mỗi health request. Chỉ coi fallback là ready nếu profile cho phép và vẫn kiểm chứng được hard constraints. Health được giới hạn ở hạ tầng vận hành, không công khai topology hay credential.

Thêm field response tùy chọn được coi là tương thích; đổi nghĩa, xóa field hoặc làm request cũ mất hợp lệ cần version mới. Khi bắt đầu code, chuyển hợp đồng này thành OpenAPI và kiểm tra ví dụ bằng schema; hiện chưa có endpoint nào chạy.

C13 maintenance: tạo import/retry ghi, delete, metadata/fact updates và worker claims ngoài tập drain bị chặn khi writes_blocked; jobs trong tập drain bền vững được tiếp tục để hoàn tất barrier; API trả 503 MAINTENANCE_MODE có Retry-After, không nhận thao tác rồi âm thầm bỏ. Search có thể chạy trên config cũ trong build; khi search_blocked/cutover trả cùng lỗi bảo trì. Auth/account/detail/download tiếp tục nếu dependencies/version còn hợp lệ. Health/readiness phản ánh instance có phục vụ được search theo gate; liveness không fail chỉ vì bảo trì. Source_id/manifest_key được kiểm tra theo source config ref/hash đã đăng ký phía server, không yêu cầu bảng source.

## 13. Truy vấn địa danh, nhiều mục tiêu và multi-hop

C14–C18 bổ sung vào POST /v1/search các trường tùy chọn `mode` (auto mặc định, single, multi_target, multi_hop) và `results_per_target` (integer 1–5). Không gửi các trường mới vẫn hỗ trợ search duyệt thông thường; planner nhận diện nhiều targets khi có danh sách yêu cầu riêng như “ảnh Hạ Long, ảnh Cát Bà”. `limit` tiếp tục là kích thước trang 1–50, không quyết định số target hoặc số hops.

Ví dụ request multi-target:

```json
{
  "query": "Tìm ảnh Hạ Long, ảnh Cát Bà",
  "mode": "multi_target",
  "results_per_target": 1,
  "limit": 20
}
```

Planner đề xuất tối đa 5 targets, mỗi target resolve/place alias riêng. `results_per_target` mặc định 1 khi multi_target, hoặc suy từ yêu cầu số ảnh rõ ràng trong câu (ví dụ “cho tôi 1 ảnh Hạ Long”); count tường minh trong JSON và câu mâu thuẫn trả 422 INVALID_QUERY. Single/multi_hop không nêu count vẫn có thể duyệt theo limit như contract ban đầu. Multi-hop ở từng target là subplan graph, không bị mất khi query mode chính là multi_target. Các giới hạn này là thiết kế đề xuất cần kiểm thử bằng query thật.

Thêm fields response tùy chọn `query_mode`, `groups`, `partial`. Top-level items vẫn là list ảnh đầy đủ với schema cũ, dedup theo image_id. Groups có target_id, label, resolved entity IDs, image_ids tham chiếu top-level items, status=ok/no_match/insufficient và evidence gồm entity IDs/predicates/source URLs hoặc source revision công khai phù hợp. Không trả object keys/secret hoặc chain-of-thought. Nếu một ảnh thuộc nhiều target đã xác minh, nhóm tham chiếu cùng ID; không nhân đôi top-level item. Client dùng groups để hiển thị đúng target thay vì coi thứ tự flat là quota từng nơi.

Mỗi nhóm được lấy/rerank riêng trong budget chung request, tối đa 50 ảnh VLM/request theo cấu hình thử; không lấy top-2 của một embedding cả câu. Với count hữu hạn, snapshot chỉ giữ số ảnh đã chọn cho mỗi target, không thêm tail vượt count; nếu tất cả kết quả vừa trang đầu thì next_cursor=null. Khi nhiều trang, nhóm chỉ liệt kê IDs thuộc trang hiện tại, còn statuses/counts cuối lấy từ query_plan snapshot; cursor giữ group membership và vị trí, không rerank lại.

partial=true nếu có nhóm no_match/insufficient trong khi nhóm khác có ảnh; không bù bằng ảnh của nơi khác. Nếu mọi nhóm không có ảnh hợp lệ thì items=[], groups có trạng thái rỗng, next_cursor=null, HTTP 200 và partial=false. Thiếu ảnh hợp lệ không đồng nghĩa degraded; lỗi dependency vẫn theo strict/fallback trước đó, không chuyển thành nhóm no_match. Entity mơ hồ không giải được trả 422 INVALID_QUERY có target_id trong details; chưa chọn entity thì không gán no_match tùy tiện.

Search_sessions lưu query_plan JSON (mode, target IDs/labels/entities, counts/statuses/evidence refs) và items JSON với target_ids, giữ config_id/graph_revision và expires_at. Không tạo bảng query/target/result riêng. Query nhạy cảm và evidence retention vẫn theo Q09. Multi-hop evidence/path phải khớp graph revision đã chụp, được final-check sau VLM; không tự thêm facts từ trí nhớ model.

## 14. Crawl nguồn web — admin

Đề xuất POST /v1/admin/crawls cần admin và Idempotency-Key, body source_id, seed_entity_ids/category IDs theo source config, max_images và collection_id. Source/prefix/download host, quota/rate và accept rules lấy từ config server; không nhận URL bất kỳ hoặc graph query. Đề xuất max_images 1–1.500 cho đợt sample, source adapter có thể giới hạn thấp hơn. Request hợp lệ trả 202 request_id/crawl_id/status_url; crawl_id là jobs.id type crawl.

GET /v1/admin/crawls/{crawl_id} trả status, checkpoint progress, discovered/accepted/downloaded/rejected/failed counts và import_id nullable khi manifest đã được chuyển vào import pipeline. GET /v1/admin/crawls/{crawl_id}/items với cursor/limit 1–100 đọc jobs type crawl_item và lỗi đã làm sạch. Counts crawl không phải số ảnh searchable; trạng thái publish xem qua import_id. Không thêm public crawl/search-provider endpoint hoặc bảng SQL.

Crawl job và các jobs fetch_media/crawl_item chạy có dedupe/checkpoint; nguồn/tải lỗi giữ trạng thái riêng, không làm mất metadata/attribution. Maintenance writes_blocked chặn crawl mới và claim ngoài tập drain như import; không tải không giới hạn rồi bỏ checkpoint. Retry request tạo crawl cùng idempotency key/body trả cùng root; khác body trả 409. Retry tự động hữu hạn theo job policy; chưa thêm endpoint admin retry crawl riêng khi chưa đặc tả workflow.
