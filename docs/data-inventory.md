# Kiểm kê dữ liệu đầu vào

Trạng thái: biểu mẫu có hướng dẫn để hoàn thiện với kho ảnh thật. Hiện chỉ xác nhận kho riêng và tổng mục tiêu 100.000–1.000.000 ảnh; chưa có truy cập hoặc số liệu khảo sát kho.

## 1. Danh mục cần thu thập

| Hạng mục | Thông tin hiện có | Cách hoàn thiện | Dùng cho |
| --- | --- | --- | --- |
| Chủ kho và người dùng | Chưa cung cấp | Xác định người phụ trách dữ liệu và nhóm tìm ảnh | Phạm vi và quyền |
| Lĩnh vực ảnh | Chưa cung cấp | Phân loại các nhóm nội dung chính | Query set và model |
| Nguồn lưu | Kho riêng, chưa rõ nền tảng | Ghi bucket/prefix hoặc nguồn nội bộ, không ghi secret | Adapter nhập |
| Số lượng | Mục tiêu 100k–1M | Đếm object và ảnh hợp lệ riêng | Capacity |
| Byte size | Chưa đo | Min/median/p95/max và tổng bytes | Storage/network |
| Pixel size | Chưa đo | Width/height, p95 số pixel, orientation | Validation/inference |
| Định dạng | Chưa đo | JPEG/PNG/WebP/khác, ảnh động, file hỏng | Decoder và phạm vi hỗ trợ |
| Metadata | Chưa cung cấp | Độ phủ và độ đúng title/tag/license/mã hàng | Keyword/filters |
| Ngôn ngữ | Chưa xác nhận | Ngôn ngữ query và metadata | Model/tokenizer |
| Trùng lặp | Chưa đo | Trùng byte và gần trùng báo riêng | Chất lượng kết quả |
| Cập nhật/xóa | Chưa cung cấp | Số ảnh/ngày, đỉnh batch, revision nguồn | Incremental sync |
| Phân quyền | Chưa cung cấp | Collection, nhóm người dùng, hạn chế chia sẻ | Grants/media |
| Quyền xử lý | Chưa kiểm kê | Chủ sở hữu, license/provenance, hạn chế lưu/xử lý | Điều kiện đưa vào hệ thống |

## 2. Quy trình khảo sát đề xuất

1. Lập danh sách nguồn và người phụ trách; xác định vùng được phép đọc, không ghi credential trong báo cáo.
2. Lấy metadata object để đo số lượng/bytes trước; phân biệt file ảnh, thumbnail có sẵn và file khác để tránh đếm trùng.
3. Lấy mẫu phân tầng theo nguồn, collection, format và thời gian; đề xuất bắt đầu 1.000–5.000 ảnh nếu đủ đại diện, không suy diễn thống kê khi mẫu bị lệch.
4. Đọc mẫu bằng decoder có giới hạn để đo kích thước, lỗi, EXIF và orientation. Đo throughput end-to-end ở môi trường mục tiêu.
5. Kiểm tra checksum để ước lượng trùng byte; đánh giá gần trùng trên mẫu riêng nếu người dùng phản ánh vấn đề.
6. Tổng hợp độ phủ metadata, lỗi và chi phí xử lý; ghi tỷ lệ mẫu và khoảng dữ liệu chưa khảo sát.

Lưu kết quả thống kê tổng hợp trong báo cáo; giữ ảnh mẫu và manifest chứa đường dẫn riêng ở vùng dữ liệu ngoài Git. Chỉ đưa fixtures nhỏ có quyền rõ ràng vào repository khi bắt đầu implementation.

## 3. Từ điển metadata ban đầu

| Trường | Bắt buộc | Quy tắc |
| --- | --- | --- |
| source_item_key | Có | ID ổn định trong một source, không đổi theo tên hiển thị |
| input_revision | Có khi import | Integer dương tăng đơn điệu theo item, adapter cấp nếu cần |
| object_key/version | Có | Nằm trong nguồn được phép, nội dung bất biến hoặc kiểm tra version |
| collection | Có | Xác định phạm vi quản lý và truy cập |
| title | Không | Giữ nguyên tiếng Việt; không tự biến tên file thành mô tả đã xác minh |
| tags | Không | Danh sách chuỗi, chuẩn hóa theo taxonomy sau khi lĩnh vực rõ |
| license/provenance | Theo nguồn | Ghi đúng dữ liệu có chứng cứ, không suy đoán từ nội dung ảnh |
| width/height/checksum | Worker tạo | Lấy từ quá trình xử lý, không chỉ tin giá trị client |

Trường mới như SKU, địa điểm hoặc tác giả cần người phụ trách định nghĩa nguồn chuẩn, kiểu dữ liệu, độ phủ và quyền hiển thị trước khi đưa vào filter.

## 4. Đầu ra khảo sát và điều kiện sử dụng

Báo cáo cần có: dataset_revision, ngày khảo sát, sources được bao phủ, phương pháp lấy mẫu, số liệu tổng/mẫu, lỗi dữ liệu, quyền truy cập, hạn chế và đề xuất điều chỉnh pipeline.

Cho phép thử nghiệm nhỏ khi có mẫu hợp lệ và quyền xử lý rõ. Chỉ nhập diện rộng khi nguồn ổn định, revision được định nghĩa, giới hạn ảnh phù hợp và lỗi mẫu đã được phân loại. Các ảnh chưa rõ quyền hoặc không đáp ứng validation phải được tách ra, không tự sửa rồi đánh dấu ready.
