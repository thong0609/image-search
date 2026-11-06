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
| Search | Active row search_configs, vector/graph generations, fusion config, deadline, concurrency, snapshot TTL/window, strict/fallback, maintenance gates và checkpoint |
| Worker | Lease/heartbeat, attempts, backoff, batch/concurrency |
| Access | Users/roles, JWT issuer/audience/signing-key references, access/refresh TTL, refresh cookie Origin/header policy, search owner key; không collection grants |
| Observability | Log level, metrics/tracing endpoint, retention policy |

Khi triển khai, tạo `.env.example` chỉ có placeholder, chọn phiên bản dependency và commit lockfile. Secrets lấy từ secret manager hoặc cơ chế môi trường đã chọn, không đặt trong Git hoặc connector JSON.

## 2. Topology ban đầu

API và worker có thể cùng codebase nhưng khác process/tài nguyên. DB quan hệ, Qdrant, graph storage adapter và object storage là các vai trò dữ liệu bền vững; graph engine chưa chốt, không nhất thiết là một dịch vụ riêng; PostgreSQL đã được chọn cho DB quan hệ. Qdrant chứa vector và payload metadata; SQL gồm 9 bảng: users/refresh_tokens, collections/images/image_versions, typed jobs kiêm outbox, search_configs, search_sessions và audit_events. Projection refs/state ở image_versions.index_state; root refresh token row giữ trạng thái family. Không yêu cầu GPU cho mọi thành phần; benchmark quyết định CPU/GPU cho batch encoder, text inference và VLM rerank; giới hạn riêng online VLM để import không chiếm hết VRAM. Số replica tùy Q06; một instance chỉ phù hợp khi chấp nhận downtime.

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

JWT signing keys được quản lý tách khỏi source/config public; pin thuật toán/kid, có kế hoạch key rotation. Public verification keys cũ chỉ giữ theo TTL hợp lệ, không chấp nhận key bị compromise. Backup/restore không được làm sống lại root/token đã revoked hoặc consumed; đối soát revocation ledger trước phục vụ. Tham số và hành vi rotation/reuse theo auth-design; refresh lỗi sau commit phải có hướng login lại.

## 4. SLO và phục hồi

SLO độ trễ đề xuất p95 warm < 2 giây ở tải được xác nhận. Availability, error budget, RPO và RTO chưa chốt (Q06); không tuyên bố production sẵn sàng khi chưa có mục tiêu và kiểm tra phục hồi.

Backup bao phủ DB quan hệ (9 bảng gồm root/token history, tombstones, version index_state, jobs, active config/manifest và audit), Qdrant snapshot (vector/payload), graph snapshot/artifacts (entity/relations/shared-fact revisions) và object storage (ảnh, metadata snapshots, artifacts để rebuild). Đối chiếu bằng manifest/version/hash; không giả định các hệ chụp cùng thời điểm. Đối soát graph pointers/revision với catalog; restore staging không được đọc shared fact chưa publish. Rebuild Qdrant phải có đủ snapshot metadata và model/artifact đã pin, không chỉ ảnh gốc.

Restore drill: phục hồi vào môi trường cách ly → xác nhận roles/tombstones và revoke root refresh token rows không còn hợp lệ và kiểm tra auth_version → xác minh object references/vector/profile → chạy truy vấn mẫu → đo thời gian và mất dữ liệu so với RPO/RTO → chỉ chuyển traffic sau review kết quả. Nếu phục hồi làm sống lại dữ liệu đã xóa, replay deletion ledger/tombstones mới hơn trước khi cho truy cập.

## 5. Runbook maintenance, reindex và rollback

Schema 9 bảng (C13) dùng một search_configs active và tối đa một bản build. Không có dual-write/catch-up nhiều generation hoặc rollback online tự động. Jobs giữ checkpoint, index_state trong image_versions giữ refs/hashes riêng mỗi generation.

