# Thiết kế triển khai và vận hành

Trạng thái: kế hoạch vận hành, chưa phải hạ tầng đã triển khai. Lệnh cụ thể sẽ được bổ sung sau khi chọn toolchain và môi trường; không có lệnh triển khai nào được giả định đang hoạt động.

## 1. Môi trường và cấu hình

Development dùng ảnh mẫu được phép, staging dùng dữ liệu đại diện theo quyền, production chứa kho riêng thật. Tách storage prefixes/buckets, database, credentials và role assignments giữa các môi trường. Không sao chép ảnh riêng sang máy phát triển hoặc log mà chưa có quy trình dữ liệu phù hợp.

Cấu hình đề xuất theo nhóm:

| Nhóm | Nội dung |
| --- | --- |
| Catalog | Database URL, connection pool, transaction timeout |
| Qdrant | Endpoint, API-key reference, collection generation, request timeout, read/write consistency, payload indexes |
| Storage | Endpoint, bucket, region, credential reference, URL TTL |
| Model | Model/processor revision, artifact checksum, device, batch size |
| Graph | Adapter/endpoint và secret reference, generation/revision, schema/linker, predicates, traversal budgets, target lag và graph readiness |
| Reranker | VLM model/processor/prompt revision, rendition size, output schema, device/hosting, batch/concurrency, rerank window, timeout và failure policy |
| Search | Profile, vector/graph generations, fusion config, deadline, concurrency, snapshot TTL/window, strict/fallback policy |
| Worker | Lease/heartbeat, attempts, backoff, batch/concurrency |
| Access | Users/roles, JWT issuer/audience/signing-key references, access/refresh TTL, refresh cookie Origin/header policy, search owner key; không collection grants |
| Observability | Log level, metrics/tracing endpoint, retention policy |

Khi triển khai, tạo `.env.example` chỉ có placeholder, chọn phiên bản dependency và commit lockfile. Secrets lấy từ secret manager hoặc cơ chế môi trường đã chọn, không đặt trong Git hoặc connector JSON.

## 2. Topology ban đầu

API và worker có thể cùng codebase nhưng khác process/tài nguyên. DB quan hệ, Qdrant, graph storage adapter và object storage là các vai trò dữ liệu bền vững; graph engine chưa chốt, không nhất thiết là một dịch vụ riêng; PostgreSQL là đề xuất cho DB quan hệ. Qdrant chứa vector và payload metadata; SQL chứa users/roles/refresh token registry, catalog/lifecycle, jobs/outbox và published pointers. Không yêu cầu GPU cho mọi thành phần; benchmark quyết định CPU/GPU cho batch encoder, text inference và VLM rerank; giới hạn riêng online VLM để import không chiếm hết VRAM. Số replica tùy Q06; một instance chỉ phù hợp khi chấp nhận downtime.

Không đưa database/vector endpoint ra Internet công khai. API, worker và storage dùng danh tính có quyền tối thiểu; worker không cần quyền quản trị người dùng. Search/thumbnail public; detail/download kiểm tra login trước cấp URL. Ảnh gốc qua signed URL ngắn hạn hoặc media proxy theo Q05; không công khai bucket ảnh gốc.

Thumbnail và ảnh gốc dùng storage policy/prefix tách biệt; public thumbnail route không được chuyển thành original route bằng cách sửa đường dẫn. Response login/me/detail/download đặt Cache-Control: no-store hoặc private phù hợp và không dùng chung cache chứa URL được cấp sau login; auth responses luôn no-store.

## 3. Quan sát và cảnh báo

| Nhóm | Metrics tối thiểu |
| --- | --- |
| Search | request count, end-to-end p50/p95/p99, error/timeout/429 rate, encode/keyword/graph/fusion/hydration/image-fetch/VLM/final-check latency, empty-result rate |
| Graph | Entity linking coverage/errors, visited nodes/edges, traversal truncation/budget failures, projection/shared-fact lag, stale rejection, graph revision retries và hard-constraint failures |
| Reranker | Queue age, batch size, images/query, image fetch bytes, inference latency, VRAM, output validation errors, fallback rate và cost/query |
| Ingestion | queued/running/failed, oldest job age, end-to-end throughput, retry/lease expiry, import progress |
| Database/storage | Pool saturation, query latency, disk free, WAL growth, I/O, storage error rate |
| Qdrant/sync | Search/upsert/delete latency và lỗi, payload index size, outbox age, applied-to-published lag, candidate rejection, pending purge |
| Model | Load time, inference failures, RAM/VRAM, batch duration, incompatible vector rejection |
| Integrity | Ready missing vector/object, stale generation lag, tombstone vector count, purge backlog |

