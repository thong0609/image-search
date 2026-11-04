# Hợp đồng API MVP

Trạng thái: đặc tả đề xuất v0.1, chưa phải API đã triển khai. Prefix `/v1`; JSON UTF-8; thời gian ISO 8601 UTC. Giới hạn cấu hình được nêu để review, không phải giá trị đã benchmark.

## 1. Quy ước chung

Backend nhận danh tính từ identity adapter đã xác thực; nguồn danh tính chờ Q05. Không tin principal_id hoặc role tự khai trong JSON. Mọi endpoint kiểm tra collection grants. UUID được biểu diễn bằng chuỗi; timestamp và ID trong ví dụ là minh họa.

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
| 401 | UNAUTHENTICATED | Xác thực lại |
| 403 | FORBIDDEN_SCOPE | Kiểm tra quyền/filter collection |
| 404 | RESOURCE_NOT_FOUND | Không tiết lộ image/import ngoài quyền bằng endpoint lấy theo ID |
| 409 | IDEMPOTENCY_CONFLICT, STALE_VERSION, JOB_NOT_RETRYABLE | Đọc lại trạng thái trước khi thao tác |
| 410 | SEARCH_EXPIRED | Tìm lại từ trang đầu |
| 422 | INVALID_QUERY, INVALID_FILTER, INVALID_MANIFEST, TOKEN_LIMIT_EXCEEDED | Hiển thị lỗi theo field |
| 429 | RATE_LIMITED | Chờ theo Retry-After; retry có giới hạn |
| 503 | SEARCH_UNAVAILABLE, DEPENDENCY_UNAVAILABLE | Retry có giới hạn, giữ query |
| 504 | SEARCH_TIMEOUT | Thông báo timeout, cho tìm lại |

Lỗi không đưa stack trace, đường dẫn nội bộ, token, credentials hoặc signed URL vào details. Unexpected error trả 500 INTERNAL_ERROR với request_id.

## 2. POST /v1/search

Người có quyền viewer trên ít nhất một collection. Tạo phiên tìm kiếm mới.

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
- filters: tùy chọn; collection_ids nếu có phải là danh sách không rỗng, không trùng và đều được phép; không có thì dùng phạm vi hiện tại của người dùng. Không có collection được phép → 403.
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

Title có thể null; không suy diễn caption. Kết quả rỗng hợp lệ: items=[], next_cursor=null và HTTP 200. Không trả total_count vì đây là danh sách xếp hạng hữu hạn, không phải đếm toàn bộ ảnh phù hợp. Thông số model/ranking được lưu server-side để truy vết.

## 3. Phân trang: POST /v1/search với cursor

Request tiếp theo chỉ chứa `cursor` và tùy chọn `limit`; không được đồng thời chứa query hoặc filters. Cursor được ký hoặc là token ngẫu nhiên opaque, ràng buộc search_id, principal và vị trí; TTL đề xuất 15 phút từ lúc tạo phiên. Client coi cursor là opaque, không tự giải mã/sửa.

Server lưu tối đa 200 ID/version đã xếp hạng mỗi phiên làm cửa sổ kết quả ban đầu. Mỗi trang kiểm tra lại quyền và trạng thái, bỏ item bị xóa, đổi version hoặc mất quyền, tiến tiếp trong snapshot để lấp trang. Không đưa ảnh mới vào snapshot. next_cursor=null khi hết cửa sổ, kể cả kho vẫn còn ảnh; UI chỉ nói đã hết kết quả của lượt tìm này.

Cùng cursor và limit trả cùng vị trí logic, nhưng response có thể ít item hơn khi quyền/dữ liệu thay đổi. URL được cấp mới theo request. Trang nối tiếp không lặp ID trong một chuỗi cursor. Cursor của principal khác hoặc bị sửa trả 400 INVALID_CURSOR; phiên hết hạn trả 410. TTL và cửa sổ được benchmark để cân bằng chi phí lưu session.

## 4. GET /v1/images/{image_id}

Trả 200 với image metadata hiện tại: id, content_version, title, tags nếu có, width, height, mime_type, source, license nếu có, thumbnail_url, original_url, url_expires_at và request_id. Trả 404 nếu ảnh chưa sẵn sàng, đã xóa hoặc ngoài quyền. Không nhận content_version tùy ý để truy cập bản lịch sử trong MVP.

URL ký ngắn hạn, đề xuất tối đa 5 phút và giới hạn TTL theo tài nguyên. Trình duyệt có URL đã cấp có thể truy cập đến hết TTL; nếu nghiệp vụ đòi thu hồi tức thì phải dùng proxy kiểm tra quyền mỗi lần tải (Q05). API cấp mới luôn kiểm tra quyền.