1. Kiểm tra capacity bản cũ/mới, model/schema mới qua quality gate, backup và thời lượng maintenance dự kiến. Tạo row search_configs building; giữ định nghĩa cấu hình bất biến và runtime maintenance state riêng.
2. Trong transaction điều phối, khóa active config và bật maintenance.writes_blocked có owner/revision/checkpoint bền vững. API và worker phải kiểm tra gate dưới cùng cơ chế khóa trước nhận/claim ghi catalog, import, metadata, delete hoặc shared facts. Trả 503 MAINTENANCE_MODE với Retry-After cho thao tác mới bị chặn; auth/account vẫn hoạt động nếu dependency sẵn sàng.
3. Drain toàn bộ writer/jobs đang chạy trước barrier, gồm request đã nhận và external writes chưa rõ kết quả. Drain dùng tập root jobs/request đã nhận trước barrier được ghi bền bằng manifest/checkpoint maintenance; cho phép claim tiếp các bước con của đúng tập này để hoàn tất theo lease, không nhận root mới. Không suy ra tập drain chỉ bằng max(id)/timestamp. Cho phép pipeline trong tập drain hoàn tất theo lease; không coi queue rỗng là đã drain nếu còn writer/lease. Kiểm chứng mọi sync/publish/purge/fact jobs trước barrier đã xử lý hoặc được hủy/dọn có kiểm soát. Nếu chưa drain được thì không build/cutover.
4. Dựng Qdrant/graph indices trên catalog và facts đứng yên, lưu immutable artifacts và index_state refs/hashes. Rebuild jobs có checkpoint/dedupe; không mở lại ghi chỉ vì process maintenance restart. Search có thể tiếp tục trên config cũ nếu đủ tài nguyên; có thể chủ động tạm dừng search khi tài nguyên không đủ.
5. Đối soát toàn bộ active images/current_version, hai target ready, point/artifact hashes, shared fact manifest và tombstones. Chạy benchmark/query mẫu/no-answer; thiếu hoặc lệch dữ liệu thì không chuyển active.
6. Bật maintenance.search_blocked, chặn search mới và drain search đang chạy trước activation. Khóa cấu hình điều phối, kiểm tra lại barrier/manifest, chuyển old active → retired và new → active trong cùng transaction; unique active được giữ. Mang write/search gate sang row mới trước khi nhả khóa. API/worker dùng active row làm nguồn duy nhất, không cache gate/pointer làm mất bảo đảm sau commit. Mọi search_sessions config cũ hết hiệu lực.
7. Smoke test bản mới trong maintenance. Nếu cần quay lại trước khi mở ghi và catalog/facts chưa đổi, có thể activate bản cũ sau xác minh tương thích; vẫn vô hiệu hóa snapshots. Sau đó mở gate và theo dõi metrics. Ghi audit cho từng chuyển trạng thái.
8. Giữ index/config/artifacts cũ theo retention và tham chiếu. Sau khi đã mở ghi, index cũ có thể stale: muốn rollback phải vào maintenance, drain ghi và rebuild/đối soát bản đích trên catalog/facts hiện tại trước activation. Không đổi pointer trực tiếp tới bản stale hoặc làm mất tombstones/ảnh mới.

Nếu build thất bại trước cutover, có thể hủy bản build và mở lại ghi trên config cũ sau xác minh không có writer lạc/point staging được công bố. Sau cutover thất bại, giữ gate và phục hồi theo checkpoint. Lease maintenance hết hạn không tự mở ghi: operator/worker phục hồi phải kiểm tra barrier và cấu hình active. Runtime gate và config switch không phải distributed transaction với Qdrant/graph/object storage.