Metric labels không chứa query, image_id, principal_id hoặc request_id để tránh cardinality cao. IDs đặt trong structured logs/traces; token, URL ký và ảnh không được log. Raw query logging mặc định tắt cho tới khi Q09 chốt; session có thể lưu query hash để ràng buộc cursor.

Cảnh báo thử cho pilot: p95 vượt mục tiêu trong 10 phút với đủ request; lỗi 5xx > 1% trong 5 phút với tối thiểu 100 request; disk free < 20%; backlog vượt khả năng xử lý trong cửa sổ cập nhật đã chốt. Đây là ngưỡng khởi đầu để tune, chưa là SLA. Tách cảnh báo tính toàn vẹn/quyền khỏi cảnh báo hiệu năng.

Auth metrics bổ sung: login success/failure/rate-limit, expired/revoked access token use, refresh rotations/reuse, admin authorization failures. Không log password/Authorization/refresh cookie. Logout/role/password changes phải được thử nghiệm thu hồi token; auth endpoints không cache. Role và media policy theo [auth-design.md](auth-design.md).

JWT signing keys được quản lý tách khỏi source/config public; pin thuật toán/kid, có kế hoạch key rotation. Public verification keys cũ chỉ giữ theo TTL hợp lệ, không chấp nhận key bị compromise. Backup/restore không được làm sống lại family/token đã revoked hoặc consumed; đối soát revocation ledger trước phục vụ. Tham số và hành vi rotation/reuse theo auth-design; refresh lỗi sau commit phải có hướng login lại.

## 4. SLO và phục hồi

SLO độ trễ đề xuất p95 warm < 2 giây ở tải được xác nhận. Availability, error budget, RPO và RTO chưa chốt (Q06); không tuyên bố production sẵn sàng khi chưa có mục tiêu và kiểm tra phục hồi.

Backup bao phủ DB quan hệ (users/roles/refresh token registry, tombstones, registry, outbox, pointers), Qdrant snapshot (vector/payload), graph snapshot/artifacts (entity/relations/shared-fact revisions) và object storage (ảnh, metadata snapshots, artifacts để rebuild). Đối chiếu bằng manifest/version/hash; không giả định các hệ chụp cùng thời điểm. Đối soát graph pointers/revision với catalog; restore staging không được đọc shared fact chưa publish. Rebuild Qdrant phải có đủ snapshot metadata và model/artifact đã pin, không chỉ ảnh gốc.

Restore drill: phục hồi vào môi trường cách ly → xác nhận roles/tombstones và revoke refresh families không còn hợp lệ và kiểm tra auth_version → xác minh object references/vector/profile → chạy truy vấn mẫu → đo thời gian và mất dữ liệu so với RPO/RTO → chỉ chuyển traffic sau review kết quả. Nếu phục hồi làm sống lại dữ liệu đã xóa, replay deletion ledger/tombstones mới hơn trước khi cho truy cập.

## 5. Runbook reindex hoặc đổi model

1. Xác minh capacity đủ hai generation và model mới đã qua quality gate development/test.
2. Tạo profile bất biến và generation building, ghi source watermark.
3. Backfill theo batch, đồng thời chuyển thay đổi mới vào generation mới qua job/change log bền vững. Xóa phải đi vào cả hai generation.
4. Chờ catch-up từng Qdrant/graph target; đối soát số lượng hợp lệ, version, missing vectors/graph projections, shared-fact revisions, published pointers và tài khoản/role. Dừng cutover nếu chưa bắt kịp.
5. Chạy benchmark, query mẫu và kiểm tra no-answer; lưu bằng chứng, chuyển generation sang validating.
6. Chuyển active config nguyên tử gồm search profile, vector/graph generations và graph revision; request mới dùng generation mới, session cũ tiếp tục dùng snapshot nếu image version vẫn hợp lệ; session có hard graph constraint hết hiệu lực khi graph generation/revision đổi.
7. Theo dõi latency/error/quality trong cửa sổ đã chọn. Giữ generation cũ cập nhật trong thời gian rollback nếu muốn rollback không mất ảnh mới.
8. Khi hết cửa sổ, retire generation cũ rồi dọn theo retention. Nếu generation cũ chưa catch-up thì không rollback trực tiếp; catch-up hoặc thông báo giới hạn trước khi đổi pointer.

