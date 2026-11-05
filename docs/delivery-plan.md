# Kế hoạch triển khai và truy vết yêu cầu

Trạng thái: backlog cấp thiết kế. Chưa có lịch tuần do chưa biết nhân lực/deadline (Q10). Chuyển giai đoạn theo bằng chứng đầu ra, không theo việc đã viết xong code.

## 1. Các giai đoạn

| Giai đoạn | Công việc | Đầu ra và điều kiện chuyển |
| --- | --- | --- |
| P0: khám phá dữ liệu | Inventory nguồn, thống kê kích thước/format/metadata, query thật, quyền | Data inventory, Q01/Q02/Q05/Q07 có câu trả lời đủ cho thử nghiệm |
| P1: thử nghiệm truy hồi | Mẫu đại diện, nhãn dev/test, so model và keyword/vector | Báo cáo semantic baseline, cấu hình có thể tái lập; thống nhất Q08 |
| P2: nền tảng | Chốt DB quan hệ/toolchain, Qdrant collections/payload indexes, object storage, identity, migrations, CI | Import và search skeleton chạy được với fixtures, manifest/lockfile/README đầy đủ |
| P3: pipeline dữ liệu | Batch jobs, lease/fencing, thumbnails, versioning, update/delete | Import phục hồi sau crash, replay an toàn, kiểm tra integrity |
| P4: sản phẩm tìm kiếm | Search/filter/snapshot/detail/download, login/logout/account/admin và UI | FR01–FR06, FR08–FR13 có kiểm thử, demo hành trình đầy đủ |
| P5: tải và vận hành | 100k/1M, filters/QPS, import đồng thời, restore/reindex | Báo cáo NFR, runbook đã thực hành, capacity/cost estimate |
| P6: pilot | Nhóm người dùng thật, đánh giá lỗi và giới hạn | Quyết định phát hành dựa trên yêu cầu đã chốt, không còn blocker quyền/dữ liệu |

P0 dùng [biểu mẫu kiểm kê dữ liệu](data-inventory.md). P1 có thể dùng pipeline thử nghiệm nhỏ trước P3 đầy đủ; kết quả P1 phải khóa profile trước khi embedding toàn bộ kho. UI có thể dùng mock theo API contract trong lúc backend được triển khai.

## 2. Các hạng mục triển khai

- DATA: inventory, sample có quyền, manifest revisions, metadata quality, label set.
- CORE: users/roles/refresh registry, JWT login/refresh/logout, rotation/reuse và Origin/header policy, catalog/version schema, Qdrant client và payload schema/indexes, object storage adapter, audit.
- INGEST: parser, jobs/leases, validate/decode, thumbnail, metadata snapshots, image batch encoder, transactional outbox, revisioned points, publish/retry/reconcile/purge.
- SEARCH: query validation, text encoder, vector retriever, filters, optional lexical fusion, snapshots.
- API/UI: hợp đồng lỗi, detail/media, import progress/retry, auth/download/account UI và các trạng thái giao diện.
- EVAL/OPS: deterministic fixtures, integration tests, benchmark runner, metrics, backup/restore, reindex/cutover.

Các nhóm là backlog logic, không chỉ định thêm agent hoặc microservice. Khi bắt đầu implementation, chia thành thay đổi nhỏ có đầu ra review được và validation phù hợp.

## 3. Ma trận truy vết

