# Quyết định, giả định và câu hỏi còn mở

Trạng thái ngày 05/11/2026. “Đã xác nhận” chỉ dùng cho thông tin người dùng đã cung cấp; ADR chưa chốt là thiết kế để review. ADR03 có quyết định mới của người dùng thay phương án ban đầu.

## 1. Quyết định sản phẩm đã xác nhận

| ID | Quyết định | Nguồn |
| --- | --- | --- |
| C01 | MVP nhận yêu cầu bằng văn bản | Yêu cầu người dùng |
| C02 | MVP dùng kho ảnh riêng | Làm rõ của người dùng |
| C03 | Kho mục tiêu 100.000–1.000.000 ảnh | Làm rõ của người dùng |
| C04 | Tìm bằng ảnh là mở rộng sau MVP | Yêu cầu người dùng |
| C05 | Có thể thêm nguồn ảnh ngoài sau MVP | Làm rõ của người dùng |
| C06 | Dùng Qdrant lưu vector và metadata tìm kiếm, tách khỏi DB quan hệ; không dùng pgvector | Yêu cầu người dùng ngày 05/11/2026 |
| C07 | Chưa cần feedback trong MVP | Yêu cầu người dùng ngày 05/11/2026 |
| C08 | Có login/logout, phân quyền chức năng; không ACL theo ảnh/collection | Yêu cầu người dùng ngày 05/11/2026 |
| C09 | Khách search/xem danh sách và thumbnail; mở chi tiết/download cần login; user xem/tải toàn kho | Làm rõ của người dùng ngày 05/11/2026 |
| C10 | Ba vai trò visitor/user/admin; admin quản trị cả kho và tài khoản, user không quản trị | Yêu cầu người dùng ngày 05/11/2026 |
| C11 | Login dùng access token + refresh token, không dùng session đăng nhập | Yêu cầu người dùng ngày 05/11/2026 |

## 2. ADR và trạng thái

ADR03 đã chốt ở mức lựa chọn Qdrant và tách DB; PostgreSQL cho DB quan hệ, schema payload, đồng bộ và các ADR khác còn là đề xuất. Chi tiết ở [thiết kế Qdrant](qdrant-design.md).

| ID | Lựa chọn | Phương án thay thế | Lý do và đánh đổi | Điều kiện xem lại |
| --- | --- | --- | --- | --- |
| ADR01 | Backend theo module, API/worker riêng process | Nhiều microservice | Dễ triển khai ban đầu; scale từng module hạn chế hơn | Tải/nhân lực đòi tách dịch vụ |
| ADR02 | Python/FastAPI là ứng viên backend | Stack nhóm đã quen | Thuận tiện pipeline ML; chưa chốt toolchain | Sau đánh giá năng lực nhóm Q10 |
| ADR03 | Qdrant lưu vector/search metadata; DB quan hệ tách riêng — đã chốt | pgvector — phương án cũ đã bị thay thế | Theo yêu cầu người dùng 05/11/2026; thêm chi phí đồng bộ/backup hai hệ | Chỉ thay lựa chọn khi người dùng đổi yêu cầu; benchmark dùng chọn cấu hình |
| ADR04 | Image/text encoder cùng profile tương thích | Caption-only | Tái sử dụng cho image-to-image; cần chạy model ảnh lúc nhập | Benchmark miền dữ liệu hoặc model mới |
| ADR05 | Qdrant HNSW cho online, exact làm chuẩn đo | Qdrant exact-only | Đánh đổi recall/độ trễ cần kiểm chứng | Sau benchmark filters và tài nguyên |
| ADR06 | Object storage giữ ảnh/thumbnail | Blob trong database/filesystem cục bộ | Tách dung lượng media khỏi truy vấn; nhất quán cross-store cần reconcile | Điều kiện on-prem hoặc nguồn storage Q07 |
| ADR07 | Jobs PostgreSQL có lease/fencing | Broker riêng | Giảm hạ tầng; contention cần đo | Backlog và DB contention vượt mục tiêu |
| ADR08 | Snapshot hữu hạn cho phân trang | Offset trên ANN chạy lại | Tránh lặp/thứ tự thay đổi; tốn storage và giới hạn cửa sổ | Nhu cầu duyệt sâu hoặc tải session cao |
| ADR09 | Không ACL theo ảnh; search/thumbnail public, detail/download cần auth; role cho quản trị — phạm vi đã chốt C08/C09 | Collection grants — thiết kế cũ đã thay thế | Phù hợp kho dùng chung; signed media URL đã cấp vẫn có TTL | Cấu hình media theo Q05, không tự thêm image ACL |
| ADR10 | Versioned generation và cutover | Ghi đè vector tại chỗ | Rollback/đánh giá tốt hơn; tăng dung lượng và catch-up | Chi phí hoặc downtime chấp nhận được |
| ADR11 | Transactional outbox, immutable revisioned points, pointer công bố và reconciliation | Ghi kép trực tiếp | Không có transaction SQL/Qdrant; chống retry/stale writes bằng version và final check | Sau kiểm thử consistency và vận hành |
| ADR12 | Access + refresh token — đã chốt C11; đề xuất JWT access, opaque rotating refresh, registry hash và revocation checks | Opaque login session — thiết kế cũ superseded | Theo yêu cầu người dùng; TTL/transport/signing còn là đề xuất, thêm xử lý refresh/reuse/revocation | Q12 về provisioning/SSO và cấu hình token triển khai |

