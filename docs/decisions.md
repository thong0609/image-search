# Quyết định, giả định và câu hỏi còn mở

Trạng thái ngày 06/11/2026. “Đã xác nhận” chỉ dùng cho thông tin người dùng đã cung cấp; ADR chưa chốt là thiết kế để review. ADR03 có quyết định mới của người dùng thay phương án ban đầu.

## 1. Quyết định sản phẩm đã xác nhận

| ID | Quyết định | Nguồn |
| --- | --- | --- |
| C01 | MVP nhận yêu cầu bằng văn bản | Yêu cầu người dùng |
| C02 | MVP dùng kho ảnh riêng | Làm rõ của người dùng |
| C03 | Kho mục tiêu 100.000–1.000.000 ảnh | Làm rõ của người dùng |
| C04 | Tìm bằng ảnh là mở rộng sau MVP | Yêu cầu người dùng |
| C05 | Cũ: nguồn ngoài sau MVP; C15 cập nhật thu thập web để nhập kho vào phạm vi hiện tại. Gọi provider trực tiếp khi search vẫn để sau | Người dùng; superseded một phần bởi C15 |
| C06 | Dùng Qdrant lưu vector và metadata tìm kiếm, tách khỏi DB quan hệ; không dùng pgvector | Yêu cầu người dùng ngày 05/11/2026 |
| C07 | Chưa cần feedback trong MVP | Yêu cầu người dùng ngày 05/11/2026 |
| C08 | Có login/logout, phân quyền chức năng; không ACL theo ảnh/collection | Yêu cầu người dùng ngày 05/11/2026 |
| C09 | Khách search/xem danh sách và thumbnail; mở chi tiết/download cần login; user xem/tải toàn kho | Làm rõ của người dùng ngày 05/11/2026 |
| C10 | Ba vai trò visitor/user/admin; admin quản trị cả kho và tài khoản, user không quản trị | Yêu cầu người dùng ngày 05/11/2026 |
| C11 | Login dùng access token + refresh token, không dùng session đăng nhập | Yêu cầu người dùng ngày 05/11/2026 |
| C12 | Bổ sung graph search bên cạnh vector/keyword search và VLM để rerank ứng viên trong phạm vi triển khai hiện tại | Yêu cầu người dùng ngày 06/11/2026 |
| C13 | Rút schema từ 24 xuống 9 bảng SQL theo phương án đã đề xuất; giữ collections và audit_events; reindex có maintenance window, chưa hỗ trợ dual-write/catch-up hoặc rollback online tự động | Người dùng chấp thuận phương án ngày 06/11/2026 |
| C14 | Tạm chọn địa danh để người dùng hình dung nơi đó; bắt đầu tìm bằng tiếng Việt | Người dùng ngày 06/11/2026 |
| C15 | Chưa có dataset; bổ sung thu thập web vào kho trước search; nguồn cụ thể chưa chốt | Người dùng ngày 06/11/2026; cập nhật phạm vi C05 |
| C16 | Một người phát triển, backend FastAPI và PostgreSQL | Người dùng ngày 06/11/2026 |
| C17 | Triển khai local trước; RAM hệ thống 16 GB, Intel Raptor Lake-P dùng RAM chia sẻ, không VRAM chuyên dụng cố định; cho phép API VLM ngoài | Người dùng và làm rõ phần cứng ngày 06/11/2026 |
| C18 | Query một mục tiêu, nhiều mục tiêu như “ảnh Hạ Long, ảnh Cát Bà”, và multi-hop có suy luận quan hệ | Người dùng và làm rõ multi-target ngày 06/11/2026 |
| C19 | Frontend đơn giản theo phong cách Google Images; Next.js App Router/TypeScript, Tailwind, shadcn/ui, TanStack Query và fetch; code trong frontend/, xây search từ phase 3 | Người dùng yêu cầu đưa đề xuất FE vào kế hoạch |

## 2. ADR và trạng thái

ADR03 đã chốt ở mức lựa chọn Qdrant và tách DB; FastAPI/PostgreSQL đã chốt C16; schema payload và đồng bộ chi tiết vẫn cần kiểm chứng. ADR13/ADR14 đã chốt vai trò graph/VLM theo C12; engine, checkpoint và cấu hình cụ thể chưa chốt. Chi tiết ở [thiết kế Qdrant](qdrant-design.md).