| Yêu cầu | Thiết kế | Bằng chứng cần có |
| --- | --- | --- |
| FR01 | API search + query/retrieval | Unicode/blank/token limit và semantic benchmark |
| FR02 | Qdrant filters + catalog check | Filters là lựa chọn người dùng, cùng phạm vi toàn kho giữa các user |
| FR03 | Detail/media contract | Khách xem thumbnail nhưng detail 401; login xong xem được, URL expiry |
| FR04 | Search session snapshot | Không lặp trang, cursor owner/tamper/expiry, dữ liệu thay đổi |
| FR05 | Manifest/import/jobs | Replay, crash recovery, progress totals |
| FR06 | Versions/tombstone/purge | Update race, delete during inference, stale worker |
| FR07 | Loại khỏi MVP theo C07 | Không có feedback table/endpoint/UI; nhãn offline vẫn ở benchmark |
| FR08 | Admin imports/items/retry | Phân quyền, retry all-or-nothing, safe error detail |
| FR09 | Auth/RBAC, không image ACL | visitor bị chặn detail/download/admin; user bị chặn quản trị ảnh/tài khoản; admin quản trị cả hai; mọi người tìm cùng toàn kho |
| FR10 | Login/me/access/refresh | JWT signature/claims, token types, expiry, single-use refresh/reuse/races, cookie flags/Origin/header, rate limit |
| FR11 | Logout/logout-all | Refresh family và access token cũ bị từ chối, clear refresh cookie, idempotence và DB failure |
| FR12 | Account/password/role/status | Auth_version, revoke refresh families, optimistic revision, last-admin race |
| FR13 | Download | Khách 401; user mọi role tải mọi ảnh published, search không lộ URL gốc |
| NFR01 | Scale plan | Mốc 100k và 1M thật đại diện |
| NFR02 | Search admission/deadline | p95 ở QPS/hardware/filter đã chốt |
| NFR03 | Semantic evaluation | Holdout report, subgroup metrics, Q08 đã chốt |
| NFR04 | ANN vs exact | Recall@100 cùng phạm vi, tie rules |
| NFR05 | Leases và restore runbook | Crash scenarios, restore đạt RPO/RTO |
| NFR06 | Generation/catch-up/cutover | Reindex rehearsal và rollback có dữ liệu cập nhật |
| NFR07 | Secrets/logs/media/retention | Kiểm tra quyền storage/log redaction và cấu hình retention |

Chi tiết ở [PRD](prd.md), [API](api-contract.md), [ingestion](ingestion-design.md), [evaluation](search-evaluation.md) và [operations](operations.md).

## 4. Chiến lược kiểm thử khi triển khai

Unit test cho logic có rủi ro: validation, cursor signing, role checks và public-search policy, state transitions, version checks và fusion. Integration test với DB quan hệ/Qdrant/storage adapters để kiểm chứng filters, lease, visibility và outbox replay. Bắt buộc kiểm tra crash sau Qdrant upsert trước SQL publish, write trễ sau delete, duplicate event, payload hash sai và restore lệch mốc; không giả định transaction xuyên hệ. Mock external inference/network cho test thường xuyên; live benchmark chạy riêng trên dữ liệu được phép.

End-to-end tối thiểu: nhập ảnh → đợi ready → tìm → lọc → phân trang → khách detail/download bị yêu cầu login → login → xem detail/download → logout → cập nhật → xóa → tìm lại không trả ảnh đó. Chạy thêm user gọi admin bị từ chối, hai user dùng cùng toàn kho, access/refresh hết hạn, reuse/response loss/role đổi, lỗi dependency và worker restart. Không kiểm tra chất lượng model bằng assertion trên vài ảnh rồi thay cho semantic benchmark.

Toolchain và lệnh test chưa cấu hình. Khi thêm source đầu tiên phải có formatter/linter, framework test thích hợp, manifest/lockfile và các lệnh chính xác trong README; không ghi lệnh giả đang được hỗ trợ.

## 5. Definition of done cho pilot

- Phạm vi, QPS, semantic gate, quyền và retention cần thiết đã được chốt.
- Mọi FR có bằng chứng; không còn lỗi làm lộ dữ liệu, hồi sinh ảnh xóa hoặc mất tiến độ đã commit.
- Kết quả benchmark được tái lập, ghi cả hạn chế và cấu hình thất bại.
- Restore và reindex/rollback đã diễn tập theo mục tiêu Q06.
- Có hướng dẫn người dùng/quản trị, screenshots UI khi có giao diện, danh sách giới hạn và đầu mối vận hành.
- Các chỉ tiêu chưa đạt được báo rõ và có quyết định phạm vi; không tự coi là hoàn thành chỉ vì hết thời gian.

## 6. Mở rộng sau pilot

Ưu tiên dựa trên lỗi thực tế: cải thiện metadata/hybrid → OCR/caption/reranker khi có bằng chứng → tìm bằng ảnh → nguồn ngoài theo nhu cầu. Thứ tự hai mở rộng cuối có thể đổi theo sản phẩm; mỗi phần cần PRD và benchmark riêng, không tự đưa vào MVP hiện tại.
