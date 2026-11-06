# Lộ trình chia giai đoạn

**Mục tiêu:** xây hệ tìm ảnh địa danh tiếng Việt từ nguồn web, hỗ trợ tìm một địa danh, nhiều địa danh trong một câu và truy vấn qua quan hệ; dùng vector, keyword, graph và VLM rerank.

Đã chốt: một người phát triển, FastAPI, PostgreSQL, Qdrant; local Intel Raptor Lake-P với RAM chia sẻ 16 GB; cho phép VLM API ngoài. Phase 0 đã có scaffold code, migration 9 bảng và uv.lock; chưa có dataset. Các phase là cổng theo kết quả, không phải lịch tuần. Không chuyển sang đợt crawl lớn chỉ vì đã xong một endpoint.

| Phase | Mục tiêu | Đầu ra | Cổng hoàn tất |
|---|---|---|---|
| 0. Scaffold | Tạo nền local có thể chạy và phát triển | FastAPI, PostgreSQL, Qdrant, 9 bảng, cấu hình local, logging, migration, formatter/linter/test toolchain, API/worker skeleton; scaffold Next.js/TypeScript, Tailwind/shadcn, Query provider và fetch client | Có thể khởi động lại local theo README; fixture image đi qua health check; secrets không vào Git |
| 1. Dataset và truy vấn | Có dữ liệu dùng để đánh giá địa danh | Thử Wikimedia Commons cho ảnh và Wikidata cho entity/quan hệ; chọn 20–30 địa danh, thu 20–50 ảnh/địa danh (tối đa 1.500); lập query Việt thật | Mẫu ảnh được dedup và kiểm tra liên kết nơi chụp; mỗi ảnh giữ source page/media URL, external ID, tác giả, license, attribution, fetched time/hash; facts có source/revision; query có nhãn single/multi-target/multi-hop/no-answer |
| 2. Crawler và ingestion | Nhập web sample vào kho an toàn, có thể tiếp tục sau lỗi | Adapter Commons/Wikidata có checkpoint; crawl jobs; rate limits/User-Agent; URL/redirect/DNS/size checks; object storage local; thumbnail/hash/dedup; attribution; import/vector/graph publish | Crawl resume/retry được; attribution/license và liên kết ảnh–địa danh được giữ trong metadata; ảnh không đủ provenance bị loại khỏi publish; deleted/stale item không xuất hiện; crawl không nằm trên search path |
| 3. Single-target retrieval | Hoàn thiện baseline tìm một địa danh | Keyword và vector retrieval; benchmark CLIP so với SigLIP 2 trên CPU; filters; API kết quả có source/attribution | Bộ test Vietnamese single/no-answer có nhãn; chọn baseline bằng chất lượng, latency và RAM đo được; không quyết theo model name |
| 4. Multi-target | Trả riêng từng địa danh trong một câu | Query planner tách và resolve targets; ví dụ Hạ Long/Cát Bà; budget chung; nhóm kết quả và trạng thái thiếu kết quả | Mỗi target nhận ảnh thuộc đúng nhóm, count rõ; target thiếu ảnh không được bù bằng target khác; query mơ hồ trả yêu cầu làm rõ |
| 5. Graph và multi-hop | Trả kết quả qua đường quan hệ có nguồn | Place/entity aliases, quan hệ địa lý được version/provenance, traversal giới hạn và evidence references | Path khớp facts đã xác minh; hard constraint không bị bỏ khi graph lỗi; multi-hop thiếu facts được báo thiếu/no-answer |
| 6. VLM reranking | Cải thiện thứ tự ảnh trong shortlist | API model adapter; CPU encoder local; VLM API shortlist 5–10 ảnh mỗi target, tổng không quá budget; quota, timeout, fallback, usage/cost metrics | Ablation so vector/keyword/graph với và không VLM; đo p95 end-to-end, độ đúng theo target, cost/query; chốt model và mức chi trước pilot |
| 7. Sản phẩm MVP | Hoàn thiện hành trình, quyền và vận hành | UI/API tìm/lọc/nhóm/phân trang; import/admin; auth/media; attribution; backup/restore; telemetry và hướng dẫn dùng | FR có bằng chứng; data deletion không hồi sinh; guest/user/admin đúng quyền; reindex theo maintenance; lỗi dependency không giả thành rỗng |
| 8. Pilot và scale | Đưa đến nhóm dùng thử rồi mở rộng theo tải | Pilot local/staging; báo cáo chất lượng, QPS, p95, tài nguyên, API cost; kế hoạch deploy | Chốt quality/SLO/RPO-RTO/retention; diễn tập restore; chỉ sau khi workload đạt mới thử mốc lớn hơn hướng tới 100k–1M |

## Frontend theo giai đoạn

