# Hợp đồng API MVP

Cập nhật triển khai website 27/11/2026: auth/account, filters, snapshot, quản trị gỡ ảnh và nhập CSV
theo batch đã có. Luồng CSV có API preview/upload, tiến độ, errors.csv và retry.
API tìm kiếm giữ `groups` của luồng hiện hành; ảnh gốc qua proxy bearer thay signed URL.
Xem [hướng dẫn website](../guides/website.md); hợp đồng manifest import, crawl, maintenance đầy đủ và VLM bên dưới vẫn là đặc tả;
không coi chúng là endpoint đã hoàn thành.

Trạng thái: đặc tả đề xuất v0.1, chưa phải API đã triển khai. Prefix `/v1`; JSON UTF-8; thời gian ISO 8601 UTC. Giới hạn cấu hình được nêu để review, không phải giá trị đã benchmark.

Cập nhật 05/11/2026: search metadata đọc từ Qdrant payload; DB quan hệ kiểm tra lifecycle/published point và tài khoản/role theo chức năng. Thiết kế lưu trữ thay đổi không làm đổi public request/response dưới đây.

Cập nhật 06/11/2026: pipeline gồm vector/keyword/graph → fusion → VLM rerank. Client vẫn gửi query/filters; không gửi raw graph query, tên model hoặc credentials. Server chọn active row trong search_configs đã version; SQL hiện hành gồm 9 bảng theo C13. Chi tiết ở [graph và reranking](graph-reranking-design.md).

## 1. Quy ước chung