| ID | Lựa chọn | Phương án thay thế | Lý do và đánh đổi | Điều kiện xem lại |
| --- | --- | --- | --- | --- |
| ADR01 | Backend theo module, API/worker riêng process | Nhiều microservice | Dễ triển khai ban đầu; scale từng module hạn chế hơn | Tải/nhân lực đòi tách dịch vụ |
| ADR02 | Python/FastAPI — đã chốt C16 | Stack khác | Một người phát triển chọn FastAPI; dependency versions/toolchain chưa cài | Chỉ thay khi người dùng đổi lựa chọn |
| ADR03 | Qdrant lưu vector/search metadata; DB quan hệ tách riêng — đã chốt | pgvector — phương án cũ đã bị thay thế | Theo yêu cầu người dùng 05/11/2026; thêm chi phí đồng bộ/backup hai hệ | Chỉ thay lựa chọn khi người dùng đổi yêu cầu; benchmark dùng chọn cấu hình |
| ADR04 | Image/text encoder cùng profile tương thích | Caption-only | Tái sử dụng cho image-to-image; cần chạy model ảnh lúc nhập | Benchmark miền dữ liệu hoặc model mới |
| ADR05 | Qdrant HNSW cho online, exact làm chuẩn đo | Qdrant exact-only | Đánh đổi recall/độ trễ cần kiểm chứng | Sau benchmark filters và tài nguyên |
| ADR06 | Object storage giữ ảnh/thumbnail | Blob trong database/filesystem cục bộ | Tách dung lượng media khỏi truy vấn; nhất quán cross-store cần reconcile | Điều kiện on-prem hoặc nguồn storage Q07 |
| ADR07 | Một bảng jobs có type/parent/dependencies và lease/fencing; PostgreSQL đã chọn C16 | Broker riêng | Giảm hạ tầng; contention cần đo | Backlog và DB contention vượt mục tiêu |
| ADR08 | Snapshot hữu hạn cho phân trang | Offset trên ANN chạy lại | Tránh lặp/thứ tự thay đổi; tốn storage và giới hạn cửa sổ | Nhu cầu duyệt sâu hoặc tải session cao |
| ADR09 | Không ACL theo ảnh; search/thumbnail public, detail/download cần auth; role cho quản trị — phạm vi đã chốt C08/C09 | Collection grants — thiết kế cũ đã thay thế | Phù hợp kho dùng chung; signed media URL đã cấp vẫn có TTL | Cấu hình media theo Q05, không tự thêm image ACL |
| ADR10 | Versioned indices với maintenance window và một config active — cập nhật C13 | Dual-write/catch-up online — hoãn | Ít registry/job state hơn; dừng ghi để build/cutover và rebuild khi cần rollback sau thay đổi dữ liệu | Chỉ mở rộng online nếu nhu cầu availability yêu cầu |
| ADR11 | Transactional outbox, immutable revisioned points, pointer công bố và reconciliation | Ghi kép trực tiếp | Không có transaction SQL/Qdrant; chống retry/stale writes bằng version và final check | Sau kiểm thử consistency và vận hành |
| ADR12 | Access + refresh token — đã chốt C11; đề xuất JWT access, opaque rotating refresh, registry hash và revocation checks | Opaque login session — thiết kế cũ superseded | Theo yêu cầu người dùng; TTL/transport/signing còn là đề xuất, thêm xử lý refresh/reuse/revocation | Q12 về provisioning/SSO và cấu hình token triển khai |
| ADR13 | Graph search là nhánh retrieval bổ sung — đã chốt C12; đề xuất graph projection versioned, entity linking và traversal có giới hạn | Chỉ vector/keyword/metadata filters | Tìm quan hệ nhiều bước; thêm chi phí dữ liệu, đồng bộ và vận hành; engine/schema cụ thể chưa chốt | Q13 và benchmark graph |
| ADR14 | VLM rerank sau fusion — đã chốt C12; đề xuất chấm query–ảnh trên shortlist hữu hạn, output có schema và fallback tường minh | Chỉ dùng thứ hạng fusion | Đánh giá chi tiết thị giác; thêm độ trễ, VRAM và chi phí; model/prompt chưa chốt | Q14/Q15 và benchmark end-to-end |
| ADR15 | Schema 9 bảng — đã chốt C13; JSON có schema cho index_state/snapshots, typed jobs làm queue/outbox, root token row giữ family state | Schema 24 bảng — superseded | Giảm bảng/join; chuyển một số validation sang ứng dụng và vận hành rebuild qua maintenance | Khi query/scale/online reindex cần schema tách riêng |

Mỗi ADR khi chốt cần bổ sung người quyết định, ngày, benchmark liên quan và phạm vi có hiệu lực. Khi thay đổi, giữ lại ADR cũ ở trạng thái superseded, không xóa lý do đã dùng.