## 5. POST /v1/feedback

Body: search_id UUID, image_id UUID, relevance enum relevant/partially_relevant/irrelevant. Chỉ nhận cho item đã hiển thị trong search session của principal, đang còn quyền và trong thời hạn session. Nếu không tìm thấy quan hệ hợp lệ trả 404; hết hạn trả 410.

Upsert theo (search_id, principal_id, image_id), 200 với request_id và saved=true. Retry không tạo bản ghi trùng; đổi lựa chọn cập nhật nhãn cũ. Không sửa thứ tự của phiên tìm kiếm hiện tại.

## 6. POST /v1/admin/imports

Cần editor trên collection; bắt buộc Idempotency-Key. Body gồm collection_id, source_id, manifest_key. manifest_key là object trong vùng nhập đã đăng ký; không chấp nhận URL tùy ý hoặc đường dẫn máy chủ từ client. source_id phải thuộc collection_id.

Manifest JSONL, mỗi dòng gồm source_item_key ổn định, input_revision integer tăng đơn điệu theo item, object_key thuộc nguồn được phép và metadata tùy chọn. Chi tiết validation ở [ingestion-design.md](ingestion-design.md). Revision nhỏ hơn bản đã nhận là superseded; cùng revision khác nội dung là conflict.

202 trả request_id, import_id, status=queued và status_url. Tạo import không đồng nghĩa ảnh đã searchable. Lỗi cấu trúc request trả đồng bộ; lỗi từng dòng manifest sau khi chạy parser được ghi trong kết quả import. Giới hạn manifest đề xuất 10.000 dòng và 10 MiB mỗi import; một triệu ảnh chia nhiều import có manifest/checkpoint riêng.

## 7. GET /v1/admin/imports/{import_id}

200 gồm request_id, import_id, status, total_items nullable khi đang parse, counts theo từng trạng thái, created_at, updated_at. Status: queued/parsing/running/completed/completed_with_errors/failed.

GET `/v1/admin/imports/{import_id}/items?status=failed&limit=100&cursor=...` trả lỗi từng item theo ID tăng dần, cursor opaque; limit 1–100. Quản trị phải có quyền collection tương ứng; ngoài quyền trả 404. Error detail được làm sạch, không chứa dữ liệu bí mật.

## 8. POST /v1/admin/imports/{import_id}/retry

Body item_ids: 1–100 UUID không trùng, thuộc import và đang failed do nguyên nhân có thể thử lại sau khi quản trị sửa điều kiện. Tất cả item được kiểm tra trong một transaction; item không hợp lệ trả 409 và không enqueue một phần. Retry không hồi sinh ảnh tombstone hoặc version đã superseded. Thành công 202 trả queued_item_count và request_id; gọi lại khi job pending/running trả 409 JOB_NOT_RETRYABLE.

Sửa ảnh hoặc metadata thực hiện qua import revision mới; không thêm endpoint update riêng khi chưa có nhu cầu chỉnh từng ảnh trên UI.

## 9. DELETE /v1/admin/images/{image_id}

Cần editor; ngoài phạm vi trả 404. Header If-Match bắt buộc chứa metadata_revision do admin đọc từ import item/catalog quản trị; thiếu trả 428 PRECONDITION_REQUIRED, lệch trả 409 STALE_VERSION. Response 202 có request_id, image_id, lifecycle=deleted, purge_status=pending và metadata_revision mới.

Tombstone có hiệu lực với response mới sau commit; response hoặc URL đã cấp trước đó có thể còn dùng tới TTL. Lặp delete với revision hiện tại là no-op 202; không tạo lại purge job. Purge vật lý theo retention và backlog, trạng thái được xem ở GET `/v1/admin/images/{image_id}`.

## 10. GET /v1/admin/images/{image_id}

Cần editor trên collection. Trả trạng thái cả ảnh active và deleted: image_id, collection_id, lifecycle, current_version, desired_version, metadata_revision, processing_status, purge_status, updated_at, request_id; header ETag chứa metadata_revision dạng quoted string. Không có quyền trả 404.

## 11. Health và versioning

`GET /health/live`: kiểm tra process còn hoạt động, không chạm dependency; `GET /health/ready`: 200 khi instance phục vụ được, 503 nếu model/index/database chưa sẵn sàng. Health được giới hạn ở hạ tầng vận hành, không công khai topology hay credential.

Thêm field response tùy chọn được coi là tương thích; đổi nghĩa, xóa field hoặc làm request cũ mất hợp lệ cần version mới. Khi bắt đầu code, chuyển hợp đồng này thành OpenAPI và kiểm tra ví dụ bằng schema; hiện chưa có endpoint nào chạy.
