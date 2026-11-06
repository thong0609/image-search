# Bộ tài liệu phân tích và thiết kế

Phiên bản: 0.5 — 06/11/2026. Đây là thiết kế để review và làm cơ sở triển khai; chưa có code ứng dụng hoặc kết quả benchmark.

## Phạm vi và cách đọc

Đã xác nhận: MVP nhận văn bản, tìm trong kho ảnh riêng 100.000–1.000.000 ảnh; Qdrant lưu vector và search metadata, tách khỏi DB quan hệ. Không feedback; có access/refresh token thay session đăng nhập và ba vai trò visitor/user/admin (visitor là khách, tài khoản lưu user/admin), không ACL ảnh/collection. Khách search/thumbnail, detail/download cần login. Phạm vi cập nhật gồm vector search, keyword search, graph search và VLM rerank sau hợp nhất ứng viên. Sau MVP có thể tìm bằng ảnh và thêm nguồn ngoài.

Mọi lựa chọn công nghệ, giới hạn đầu vào và chỉ tiêu hiệu năng ghi là **đề xuất** cho tới khi được chốt. Các thông tin thiếu được quản lý bằng mã Q trong [sổ quyết định](decisions.md). Không coi ví dụ dữ liệu là dữ liệu thật.

| Tài liệu | Nội dung | Đọc khi |
| --- | --- | --- |
| [PRD](prd.md) | Người dùng, yêu cầu, phạm vi, tiêu chí chấp nhận | Chốt sản phẩm |
| [Kiểm kê dữ liệu](data-inventory.md) | Thông tin kho ảnh cần thu thập, quy trình khảo sát, metadata | Chuẩn bị dữ liệu và sizing |
| [Thiết kế hệ thống](system-design.md) | Thành phần, luồng xử lý, nhất quán, mở rộng | Thiết kế backend/hạ tầng |
| [Mô hình dữ liệu](data-model.md) | Thực thể, ràng buộc, versioning, index | Thiết kế database |
| [Thiết kế Qdrant](qdrant-design.md) | Payload, collection/index, ranh giới với SQL, đồng bộ và consistency | Xây vector store và outbox |
| [Thiết kế tài khoản](auth-design.md) | Login/refresh/logout, JWT, rotation/revocation, role và chính sách media | Xây auth và quản trị |
| [Hợp đồng API](api-contract.md) | Request/response, lỗi, phân trang, quyền | Phối hợp frontend/backend |
| [Pipeline nhập ảnh](ingestion-design.md) | Batch, state machine, retry, cập nhật/xóa | Xây worker và công cụ quản trị |
| [Graph search và VLM rerank](graph-reranking-design.md) | Sơ đồ phân cấp, quan hệ, fusion, reranking và consistency | Triển khai phạm vi tìm kiếm mới |
| [Tìm kiếm và đánh giá](search-evaluation.md) | Retrieval, model, benchmark, quality gate | Thử nghiệm và nghiệm thu |
| [Vận hành](operations.md) | Triển khai, quan sát, backup, reindex, sự cố | Chuẩn bị pilot |
| [Kế hoạch thực hiện](delivery-plan.md) | Giai đoạn, đầu ra, phụ thuộc, traceability | Lập backlog |
| [Quyết định và câu hỏi](decisions.md) | ADR, giả định, thông tin cần chốt | Review thay đổi |
| [Phân tích tổng quan](mvp-architecture.md) | Giải thích định hướng và phương án ban đầu | Đọc nhập môn |
| [Kế hoạch quy mô](scale-plan.md) | Dung lượng, tải, mốc 100k/1M, nguồn ngoài | Capacity planning |

## Quy tắc cập nhật

- PRD là nguồn chuẩn cho phạm vi; API contract là nguồn chuẩn cho hành vi giao tiếp; data model là nguồn chuẩn cho ràng buộc dữ liệu.
- Sổ quyết định ghi lựa chọn công nghệ và trạng thái. Khi có thay đổi, cập nhật tài liệu liên quan trong cùng thay đổi.
- Các chỉ tiêu thử nghiệm dùng chung: p95 API warm < 2 giây; ANN Recall@100 ≥ 95%. Đây là mục tiêu đề xuất, phải gắn với phần cứng, QPS, dữ liệu và bộ lọc. Chưa có ngưỡng nghiệm thu semantic quality.
- Mục tiêu p95 trên áp dụng cho toàn pipeline gồm graph và VLM; cần đo lại ngân sách độ trễ và chốt Q13–Q15 trước nghiệm thu, không coi tốc độ baseline là tốc độ hệ thống mở rộng.
- Đã chọn Qdrant cho vector/search metadata; chưa chọn engine DB quan hệ, framework, checkpoint, cloud hoặc cấu hình production cuối cùng. Không có lệnh chạy/build/test ứng dụng được hỗ trợ ở giai đoạn tài liệu.