Lịch sử ADR03: 04/11/2026 đề xuất PostgreSQL + pgvector để giảm thành phần và cập nhật metadata/vector cùng giao dịch; trạng thái superseded ngày 05/11/2026 bởi C06. Không có migration thực tế vì dự án chưa có implementation. Tại thời điểm ADR03 ban đầu PostgreSQL còn là ứng viên; C16 ngày 06/11/2026 đã chốt PostgreSQL, không dùng pgvector.

## 3. Giả định đang dùng

- Địa danh và tiếng Việt đã chốt C14; seed địa danh/phạm vi địa lý đầu tiên vẫn là đề xuất, chưa có dataset.
- Schema 9 bảng đã chốt C13; giữ collection và audit. Nguồn là config versioned, maintenance window thay cho dual-write/catch-up online.
- Một người phát triển và local đã chốt C16/C17; đề xuất ít dịch vụ, encoder CPU và VLM API trước. RAM 16 GB không được coi là VRAM dedicated/CUDA.
- Ảnh được phép xử lý và lưu; cần kiểm kê nguồn/quyền cụ thể.
- MVP dùng một collection phân loại cho mỗi image, không có collection grants. Visitor/user/admin đã chốt C10; visitor được biểu diễn bằng trạng thái chưa đăng nhập, tài khoản lưu user/admin. Cặp access/refresh đã chốt C11; JWT access, refresh cookie/TTL và registry là thiết kế đề xuất; phân quyền chức năng/login/logout và access policy đã được người dùng chốt.
- Chưa cần full web crawl, cá nhân hóa hoặc LLM để phân tích query. VLM rerank đã thuộc phạm vi C12; cấu hình đầy đủ chạy rerank, baseline không VLM chỉ dùng đối chứng hoặc fallback đã khai báo.

## 4. Câu hỏi cần chốt

| ID | Câu hỏi | Tác động | Cần có trước |
| --- | --- | --- | --- |
| Q01 | Đã chọn tạm địa danh để xem nơi đó thế nào; cần seed địa danh và 10–20 query/nhãn thật, gồm single/multi-target/multi-hop | Dataset/query plan/semantic quality | Trước benchmark |
| Q02 | Tiếng Việt đã chốt; chưa có metadata/dataset. title/description/tags và provenance theo đề xuất MVP địa danh | Metadata coverage, tokenizer và source mapping | Trước crawl sample |
| Q03 | QPS thường/đỉnh, người đồng thời và cửa sổ nhập ảnh? | Sizing, SLO, concurrency | Benchmark nghiệm thu |
| Q04 | Local Intel Raptor Lake-P, RAM chia sẻ 16 GB đã rõ; API VLM được phép. Chưa chốt budget/endpoint hoặc cloud sau này | CPU benchmark, API usage/cost, hosting | Trước chạy model có phí/deploy |
| Q05 | Có cần kiểm tra login ở mỗi lần đọc ảnh gốc/thu hồi URL tức thì, hay chấp nhận signed URL ngắn hạn có thể chia sẻ? | Signed URL/proxy cho preview/download; không đổi phạm vi tìm kiếm | Chốt cách phục vụ ảnh gốc |
| Q06 | Availability, RPO/RTO và downtime chấp nhận? | Replica, backup, restore | Pilot có dữ liệu thật |
| Q07 | Chưa có dataset; cần chốt nguồn/seed crawl, mapping license/attribution, quotas và cập nhật/xóa | Web acquisition/source adapter và import | Crawl sample và trước import diện rộng |
| Q08 | Mức chất lượng đủ dùng theo nhóm query và ai gán nhãn? | Semantic acceptance gate | Nghiệm thu MVP |
| Q09 | Retention query, refresh registry, audit, backup và thời hạn purge? | Dữ liệu nhạy cảm, chi phí, xóa | Bật thu thập/lưu dữ liệu tương ứng |
| Q10 | Một người, FastAPI/PostgreSQL đã chốt; frontend theo C19, deadline còn mở | Toolchain/UI và lịch | Trước cam kết lịch |
| Q11 | Đã giải quyết: khách search/thumbnail; detail/download cần login, mọi user dùng toàn kho | C09; không phải câu hỏi còn mở | Đã chốt 05/11/2026 |
| Q12 | Admin cấp tài khoản hay tự đăng ký? Có SSO/quên mật khẩu/email recovery trong MVP không? | Provisioning tài khoản và trải nghiệm khách muốn tải ảnh | Chốt workflow tài khoản |
| Q13 | Loại thực thể/quan hệ, nguồn chuẩn, độ phủ, quy tắc hợp nhất thực thể và graph engine nào? | Graph schema, chất lượng và consistency | Khóa graph profile và backfill |
| Q14 | VLM checkpoint/hosting, quyền gửi ảnh, độ phân giải, prompt/output và ngân sách inference nào? | Rerank quality, VRAM, chi phí | Khóa reranker profile |
| Q15 | Rerank window, deadline, QPS và có cho phép fallback khi graph/VLM lỗi không? | SLO end-to-end và chính sách degraded | Nghiệm thu pipeline mới |

