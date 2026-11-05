# Images-search

Định hướng hệ thống tìm ảnh theo yêu cầu bằng văn bản ở MVP, dùng kho ảnh riêng với quy mô 100.000–1.000.000 ảnh. Sau MVP có thể mở rộng tìm bằng ảnh và tích hợp nguồn ảnh bên ngoài.

Repository hiện ở giai đoạn phân tích, chưa có ứng dụng hoặc toolchain. Chưa có lệnh cài đặt, chạy, build, lint hay test được cấu hình.

Lựa chọn dữ liệu đã chốt: **Qdrant lưu vector và metadata phục vụ tìm kiếm**, tách khỏi **DB quan hệ lưu nghiệp vụ và quyền**. PostgreSQL là đề xuất cho DB quan hệ; không dùng pgvector. Ảnh và metadata snapshots phục vụ phục hồi nằm trong object storage.

Truy cập: **khách được tìm kiếm và xem danh sách/thumbnail; mở chi tiết hoặc download cần đăng nhập**. Mọi tài khoản dùng cùng toàn kho; Ba vai trò là **visitor, user, admin**; visitor là khách không có tài khoản/phiên đăng nhập, admin quản trị cả ảnh và tài khoản. Login dùng **access token + refresh token**, không dùng session đăng nhập. Feedback chưa nằm trong MVP.

## Tài liệu

- [Mục lục bộ tài liệu phân tích và thiết kế](docs/README.md): PRD, thiết kế hệ thống, dữ liệu, API, pipeline nhập ảnh, tài khoản/login/logout, đánh giá, vận hành, kế hoạch và sổ quyết định.
- [Đề xuất MVP, kiến trúc và kế hoạch đánh giá](docs/mvp-architecture.md).
- [Kế hoạch quy mô 100.000–1.000.000 ảnh](docs/scale-plan.md).
- [Thiết kế Qdrant và đồng bộ với DB quan hệ](docs/qdrant-design.md).
- [Thiết kế tài khoản và phân quyền chức năng](docs/auth-design.md).
- `AGENTS.md`: quy ước làm việc trong repository.

Nguồn ảnh riêng, khoảng quy mô và lựa chọn Qdrant đã được xác nhận. Engine DB quan hệ và các công nghệ/cấu hình khác vẫn là đề xuất; lĩnh vực ảnh, tải truy vấn, ngân sách và yêu cầu nghiệp vụ cần được xác nhận trước khi chốt triển khai.
