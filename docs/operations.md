# Thiết kế triển khai và vận hành

Trạng thái: kế hoạch vận hành, chưa phải hạ tầng đã triển khai. Lệnh cụ thể sẽ được bổ sung sau khi chọn toolchain và môi trường; không có lệnh triển khai nào được giả định đang hoạt động.

## 1. Môi trường và cấu hình

Development dùng ảnh mẫu được phép, staging dùng dữ liệu đại diện theo quyền, production chứa kho riêng thật. Tách storage prefixes/buckets, database, credentials và grants giữa các môi trường. Không sao chép ảnh riêng sang máy phát triển hoặc log mà chưa có quy trình dữ liệu phù hợp.

Cấu hình đề xuất theo nhóm:

| Nhóm | Nội dung |
| --- | --- |
| Catalog | Database URL, connection pool, transaction timeout |
| Storage | Endpoint, bucket, region, credential reference, URL TTL |
| Model | Model/processor revision, artifact checksum, device, batch size |
| Search | Generation, ranking config, deadline, concurrency, snapshot TTL/window |
| Worker | Lease/heartbeat, attempts, backoff, batch/concurrency |
| Access | Identity provider config, collection grants, session/cursor signing key |
| Observability | Log level, metrics/tracing endpoint, retention policy |

Khi triển khai, tạo `.env.example` chỉ có placeholder, chọn phiên bản dependency và commit lockfile. Secrets lấy từ secret manager hoặc cơ chế môi trường đã chọn, không đặt trong Git hoặc connector JSON.

## 2. Topology ban đầu

API và worker có thể cùng codebase nhưng khác process/tài nguyên. PostgreSQL/pgvector và object storage là dependency bền vững. Không yêu cầu GPU cho mọi thành phần; benchmark quyết định GPU cho batch và text inference. Số replica tùy Q06; một instance chỉ phù hợp khi chấp nhận downtime.

Không đưa database/vector endpoint ra Internet công khai. API, worker và storage dùng danh tính có quyền tối thiểu; worker không cần quyền quản trị người dùng. Tải ảnh qua signed URL ngắn hạn hoặc media proxy theo quyết định Q05.

## 3. Quan sát và cảnh báo

| Nhóm | Metrics tối thiểu |
| --- | --- |
| Search | request count, p50/p95/p99, error/timeout/429 rate, encode/retrieve/catalog latency, empty-result rate |
| Ingestion | queued/running/failed, oldest job age, end-to-end throughput, retry/lease expiry, import progress |
| Database/storage | Pool saturation, query latency, disk free, WAL growth, I/O, storage error rate |
| Model | Load time, inference failures, RAM/VRAM, batch duration, incompatible vector rejection |
| Integrity | Ready missing vector/object, stale generation lag, tombstone vector count, purge backlog |

Metric labels không chứa query, image_id, principal_id hoặc request_id để tránh cardinality cao. IDs đặt trong structured logs/traces; token, URL ký và ảnh không được log. Raw query logging mặc định tắt cho tới khi Q09 chốt; session có thể lưu query hash để ràng buộc cursor.

Cảnh báo thử cho pilot: p95 vượt mục tiêu trong 10 phút với đủ request; lỗi 5xx > 1% trong 5 phút với tối thiểu 100 request; disk free < 20%; backlog vượt khả năng xử lý trong cửa sổ cập nhật đã chốt. Đây là ngưỡng khởi đầu để tune, chưa là SLA. Tách cảnh báo tính toàn vẹn/quyền khỏi cảnh báo hiệu năng.

## 4. SLO và phục hồi

SLO độ trễ đề xuất p95 warm < 2 giây ở tải được xác nhận. Availability, error budget, RPO và RTO chưa chốt (Q06); không tuyên bố production sẵn sàng khi chưa có mục tiêu và kiểm tra phục hồi.

Backup phải bao phủ metadata, grants, retrieval registry và dữ liệu vector hoặc khả năng rebuild đã đo. Snapshot database và object storage phải được đối chiếu bằng manifest/version, không giả định chụp ở hai thời điểm khác nhau vẫn nhất quán.