Lịch sử ADR12: thiết kế opaque auth session và auth_sessions ban đầu được superseded bởi C11. Không có session login; bản ghi refresh hash/family phục vụ rotation/revocation. search_sessions vẫn là snapshot phân trang.

Lịch sử ADR09: collection-level grants và feedback từng được đề xuất nhưng bị thay thế theo C07–C09; không tạo bảng/API feedback và không áp dụng ACL đó. FR07 giữ ID lịch sử ở trạng thái loại khỏi MVP.

Các câu hỏi còn mở trên là đầu vào thiết kế tiếp theo; không phải yêu cầu xin phép để tiếp tục viết tài liệu. Công việc độc lập với chúng có thể tiến hành theo giả định đã ghi rõ.

## 5. Rủi ro và hướng xử lý

| Rủi ro | Dấu hiệu | Hướng xử lý |
| --- | --- | --- |
| Model lệch miền/tiếng Việt | Nhóm query sai tập trung | Đánh giá baseline theo nhóm trước chọn model |
| Metadata thiếu hoặc sai | Tên/mã/filter không tìm được | Inventory, provenance, sửa dữ liệu; thêm OCR khi cần |
| Import ảnh hưởng tìm kiếm | p95 tăng khi batch chạy | Giới hạn batch, tách tài nguyên, đo đồng thời |
| Vector stale khi ảnh sửa/xóa | Version mismatch/tombstone lọt | CAS, fencing, final check, reconciliation |
| Ghi Qdrant thành công nhưng SQL chưa công bố hoặc ngược lại sau restore | Unpublished/missing point, payload hash lệch | Outbox replay, immutable point revision, published pointer, đối soát và restore cách ly |
| Reindex vượt maintenance window | Writers/jobs chưa drain hoặc build quá lâu | Đo thời gian maintenance, checkpoint rebuild, capacity bản cũ/mới, gate trước mở ghi; chưa cam kết online catch-up |
| Benchmark có bias | Chất lượng test giảm mạnh khi pilot | Query thật, holdout, pooled labels, giữ cấu hình chạy |
| Graph sai/thưa hoặc lỗi liên kết thực thể | Query quan hệ sai dù vector đúng | Nguồn chuẩn, provenance, nhãn graph, giới hạn traversal và benchmark ablation |
| Graph stale hoặc cạnh bị hồi sinh | Image/version mismatch, quan hệ cũ còn trả về | Projection bất biến, published pointer, tombstone, kiểm tra revision và reconcile |
| VLM chậm hoặc output sai | p95 tăng, thiếu/trùng ID, score ngoài schema | Shortlist hữu hạn, admission limit, validate toàn batch, strict/fallback theo profile |
| Phụ thuộc API ngoài về sau | Quota/lỗi nguồn làm chậm search | Adapter, timeout, chế độ suy giảm và source provenance |

Lịch sử C13/ADR15: thiết kế tách source/family/generation/projection/import/item/delivery/search-item thành bảng riêng được superseded bởi schema 9 bảng. Không có migration thực tế. Family và projection vẫn là khái niệm nghiệp vụ, được lưu qua root row/index_state; jobs tạo cùng transaction catalog giữ transactional outbox. ADR10 đổi từ reindex có catch-up sang maintenance runbook; auth vẫn giữ rotation/reuse detection và access revocation sau commit.

C14–C18 cập nhật phạm vi ngày 06/11/2026: chưa có data, crawl nguồn có kiểm soát trở thành acquisition offline hiện tại; nguồn Wikimedia/Wikidata, graph JSON adapter và API VLM Flash/Flash-Lite là đề xuất ở [MVP địa danh](landmark-mvp-plan.md), không tự coi đã chốt engine/provider/budget. C18 nhiều mục tiêu khác số lượng ảnh: “Hạ Long, Cát Bà” phải có hai nhóm, không một danh sách top-2 tùy ý. Chưa có crawl/model run thực tế hoặc chi phí phát sinh do cập nhật tài liệu này.