Đổi riêng VLM/prompt không rebuild vector nếu tương thích. Tạo search_configs mới, chặn/drain search và writer công bố graph trong khoảng activation ngắn, lấy graph_manifest/revision hiện hành dưới khóa rồi switch active; không lấy manifest cũ của config retired. Vô hiệu hóa snapshots cũ và mở lại gates sau kiểm tra.

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
| Maintenance bị gián đoạn | Giữ gate bền, kiểm tra active config và checkpoint; khôi phục barrier/drain hoặc hủy build an toàn, không tự mở ghi khi lease hết |
| Worker crash/lease hết | Thu hồi sau expiry; kiểm tra fencing; không reset toàn import |
| Ảnh xóa còn xuất hiện | Kiểm tra tombstone và final authorization; vô hiệu hóa nhánh/cache sai; đối soát mọi generation |
| Generation sai chất lượng | Vào maintenance; rollback trực tiếp chỉ khi catalog/facts chưa đổi và index cũ còn khớp, nếu không rebuild bản đích trước switch |
| Snapshot store quá lớn | Cleanup TTL, giới hạn phiên theo principal, điều chỉnh window; không xóa tùy tiện phiên còn hạn nếu không có lỗi rõ |

Mỗi sự cố ghi timeline, phạm vi ảnh hưởng, request/config IDs an toàn, biện pháp và bằng chứng phục hồi. Hướng dẫn vận hành không tự cấp quyền publish/deploy thực tế.

## 7. Retention và media

Đề xuất pilot: search snapshot 15 phút, signed URL tối đa 5 phút, idempotency record tối thiểu 24 giờ. Raw query log mặc định tắt; nếu được chốt có thể lưu 7 ngày ban đầu. Refresh token registry, audit, tombstones, backup và purge grace period cần Q09.

Tombstone có hiệu lực ngay cho response sau commit; signed URL đã cấp không đảm bảo thu hồi tức thì. Nếu cần thu hồi tức thì, media proxy phải kiểm tra login và lifecycle hiện tại mỗi request và chính sách cache tương ứng. Xóa ảnh trong hệ live cần phân biệt với xóa khỏi backup theo lịch.

## 8. Capacity và chi phí

Dự toán riêng vector/index, ảnh gốc, thumbnail, backup, graph và generations song song. Đo dung lượng ảnh p50/p95 và tải theo [kế hoạch MVP địa danh](landmark-mvp-plan.md); tính egress, inference và công vận hành sau khi có benchmark.

Cập nhật C12: tính thêm graph nodes/edges/aliases/indexes/artifacts, backfill hai graph generations, VLM weights/KV/runtime memory, ảnh rendition, GPU concurrency, image egress và cost mỗi lượt rerank. Thay riêng VLM/prompt cần profile/quality gate và rollback cấu hình, không bắt buộc rebuild vector. Rebuild dùng maintenance window, không background catch-up. Tổng deadline thử dưới 5 giây và p95 warm < 2 giây chưa được chứng minh với graph+VLM; chốt Q15 theo benchmark end-to-end.

## 9. Local địa danh và model usage

FastAPI/PostgreSQL đã chọn, local Intel Raptor Lake-P dùng chung RAM hệ thống 16 GB. Bắt đầu encoder CPU, một model/microbatch nhỏ và giới hạn một inference worker để đo RAM; không cấu hình CUDA hoặc local VLM lớn theo giả định có VRAM riêng. VLM API ngoài được phép nhưng endpoint/model/API key và ngân sách chưa chốt. Đề xuất thử shortlist 5–10/target, tối đa 50 ảnh/request cho multi-target và concurrency API=1. Ghi token usage/retries/cost thực, quota cứng trong ứng dụng, timeout và provider credential references; không coi billing alert là hard cap.

Crawl jobs có rate/checkpoint và source/redirect/DNS allowlists, validate nguồn/attribution trước publish, không chạy trong search. Điều phối batch crawl/encode với online để tránh hết RAM; filesystem/object adapter và graph JSON sample lưu ngoài Git, không public ảnh gốc. API budget thử 10–20 USD là đề xuất đợt benchmark, không phải chi phí tháng cố định/phê duyệt gọi model. Chưa chi tiền/tải dataset/deploy trong giai đoạn tài liệu. [MVP địa danh](landmark-mvp-plan.md) ghi rõ các quyết định và đề xuất nguồn/model.
