# Lộ trình chia giai đoạn

**Mục tiêu:** xây hệ tìm ảnh địa danh tiếng Việt từ nguồn web, hỗ trợ tìm một địa danh, nhiều địa danh trong một câu và truy vấn qua quan hệ; dùng vector, keyword, graph và VLM rerank.

Đã chốt: một người phát triển, FastAPI, PostgreSQL, Qdrant; local Intel Raptor Lake-P với RAM chia sẻ 16 GB; cho phép VLM API ngoài. Chưa có code hoặc dataset. Các phase là cổng theo kết quả, không phải lịch tuần. Không chuyển sang đợt crawl lớn chỉ vì đã xong một endpoint.

| Phase | Mục tiêu | Đầu ra | Cổng hoàn tất |
|---|---|---|---|
| 0. Scaffold | Tạo nền local có thể chạy và phát triển | FastAPI, PostgreSQL, Qdrant, 9 bảng, cấu hình local, logging, migration, formatter/linter/test toolchain, API/worker skeleton | Có thể khởi động lại local theo README; fixture image đi qua health check; secrets không vào Git |
| 1. Dataset và truy vấn | Có dữ liệu dùng để đánh giá địa danh | Chọn một nguồn/seed nhỏ; query Việt thật; ảnh, source URL, attribution/license, entity/place link và manifest có provenance | Mẫu 400–1.500 ảnh tối đa đã được kiểm tra, dedup; nhãn query có single/multi-target/multi-hop và no-answer; facts đủ nguồn |
| 2. Crawler và ingestion | Nhập web sample vào kho an toàn, có thể tiếp tục sau lỗi | Một source adapter; crawl jobs/checkpoint; URL/redirect/DNS/size/rate limits; object storage local; thumbnail/hash/dedup; import/vector/graph publish | Crawler resume/retry được; chỉ ảnh có metadata/nguồn hợp lệ searchable; deleted/stale item không xuất hiện; crawl không nằm trên search path |
| 3. Single-target retrieval | Hoàn thiện baseline tìm một địa danh | Keyword và vector retrieval; benchmark CLIP so với SigLIP 2 trên CPU; filters; API kết quả có source/attribution | Bộ test Vietnamese single/no-answer có nhãn; chọn baseline bằng chất lượng, latency và RAM đo được; không quyết theo model name |
| 4. Multi-target | Trả riêng từng địa danh trong một câu | Query planner tách và resolve targets; ví dụ Hạ Long/Cát Bà; budget chung; nhóm kết quả và trạng thái thiếu kết quả | Mỗi target nhận ảnh thuộc đúng nhóm, count rõ; target thiếu ảnh không được bù bằng target khác; query mơ hồ trả yêu cầu làm rõ |
| 5. Graph và multi-hop | Trả kết quả qua đường quan hệ có nguồn | Place/entity aliases, quan hệ địa lý được version/provenance, traversal giới hạn và evidence references | Path khớp facts đã xác minh; hard constraint không bị bỏ khi graph lỗi; multi-hop thiếu facts được báo thiếu/no-answer |
| 6. VLM reranking | Cải thiện thứ tự ảnh trong shortlist | API model adapter; CPU encoder local; VLM API shortlist 5–10 ảnh mỗi target, tổng không quá budget; quota, timeout, fallback, usage/cost metrics | Ablation so vector/keyword/graph với và không VLM; đo p95 end-to-end, độ đúng theo target, cost/query; chốt model và mức chi trước pilot |
| 7. Sản phẩm MVP | Hoàn thiện hành trình, quyền và vận hành | UI/API tìm/lọc/nhóm/phân trang; import/admin; auth/media; attribution; backup/restore; telemetry và hướng dẫn dùng | FR có bằng chứng; data deletion không hồi sinh; guest/user/admin đúng quyền; reindex theo maintenance; lỗi dependency không giả thành rỗng |
| 8. Pilot và scale | Đưa đến nhóm dùng thử rồi mở rộng theo tải | Pilot local/staging; báo cáo chất lượng, QPS, p95, tài nguyên, API cost; kế hoạch deploy | Chốt quality/SLO/RPO-RTO/retention; diễn tập restore; chỉ sau khi workload đạt mới thử mốc lớn hơn hướng tới 100k–1M |

## Phụ thuộc và cách làm

- Phase 0 có thể làm ngay với fixtures nhỏ; phần nguồn thật ở phase 1 cần được kiểm tra trước khi tải ảnh.
- Phase 1 và 2 bắt đầu bằng một nguồn crawl và một bộ seed giới hạn. Không mở crawler tổng quát hoặc crawl theo mọi URL người dùng nhập.
- Phase 3 là baseline trước khi tinh chỉnh fusion. Phase 4 tách mục tiêu trước khi đo chất lượng multi-target. Phase 5 chỉ dùng relation có nguồn; VLM không sinh facts thay cho graph.
- Phase 6 dùng quota ứng dụng và số đo request thực tế. Đề xuất ngân sách thử ban đầu 10–20 USD chưa được duyệt; không gọi API tính phí trước khi người dùng chốt hạn mức.
- Giữ 9 bảng SQL. Crawl/import/retry dùng `jobs`; các mục tiêu query lưu trong JSON của `search_sessions`. Không thêm dịch vụ riêng khi chưa có số đo cho thấy cần.
- Chi tiết crawler, schema metadata, CPU/RAM và nguồn đề xuất nằm trong [kế hoạch MVP địa danh](landmark-mvp-plan.md); yêu cầu sản phẩm ở [PRD](prd.md); câu hỏi còn mở ở [decisions.md](decisions.md).

## Definition of done cho MVP

Người dùng gõ truy vấn tiếng Việt và nhận ảnh địa danh kèm nguồn; câu có nhiều địa danh trả nhóm riêng; multi-hop chỉ trả path có bằng chứng. Crawler có thể tiếp tục sau restart và giữ provenance. Vector/keyword/graph fusion và VLM rerank được đánh giá trên cùng bộ query; latency và chi phí được đo cùng chất lượng. Search, pagination, auth, xóa ảnh, lỗi dependency và restore được kiểm chứng trên sample. Mục tiêu cuối 100k–1M là scale gate riêng, không thay cho chất lượng đúng địa danh.
