# Quyết định, giả định và câu hỏi còn mở

Trạng thái ngày 04/11/2026. “Đã xác nhận” chỉ dùng cho thông tin người dùng đã cung cấp; ADR đề xuất là lựa chọn thiết kế để review, không biểu thị người dùng đã duyệt công nghệ.

## 1. Quyết định sản phẩm đã xác nhận

| ID | Quyết định | Nguồn |
| --- | --- | --- |
| C01 | MVP nhận yêu cầu bằng văn bản | Yêu cầu người dùng |
| C02 | MVP dùng kho ảnh riêng | Làm rõ của người dùng |
| C03 | Kho mục tiêu 100.000–1.000.000 ảnh | Làm rõ của người dùng |
| C04 | Tìm bằng ảnh là mở rộng sau MVP | Yêu cầu người dùng |
| C05 | Có thể thêm nguồn ảnh ngoài sau MVP | Làm rõ của người dùng |

## 2. ADR đề xuất

| ID | Lựa chọn | Phương án thay thế | Lý do và đánh đổi | Điều kiện xem lại |
| --- | --- | --- | --- | --- |
| ADR01 | Backend theo module, API/worker riêng process | Nhiều microservice | Dễ triển khai ban đầu; scale từng module hạn chế hơn | Tải/nhân lực đòi tách dịch vụ |
| ADR02 | Python/FastAPI là ứng viên backend | Stack nhóm đã quen | Thuận tiện pipeline ML; chưa chốt toolchain | Sau đánh giá năng lực nhóm Q10 |
| ADR03 | PostgreSQL + pgvector làm thử nghiệm mặc định | PostgreSQL + Qdrant | Ít hệ thống và giao dịch đơn; cần đo cạnh tranh tài nguyên | Benchmark 1M không đạt hoặc cần scale vector riêng |
| ADR04 | Image/text encoder cùng profile tương thích | Caption-only | Tái sử dụng cho image-to-image; cần chạy model ảnh lúc nhập | Benchmark miền dữ liệu hoặc model mới |
| ADR05 | HNSW cho ứng viên online, exact làm chuẩn đo | Exact-only/IVFFlat | Đánh đổi recall/độ trễ cần kiểm chứng | Sau benchmark filters và tài nguyên |
| ADR06 | Object storage giữ ảnh/thumbnail | Blob trong database/filesystem cục bộ | Tách dung lượng media khỏi truy vấn; nhất quán cross-store cần reconcile | Điều kiện on-prem hoặc nguồn storage Q07 |
| ADR07 | Jobs PostgreSQL có lease/fencing | Broker riêng | Giảm hạ tầng; contention cần đo | Backlog và DB contention vượt mục tiêu |
| ADR08 | Snapshot hữu hạn cho phân trang | Offset trên ANN chạy lại | Tránh lặp/thứ tự thay đổi; tốn storage và giới hạn cửa sổ | Nhu cầu duyệt sâu hoặc tải session cao |
| ADR09 | Metadata filters trước và kiểm tra quyền trước response | Lọc chỉ ở frontend | Đúng phạm vi; signed URL vẫn có thời gian hiệu lực | Yêu cầu thu hồi tức thì Q05 |
| ADR10 | Versioned generation và cutover | Ghi đè vector tại chỗ | Rollback/đánh giá tốt hơn; tăng dung lượng và catch-up | Chi phí hoặc downtime chấp nhận được |

Mỗi ADR khi chốt cần bổ sung người quyết định, ngày, benchmark liên quan và phạm vi có hiệu lực. Khi thay đổi, giữ lại ADR cũ ở trạng thái superseded, không xóa lý do đã dùng.

## 3. Giả định đang dùng

- Ưu tiên tiếng Việt do ngôn ngữ trao đổi; chưa xác nhận ngôn ngữ sản phẩm.
- Nhóm nhỏ và ưu tiên ít thành phần vận hành; chưa có thông tin nhân lực.
- Ảnh được phép xử lý và lưu; cần kiểm kê nguồn/quyền cụ thể.
- MVP dùng một collection cho mỗi image, collection grants làm scope; cơ chế danh tính chưa chọn.
- Chưa cần full web crawl, cá nhân hóa hay LLM trong đường tìm kiếm bắt buộc.

## 4. Câu hỏi cần chốt

| ID | Câu hỏi | Tác động | Cần có trước |
| --- | --- | --- | --- |
| Q01 | Lĩnh vực ảnh, người dùng chính và 10–20 query thật? | Chọn model, taxonomy, nhãn phù hợp | Thử nghiệm semantic |
| Q02 | Ngôn ngữ tìm kiếm và metadata hiện có? | Tokenizer, keyword, OCR/caption | Chốt retrieval profile |
| Q03 | QPS thường/đỉnh, người đồng thời và cửa sổ nhập ảnh? | Sizing, SLO, concurrency | Benchmark nghiệm thu |
| Q04 | Ngân sách, cloud/on-prem, GPU sẵn có? | Hạ tầng và phương án inference | Chốt môi trường pilot |
| Q05 | Ai được xem kho nào, đăng nhập hiện có, cần thu hồi media tức thì? | Identity, grants, signed URL/proxy | Triển khai quyền truy cập |
| Q06 | Availability, RPO/RTO và downtime chấp nhận? | Replica, backup, restore | Pilot có dữ liệu thật |
| Q07 | Nguồn lưu hiện tại, định dạng, kích thước và tốc độ cập nhật/xóa? | Adapter, validation, import/reindex | Import diện rộng |
| Q08 | Mức chất lượng đủ dùng theo nhóm query và ai gán nhãn? | Semantic acceptance gate | Nghiệm thu MVP |
| Q09 | Retention query, feedback, audit, backup và thời hạn purge? | Dữ liệu nhạy cảm, chi phí, xóa | Bật thu thập/lưu dữ liệu tương ứng |
| Q10 | Nhân lực, stack quen thuộc và deadline? | Toolchain, backlog và lịch | Cam kết kế hoạch thời gian |

Các câu hỏi trên là đầu vào thiết kế tiếp theo; không phải yêu cầu xin phép để tiếp tục viết tài liệu. Công việc độc lập với chúng có thể tiến hành theo giả định đã ghi rõ.

## 5. Rủi ro và hướng xử lý

| Rủi ro | Dấu hiệu | Hướng xử lý |
| --- | --- | --- |
| Model lệch miền/tiếng Việt | Nhóm query sai tập trung | Đánh giá baseline theo nhóm trước chọn model |
| Metadata thiếu hoặc sai | Tên/mã/filter không tìm được | Inventory, provenance, sửa dữ liệu; thêm OCR khi cần |
| Import ảnh hưởng tìm kiếm | p95 tăng khi batch chạy | Giới hạn batch, tách tài nguyên, đo đồng thời |
| Vector stale khi ảnh sửa/xóa | Version mismatch/tombstone lọt | CAS, fencing, final check, reconciliation |
| Reindex thiếu dung lượng/catch-up | Backlog không về 0 | Capacity hai generation, watermark, cutover gate |
| Benchmark có bias | Chất lượng test giảm mạnh khi pilot | Query thật, holdout, pooled labels, giữ cấu hình chạy |
| Phụ thuộc API ngoài về sau | Quota/lỗi nguồn làm chậm search | Adapter, timeout, chế độ suy giảm và source provenance |