Stack: Next.js App Router + TypeScript + Tailwind CSS + shadcn/ui + TanStack Query; native fetch gọi FastAPI. Thiết kế đơn giản như Google Images: nền trắng, search bar, filters và lưới ảnh. Code ở `frontend/`, tổ chức theo feature; [kế hoạch MVP mục 7](landmark-mvp-plan.md#7-frontend-tối-giản) là nguồn chi tiết.

| Phase | Công việc FE | Điều kiện hoàn tất |
|---|---|---|
| 0. Scaffold FE | Next.js/TypeScript, Tailwind/shadcn Button, Query provider, fetch client, proxy FastAPI, lint/typecheck/build và lockfile | Chạy dev server, lint/typecheck/build được; chưa có nghiệp vụ search/auth |
| 3. Single-target | Xây trang tìm kiếm, filters, grid và panel mock trên scaffold có sẵn rồi nối API thật | URL giữ query/filters; loading/rỗng/lỗi rõ; ảnh giữ tỷ lệ, dùng được trên desktop/mobile; guest detail tuân auth contract |
| 4. Multi-target | Nhóm kết quả theo target, count/trạng thái từng nhóm; tải thêm theo cursor | Hạ Long/Cát Bà không bị trộn quota; response cũ không ghi đè query mới; snapshot expired tạo lượt mới |
| 5. Graph/multi-hop | Mục mở “Thông tin tìm kiếm” chứa path/facts và source links | Evidence đúng group/revision, thiếu dữ liệu được báo rõ |
| 6. VLM | Hoàn thiện trạng thái chờ, timeout/retry, degraded theo response | Không hiển thị score như xác suất; không tự giả kết quả khi backend lỗi |
| 7. Sản phẩm | Login/account, preview/download, crawl/import progress/retry, quản trị ảnh/tài khoản; hoàn thiện responsive, keyboard/focus, attribution | Token/refresh theo FastAPI, cache xóa khi đổi user/logout; E2E search → login → detail/download, admin và lỗi có bằng chứng |
| 8. Pilot | Đo tải thumbnail, layout shifts và trải nghiệm trên mobile/mạng chậm; chuẩn bị config deploy | Chốt frontend build/runtime, API/media origins; kiểm tra auth và deep link trên môi trường pilot |

Mock data phải có single, multi-target thiếu một nhóm, multi-hop và lỗi. Các hành vi quyền/media vẫn do FastAPI kiểm soát; FE scaffold nằm ở phase 0; phase 3 bắt đầu màn hình tìm kiếm. Toolchain/lockfile và lệnh chạy/lint/build nằm trong README.

## Trạng thái phase 0

Đã tạo layout src/modules/adapters/api, app factory FastAPI, config/logging, local object storage, Alembic 9 bảng, Compose PostgreSQL/Qdrant, worker idle, fixture/smoke CLI và bộ công cụ lint/test/build. Unit tests, lint, build và migration SQL offline đã chạy được. Docker Desktop đã chạy PostgreSQL/Qdrant; migrations 0001/0002 đã áp và test tích hợp đã qua. Cổng phase 0 còn cần kiểm tra luồng khởi động lại/smoke API theo README; frontend đã có scaffold phase 0, lint/typecheck/format và production build đã qua; HTTP trang chủ và proxy health FastAPI đã kiểm tra được. Trang tìm kiếm nghiệp vụ bắt đầu ở phase 3. Worker chưa claim job; auth/search/crawl mới có ranh giới module, triển khai ở phase sau.

## Phụ thuộc và cách làm

- Phase 0 có thể làm ngay với fixtures nhỏ; phần nguồn thật ở phase 1 cần được kiểm tra trước khi tải ảnh.
- Phase 1 và 2 bắt đầu bằng một nguồn crawl và một bộ seed giới hạn. Không mở crawler tổng quát hoặc crawl theo mọi URL người dùng nhập.
- Phase 3 là baseline trước khi tinh chỉnh fusion. Phase 4 tách mục tiêu trước khi đo chất lượng multi-target. Phase 5 chỉ dùng relation có nguồn; VLM không sinh facts thay cho graph.
- Phase 6 dùng quota ứng dụng và số đo request thực tế. Đề xuất ngân sách thử ban đầu 10–20 USD chưa được duyệt; không gọi API tính phí trước khi người dùng chốt hạn mức. Với Wikimedia, gửi request theo etiquette của nguồn, cache/checkpoint và backoff khi bị giới hạn; license/attribution được kiểm tra theo từng file chứ không gán một license chung cho cả Commons.
- Giữ 9 bảng SQL. Crawl/import/retry dùng `jobs`; các mục tiêu query lưu trong JSON của `search_sessions`. Không thêm dịch vụ riêng khi chưa có số đo cho thấy cần.
- Chi tiết adapter [Commons Imageinfo](https://www.mediawiki.org/wiki/API:Imageinfo), [Wikidata data access](https://www.wikidata.org/wiki/Wikidata:Data_access), [API etiquette](https://www.mediawiki.org/wiki/API:Etiquette) và [Commons reuse](https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia), cùng schema metadata, CPU/RAM nằm trong [kế hoạch MVP địa danh](landmark-mvp-plan.md); yêu cầu sản phẩm ở [PRD](prd.md); câu hỏi còn mở ở [decisions.md](decisions.md).

## Definition of done cho MVP

Người dùng gõ truy vấn tiếng Việt và nhận ảnh địa danh kèm nguồn; câu có nhiều địa danh trả nhóm riêng; multi-hop chỉ trả path có bằng chứng. Crawler có thể tiếp tục sau restart và giữ provenance. Vector/keyword/graph fusion và VLM rerank được đánh giá trên cùng bộ query; latency và chi phí được đo cùng chất lượng. Search, pagination, auth, xóa ảnh, lỗi dependency và restore được kiểm chứng trên sample. Mục tiêu cuối 100k–1M là scale gate riêng, không thay cho chất lượng đúng địa danh.