Mỗi ADR khi chốt cần bổ sung người quyết định, ngày, benchmark liên quan và phạm vi có hiệu lực. Khi thay đổi, giữ lại ADR cũ ở trạng thái superseded, không xóa lý do đã dùng.

Lịch sử ADR03: 04/11/2026 đề xuất PostgreSQL + pgvector để giảm thành phần và cập nhật metadata/vector cùng giao dịch; trạng thái superseded ngày 05/11/2026 bởi C06. Không có migration thực tế vì dự án chưa có implementation. PostgreSQL vẫn là ứng viên cho DB quan hệ, không phải lựa chọn đã xác nhận.

## 3. Giả định đang dùng

- Ưu tiên tiếng Việt do ngôn ngữ trao đổi; chưa xác nhận ngôn ngữ sản phẩm.
- Nhóm nhỏ và ưu tiên ít thành phần vận hành; chưa có thông tin nhân lực.
- Ảnh được phép xử lý và lưu; cần kiểm kê nguồn/quyền cụ thể.
- MVP dùng một collection phân loại cho mỗi image, không có collection grants. Visitor/user/admin đã chốt C10; visitor được biểu diễn bằng trạng thái chưa đăng nhập, tài khoản lưu user/admin. Cặp access/refresh đã chốt C11; JWT access, refresh cookie/TTL và registry là thiết kế đề xuất; phân quyền chức năng/login/logout và access policy đã được người dùng chốt.
- Chưa cần full web crawl, cá nhân hóa hay LLM trong đường tìm kiếm bắt buộc.

## 4. Câu hỏi cần chốt

| ID | Câu hỏi | Tác động | Cần có trước |
| --- | --- | --- | --- |
| Q01 | Lĩnh vực ảnh, người dùng chính và 10–20 query thật? | Chọn model, taxonomy, nhãn phù hợp | Thử nghiệm semantic |
| Q02 | Ngôn ngữ tìm kiếm và metadata hiện có? | Tokenizer, keyword, OCR/caption | Chốt retrieval profile |
| Q03 | QPS thường/đỉnh, người đồng thời và cửa sổ nhập ảnh? | Sizing, SLO, concurrency | Benchmark nghiệm thu |
| Q04 | Ngân sách, cloud/on-prem, GPU sẵn có? | Hạ tầng và phương án inference | Chốt môi trường pilot |
| Q05 | Có cần kiểm tra login ở mỗi lần đọc ảnh gốc/thu hồi URL tức thì, hay chấp nhận signed URL ngắn hạn có thể chia sẻ? | Signed URL/proxy cho preview/download; không đổi phạm vi tìm kiếm | Chốt cách phục vụ ảnh gốc |
| Q06 | Availability, RPO/RTO và downtime chấp nhận? | Replica, backup, restore | Pilot có dữ liệu thật |
| Q07 | Nguồn lưu hiện tại, định dạng, kích thước và tốc độ cập nhật/xóa? | Adapter, validation, import/reindex | Import diện rộng |
| Q08 | Mức chất lượng đủ dùng theo nhóm query và ai gán nhãn? | Semantic acceptance gate | Nghiệm thu MVP |
| Q09 | Retention query, refresh registry, audit, backup và thời hạn purge? | Dữ liệu nhạy cảm, chi phí, xóa | Bật thu thập/lưu dữ liệu tương ứng |
| Q10 | Nhân lực, stack quen thuộc và deadline? | Toolchain, backlog và lịch | Cam kết kế hoạch thời gian |
| Q11 | Đã giải quyết: khách search/thumbnail; detail/download cần login, mọi user dùng toàn kho | C09; không phải câu hỏi còn mở | Đã chốt 05/11/2026 |
| Q12 | Admin cấp tài khoản hay tự đăng ký? Có SSO/quên mật khẩu/email recovery trong MVP không? | Provisioning tài khoản và trải nghiệm khách muốn tải ảnh | Chốt workflow tài khoản |

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
| Reindex thiếu dung lượng/catch-up | Backlog không về 0 | Capacity hai generation, watermark, cutover gate |
| Benchmark có bias | Chất lượng test giảm mạnh khi pilot | Query thật, holdout, pooled labels, giữ cấu hình chạy |
| Phụ thuộc API ngoài về sau | Quota/lỗi nguồn làm chậm search | Adapter, timeout, chế độ suy giảm và source provenance |