## 6. Runbook sự cố

| Tình huống | Hành động và điều kiện phục hồi |
| --- | --- |
| Model không nạp được | Readiness fail; giữ instance tốt nếu có; xác minh artifact/revision. Không đổi sang model khác ngầm |
| DB quá tải | Giảm/dừng claim batch, hạn chế online concurrency, xem pool/query plan; khôi phục theo tải đo |
| Storage lỗi | Retry hữu hạn; import giữ checkpoint; API trả lỗi khi không thể cấp media theo hợp đồng |
| Qdrant lỗi hoặc thiếu point đã công bố | Search/detail trả lỗi dependency rõ; giữ outbox để replay; kiểm tra collection/profile và restore/reconcile, không giả định SQL có metadata thay thế |
| Graph lỗi/stale hoặc vượt traversal budget | Strict fail; chỉ fallback nhánh boost khi profile cho phép và báo degraded; hard constraint luôn fail. Replay/reconcile đúng generation/revision trước phục hồi |
| VLM quá tải/timeout/output sai | Giới hạn admission/batch/window, kiểm tra VRAM và revision; strict fail hoặc fusion shortlist fallback khai báo trước, bỏ toàn bộ partial VLM output |
| Graph revision đổi khi phân trang hard constraints | Trả SEARCH_EXPIRED; client tìm lại, không dùng quan hệ cũ |
| Worker crash/lease hết | Thu hồi sau expiry; kiểm tra fencing; không reset toàn import |
| Ảnh xóa còn xuất hiện | Kiểm tra tombstone và final authorization; vô hiệu hóa nhánh/cache sai; đối soát mọi generation |
| Generation sai chất lượng | Rollback chỉ khi generation cũ còn tương thích và đã catch-up |
| Snapshot store quá lớn | Cleanup TTL, giới hạn phiên theo principal, điều chỉnh window; không xóa tùy tiện phiên còn hạn nếu không có lỗi rõ |

Mỗi sự cố ghi timeline, phạm vi ảnh hưởng, request/config IDs an toàn, biện pháp và bằng chứng phục hồi. Hướng dẫn vận hành không tự cấp quyền publish/deploy thực tế.

## 7. Retention và media

Đề xuất pilot: search snapshot 15 phút, signed URL tối đa 5 phút, idempotency record tối thiểu 24 giờ. Raw query log mặc định tắt; nếu được chốt có thể lưu 7 ngày ban đầu. Refresh token registry, audit, tombstones, backup và purge grace period cần Q09.

Tombstone có hiệu lực ngay cho response sau commit; signed URL đã cấp không đảm bảo thu hồi tức thì. Nếu cần thu hồi tức thì, media proxy phải kiểm tra login và lifecycle hiện tại mỗi request và chính sách cache tương ứng. Xóa ảnh trong hệ live cần phân biệt với xóa khỏi backup theo lịch.

## 8. Capacity và chi phí

Theo [scale-plan.md](scale-plan.md), tách dung lượng vector, index, ảnh gốc, thumbnail, backup và generation song song. Đo ảnh trung bình và phân bố p95 dung lượng trước dự toán. Tính cả egress, annotation, inference, managed service và công vận hành; chưa gán giá cloud hoặc cấu hình máy production khi Q03/Q04 còn thiếu.

Cập nhật C12: tính thêm graph nodes/edges/aliases/indexes/artifacts, backfill hai graph generations, VLM weights/KV/runtime memory, ảnh rendition, GPU concurrency, image egress và cost mỗi lượt rerank. Thay riêng VLM/prompt cần profile/quality gate và rollback cấu hình, không bắt buộc rebuild vector. Tổng deadline thử dưới 5 giây và p95 warm < 2 giây chưa được chứng minh với graph+VLM; chốt Q15 theo benchmark end-to-end.