Restore drill: phục hồi vào môi trường cách ly → xác nhận grants/tombstones → xác minh object references/vector/profile → chạy truy vấn mẫu → đo thời gian và mất dữ liệu so với RPO/RTO → chỉ chuyển traffic sau review kết quả. Nếu phục hồi làm sống lại dữ liệu đã xóa, replay deletion ledger/tombstones mới hơn trước khi cho truy cập.

## 5. Runbook reindex hoặc đổi model

1. Xác minh capacity đủ hai generation và model mới đã qua quality gate development/test.
2. Tạo profile bất biến và generation building, ghi source watermark.
3. Backfill theo batch, đồng thời chuyển thay đổi mới vào generation mới qua job/change log bền vững. Xóa phải đi vào cả hai generation.
4. Chờ catch-up; đối soát số lượng hợp lệ, version, missing vectors và quyền. Dừng cutover nếu chưa bắt kịp.
5. Chạy benchmark, query mẫu và kiểm tra no-answer; lưu bằng chứng, chuyển generation sang validating.
6. Chuyển active pointer nguyên tử; request mới dùng generation mới, session cũ tiếp tục dùng snapshot nếu image version vẫn hợp lệ.
7. Theo dõi latency/error/quality trong cửa sổ đã chọn. Giữ generation cũ cập nhật trong thời gian rollback nếu muốn rollback không mất ảnh mới.
8. Khi hết cửa sổ, retire generation cũ rồi dọn theo retention. Nếu generation cũ chưa catch-up thì không rollback trực tiếp; catch-up hoặc thông báo giới hạn trước khi đổi pointer.

## 6. Runbook sự cố

| Tình huống | Hành động và điều kiện phục hồi |
| --- | --- |
| Model không nạp được | Readiness fail; giữ instance tốt nếu có; xác minh artifact/revision. Không đổi sang model khác ngầm |
| DB quá tải | Giảm/dừng claim batch, hạn chế online concurrency, xem pool/query plan; khôi phục theo tải đo |
| Storage lỗi | Retry hữu hạn; import giữ checkpoint; API trả lỗi khi không thể cấp media theo hợp đồng |
| Worker crash/lease hết | Thu hồi sau expiry; kiểm tra fencing; không reset toàn import |
| Ảnh xóa còn xuất hiện | Kiểm tra tombstone và final authorization; vô hiệu hóa nhánh/cache sai; đối soát mọi generation |
| Generation sai chất lượng | Rollback chỉ khi generation cũ còn tương thích và đã catch-up |
| Snapshot store quá lớn | Cleanup TTL, giới hạn phiên theo principal, điều chỉnh window; không xóa tùy tiện phiên còn hạn nếu không có lỗi rõ |

Mỗi sự cố ghi timeline, phạm vi ảnh hưởng, request/config IDs an toàn, biện pháp và bằng chứng phục hồi. Hướng dẫn vận hành không tự cấp quyền publish/deploy thực tế.

## 7. Retention và media

Đề xuất pilot: search snapshot 15 phút, signed URL tối đa 5 phút, idempotency record tối thiểu 24 giờ. Raw query log mặc định tắt; nếu được chốt có thể lưu 7 ngày ban đầu. Feedback, audit, tombstones, backup và purge grace period cần Q09.

Tombstone có hiệu lực ngay cho response sau commit; signed URL đã cấp không đảm bảo thu hồi tức thì. Nếu cần thu hồi tức thì, media proxy phải kiểm tra quyền hiện tại mỗi request và chính sách cache tương ứng. Xóa ảnh trong hệ live cần phân biệt với xóa khỏi backup theo lịch.

## 8. Capacity và chi phí

Theo [scale-plan.md](scale-plan.md), tách dung lượng vector, index, ảnh gốc, thumbnail, backup và generation song song. Đo ảnh trung bình và phân bố p95 dung lượng trước dự toán. Tính cả egress, annotation, inference, managed service và công vận hành; chưa gán giá cloud hoặc cấu hình máy production khi Q03/Q04 còn thiếu.