Search/thumbnail public; detail/download cần access token hợp lệ; admin endpoints cần admin. Login/logout, account và role theo [xác thực và phân quyền](api-contract.md#auth). Không có collection grants hoặc ACL theo ảnh. Không tin user_id hoặc role tự khai trong JSON. UUID được biểu diễn bằng chuỗi; timestamp và ID trong ví dụ là minh họa.

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

Theo [xác thực và phân quyền](api-contract.md#auth), response tài khoản chỉ chứa id/email/display_name/role/status, revision và request_id; không trả hash hoặc refresh secret.

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

## 14. Crawl nguồn web — admin

Đề xuất POST /v1/admin/crawls cần admin và Idempotency-Key, body source_id, seed_entity_ids/category IDs theo source config, max_images và collection_id. Source/prefix/download host, quota/rate và accept rules lấy từ config server; không nhận URL bất kỳ hoặc graph query. Đề xuất max_images 1–1.500 cho đợt sample, source adapter có thể giới hạn thấp hơn. Request hợp lệ trả 202 request_id/crawl_id/status_url; crawl_id là jobs.id type crawl.

GET /v1/admin/crawls/{crawl_id} trả status, checkpoint progress, discovered/accepted/downloaded/rejected/failed counts và import_id nullable khi manifest đã được chuyển vào import pipeline. GET /v1/admin/crawls/{crawl_id}/items với cursor/limit 1–100 đọc jobs type crawl_item và lỗi đã làm sạch. Counts crawl không phải số ảnh searchable; trạng thái publish xem qua import_id. Không thêm public crawl/search-provider endpoint hoặc bảng SQL.

Crawl job và các jobs fetch_media/crawl_item chạy có dedupe/checkpoint; nguồn/tải lỗi giữ trạng thái riêng, không làm mất metadata/attribution. Maintenance writes_blocked chặn crawl mới và claim ngoài tập drain như import; không tải không giới hạn rồi bỏ checkpoint. Retry request tạo crawl cùng idempotency key/body trả cùng root; khác body trả 409. Retry tự động hữu hạn theo job policy; chưa thêm endpoint admin retry crawl riêng khi chưa đặc tả workflow.


## Auth


Cập nhật 06/11/2026 theo C13: chỉ dùng users và refresh_tokens cho auth; root token row thay bảng family riêng. Đã chốt: dùng access token + refresh token, không dùng session đăng nhập; vai trò visitor/user/admin; search/thumbnail public, detail/download cần đăng nhập; không ACL theo ảnh/collection và không feedback. Định dạng token, TTL và cookie transport dưới đây là đề xuất triển khai.

### 1. Phạm vi và vai trò

Tất cả mọi người tìm trên cùng kho đã công bố. Collection chỉ phân loại/filter, không chứa grants theo tài khoản. Sau login, quay lại ảnh đã chọn qua returnTo nội bộ đã kiểm tra.

| Chức năng | visitor | user | admin |
| --- | --- | --- | --- |
| Tìm/lọc, xem danh sách/thumbnail | Có | Có | Có |
| Detail/preview/download | Chuyển login | Có, toàn kho | Có, toàn kho |
| Me, đổi mật khẩu, logout | Không | Có | Có |
| Import/sửa/xóa ảnh, xem/retry jobs | Không | Không | Có |
| Quản trị tài khoản/role/status | Không | Không | Có |

Visitor là trạng thái chưa xác thực, không có users record. users.role chỉ nhận user/admin, mặc định user. Self-signup/SSO/recovery chờ Q12; admin cấp tài khoản là phương án đề xuất hiện tại.

### 2. Cặp token và nơi lưu

| Thành phần | Đề xuất | Sử dụng |
| --- | --- | --- |
| Access token | JWT ký, TTL 15 phút | Frontend giữ trong memory, gửi Authorization: Bearer trên API cần xác thực |
| Refresh token | Opaque random, entropy tối thiểu 256 bit; dùng một lần rồi rotate | Browser giữ cookie HttpOnly; chỉ auth endpoints đọc |
| Refresh family | Một chuỗi token cho mỗi lần login, hạn tuyệt đối đề xuất 7 ngày | Root row trong refresh_tokens giữ chủ sở hữu, auth_version, deadline và trạng thái thu hồi chung |
| Refresh token record | Hash token, user_id, family_id, parent_id, auth_version, expiry/consumed/revoked | Phát hiện reuse và retry/race; không chứa raw token |

Family là khái niệm nhóm token, không là bảng riêng: root có family_id=id, parent_id=null; token mới cùng family_id và parent_id trỏ token trước. Root đã consumed vẫn đại diện nhóm active nếu chưa revoked/hết hạn. Không có auth_sessions hoặc cookie session ID. Refresh registry phục vụ rotation/revocation, không thay access token làm credential cho detail/admin. Thiết kế có kiểm tra trạng thái thu hồi phía server để logout có hiệu lực ngay; không tuyên bố JWT hoàn toàn stateless.

JWT đề xuất RS256, pin thuật toán và public keys theo kid nội bộ. Validate chữ ký, typ access token, iss, aud, sub, iat/nbf/exp, jti, token_use=access, family_id và auth_version. Không lấy thuật toán/URL key tùy ý từ token; không đưa thông tin nhạy cảm vào payload. Tham khảo [RFC 8725](https://www.rfc-editor.org/rfc/rfc8725.html).

Protected request phải kiểm tra JWT rồi đọc user active/auth_version và root row của family_id đúng user, chưa revoked/hết hạn trong refresh_tokens; không kiểm tra consumed_at của root cho access JWT; role hiện hành quyết định admin. Nếu registry/DB lỗi thì fail closed, không âm thầm bỏ kiểm tra. Access token hết hạn nhưng refresh còn hợp lệ có thể gọi refresh; refresh token không được dùng như access token.

### 3. Transport cho web

Access token chỉ ở memory, không lưu vào URL/localStorage. Đề xuất refresh cookie `__Secure-refresh`, Secure, HttpOnly, SameSite=Strict, Path=/v1/auth, không Domain. Cookie này chứa refresh token, không phải session ID; server lưu hash. Browser login/refresh nhận access token trong JSON và refresh token qua Set-Cookie; không trả raw refresh token trong JSON của web API.

Auth responses Cache-Control: no-store. Cookie-auth endpoints login/refresh/logout yêu cầu Origin chính xác trong allowlist, Content-Type application/json và custom header `X-Auth-Request: 1`, từ chối origin thiếu/không hợp lệ cho browser contract này. CORS chỉ allowlist origin/header cụ thể với credentials, không wildcard; không chấp nhận form-urlencoded/text/plain cho các endpoints đó. Đây là lớp chống CSRF cho refresh cookie; không có GET /auth/csrf hoặc synchronizer token gắn session.

Protected APIs chỉ nhận access token từ Authorization, không nhận từ cookie/query string, kể cả khi browser còn refresh cookie. Client gửi credentials cho auth endpoints; các header/token không được log. Nếu có native app hoặc SSO sau này, thiết kế transport riêng, không tự thêm đường refresh từ body song song với cookie.

### 4. Login và refresh

Login: validate và rate limit → kiểm tra email/password/user active → transaction khóa user, tạo root refresh_tokens row với family_id=id, token_hash, deadline tuyệt đối và auth_version hiện tại → trả access token và refresh cookie sau commit. Mật khẩu hash Argon2id qua thư viện duy trì, không log/lưu thô; tham khảo [OWASP Password Storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html). Sai email/password hoặc disabled trả cùng INVALID_CREDENTIALS.

Refresh: đọc cookie/hash → transaction khóa user, root token rồi token được trình theo thứ tự cố định, không khóa lặp khi token chính là root → xác minh user active/auth_version, root đúng user/family chưa revoked/hết hạn và token được trình chưa consumed/revoked → đánh dấu consumed, thêm token row mới với parent_id và cùng family_id/user_id/auth_version/deadline, tạo access JWT cùng family → commit → Set-Cookie token mới. Token mới không kéo dài deadline tuyệt đối 7 ngày của family. Mỗi lần login tạo family mới; không dùng client-supplied family ID.

Token đã consumed được dùng lại: đặt revoked_at/revoke_reason trên root để thu hồi toàn family, commit rồi trả 401 TOKEN_REUSE_DETECTED và xóa cookie. Hai request refresh đồng thời chỉ có một rotation hợp lệ; request dùng lại token cũ có thể thu hồi cả chuỗi. Frontend cần single-flight refresh và phối hợp giữa tabs; không tự retry mù refresh sau timeout. Nếu response mất sau commit, phương án MVP là login lại, không có grace window nhận token cũ. Rotation/reuse lấy nguyên tắc tham khảo từ [RFC 9700 §4.14](https://www.rfc-editor.org/rfc/rfc9700.html#section-4.14); đây là login first-party, không tuyên bố triển khai đầy đủ OAuth server.

Khi API trả ACCESS_TOKEN_EXPIRED, frontend refresh một lần rồi retry request an toàn với Idempotency-Key nếu cần. 401 revoked/invalid/disabled không tạo vòng lặp refresh. Bootstrap sau reload gọi refresh để lấy access token; không có refresh cookie hợp lệ thì về visitor.

### 5. Logout, mật khẩu và role

Logout hiện tại nhận refresh cookie, tra row theo token_hash rồi thu hồi root tương ứng và xóa cookie; frontend xóa access token khỏi memory. Token đã consumed nhưng còn trong registry vẫn xác định được family để logout. Thiếu/không tồn tại refresh token trả 200 idempotent; nếu không thể ghi thu hồi do DB lỗi trả 503, không giả thành server đã revoke. Client vẫn có thể xóa memory và chặn UI local trong lúc retry logout.

Logout-all hoặc đổi mật khẩu tăng users.auth_version và thu hồi mọi root token row; đổi mật khẩu yêu cầu mật khẩu hiện tại. Admin đổi role/status cũng tăng auth_version và revoke mọi root token row trong cùng transaction. Vì protected request kiểm tra version/family, access token đã phát hành bị từ chối ngay ở request sau commit, không đợi đủ 15 phút.

Admin active cuối cùng không được khóa/hạ role; transaction phải chống race. Bootstrap admin riêng, không có default password. Logout/khóa tài khoản vẫn cho phép dùng search/thumbnail dưới vai trò visitor. Các URL media đã cấp trước logout vẫn tuân TTL riêng, không tự bị JWT revoke.

### 6. Snapshot tìm kiếm và media

`search_sessions` chỉ là snapshot phân trang 15 phút, không phải cơ chế login. Owner key là giá trị ngẫu nhiên tối thiểu 128 bit do client giữ trong memory và gửi `X-Search-Owner` khi tạo/đọc snapshot; server chỉ lưu hash, dùng để chống cursor bị dùng nhầm. Không dựa vào auth session hoặc cookie khách; không dùng key để cấp quyền ảnh. Thay access token qua refresh không làm đổi snapshot; login/logout bắt đầu snapshot mới. Client reload mất owner key thì tìm lại.

Search chỉ trả thumbnail, không có original/preview/download URL hoặc object_key. Detail/download cần JWT access hợp lệ và kiểm tra trạng thái catalog; API cấp URL media ký ngắn hạn hoặc stream qua proxy đã xác thực. Signed URL là bearer capability có thể chia sẻ tới hết TTL; Q05 quyết định có cần proxy kiểm tra access token mỗi lượt đọc. Thumbnail có thể được người xem lưu lại.

### 7. Kiểm thử khi triển khai

Login sai/disabled và rate limit; JWT sai signature/alg/kid/iss/aud/type/expiry; refresh token bị gửi như bearer; rotation một lần, reuse và hai-tab race; crash/response loss giữa commit/Set-Cookie; token family expiry; logout không thể refresh tiếp và access bị từ chối; logout-all/password/role/status đổi vô hiệu hóa token cũ; DB lỗi fail closed.

Kiểm tra cookie flags, auth Origin/custom header/CORS, refresh không lộ JSON/logs, access token không lưu bền; visitor search/thumbnail thành công nhưng detail/download 401; user không gọi được admin; admin quản trị ảnh/tài khoản; mọi user dùng cùng toàn kho; snapshot vẫn tách khỏi auth và không có feedback/grants schema.

Ràng buộc schema tối giản: unique token_hash và parent_id khác null; parent/root phải cùng user/family, token chỉ có một successor; mọi rotation/revoke khóa user trước nên không race giữa thêm token và logout. Giữ root và toàn bộ token history đến family deadline cộng access TTL/clock skew để phát hiện reuse và nhận diện logout bằng token cũ. Không ghi đè hash token hiện tại để thay cho lịch sử. Cleanup cả nhóm khi đủ điều kiện, không xóa root sớm. Chi tiết 9 bảng ở [mô hình dữ liệu](data-model.md).
