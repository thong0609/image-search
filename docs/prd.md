# Yêu cầu sản phẩm MVP

Trạng thái: bản nháp review v0.1. Phạm vi đã xác nhận được tách khỏi giả định và đề xuất trong [decisions.md](decisions.md).

## 1. Bài toán và giá trị

Người dùng cần tìm ảnh phù hợp với mô tả trong kho riêng mà không phải nhớ tên file hoặc duyệt thủ công từng thư mục. Kết quả cần đủ liên quan để người dùng chọn được ảnh, có thể xem nguồn và truy cập ảnh theo quyền.

MVP nhận văn bản và hỗ trợ kho 100.000–1.000.000 ảnh. Chưa xác định ảnh thuộc sản phẩm, nội dung sáng tạo hay lĩnh vực khác (Q01); chưa giả định mọi kho đều có caption, tag hoặc OCR.

## 2. Vai trò và hành trình

Các vai trò logic đề xuất; có thể ánh xạ vào cơ chế danh tính sẵn có, không bắt buộc xây hệ thống tài khoản mới.

| Vai trò | Nhu cầu | Quyền |
| --- | --- | --- |
| Người tìm ảnh | Mô tả nhu cầu, lọc, xem chi tiết, gửi phản hồi | Chỉ tìm và mở ảnh trong các collection được cấp |
| Quản trị dữ liệu | Nhập, cập nhật, xóa, xem và retry lỗi | Quản trị trong collection được cấp; không mặc định toàn hệ thống |
| Người vận hành | Xem sức khỏe, backup, đổi cấu hình/index | Quyền vận hành riêng, thay đổi có audit |

Hành trình chính: nhập mô tả → chọn filters → xem lưới thumbnail → mở ảnh chi tiết → đánh giá kết quả nếu muốn. Giao diện giữ lại query và filters khi quay lại danh sách; trạng thái loading, lỗi và rỗng có hướng xử lý rõ ràng.

## 3. Yêu cầu chức năng và chấp nhận

| ID | Yêu cầu | Tiêu chí chấp nhận |
| --- | --- | --- |
| FR01 | Tìm bằng văn bản | Query hợp lệ tạo danh sách có thứ tự; trả request_id; query trắng hoặc vượt giới hạn bị từ chối rõ ràng |
| FR02 | Lọc kết quả | Collection, hướng ảnh, kích thước có hành vi được định nghĩa; mọi item trả về thỏa bộ lọc và quyền |
| FR03 | Xem kết quả/chi tiết | Có thumbnail, kích thước, nguồn và tiêu đề nếu tồn tại; chỉ cấp URL ảnh cho người có quyền |
| FR04 | Phân trang | Trang tiếp theo không lặp item trong cùng phiên tìm kiếm; thay query/filters yêu cầu phiên mới |
| FR05 | Nhập ảnh theo batch | Có import_id, số thành công/thất bại và lỗi từng item; tiếp tục được sau worker crash |
| FR06 | Cập nhật và xóa ảnh | Content version cũ không được tái công bố; ảnh đã tombstone không còn xuất hiện trong response mới |
| FR07 | Phản hồi tìm kiếm | Chỉ nhận phản hồi cho kết quả đã hiển thị trong phiên thuộc người dùng; không làm hỏng tìm kiếm nếu ghi feedback lỗi |
| FR08 | Quan sát pipeline | Quản trị xem tiến độ, lỗi, retry item thuộc phạm vi mình quản lý |
| FR09 | Quyền truy cập | Người dùng không thể lấy ảnh ngoài phạm vi qua search, detail, cursor, feedback hoặc URL cấp mới |

Các filter khác như màu, phong cách, nhãn nội dung chỉ thêm khi có dữ liệu và tiêu chí đánh giá. Không hứa embedding sẽ thực thi chính xác yêu cầu đếm đối tượng hoặc phủ định.

## 4. Yêu cầu phi chức năng

| ID | Yêu cầu | Cách xác nhận |
| --- | --- | --- |
| NFR01 | Quy mô | Thử ở 100k và 1M ảnh đại diện, báo dữ liệu và cấu hình |
| NFR02 | Độ trễ | Mục tiêu đề xuất p95 API warm < 2 giây, gắn QPS chưa chốt Q03; không gồm tải ảnh trình duyệt |
| NFR03 | Chất lượng | Báo nDCG@10, Precision@10, Success@K theo nhóm truy vấn; ngưỡng semantic chờ Q08 |
| NFR04 | Độ đúng của ANN | Mục tiêu đề xuất Recall@100 ≥ 95% so với exact cùng filters, đo riêng với semantic quality |
| NFR05 | Phục hồi | Worker crash không mất tiến độ đã commit; kiểm thử backup/restore theo RPO/RTO chờ Q06 |
| NFR06 | Khả năng thay model | Tạo index mới, catch-up thay đổi, kiểm chứng và rollback theo runbook |
| NFR07 | Bảo vệ dữ liệu | Không công khai bucket riêng; logs không chứa token, signed URL hoặc ảnh riêng |

## 5. Ngoài phạm vi MVP

Tìm bằng ảnh, ảnh + văn bản, crawl web, API nguồn ngoài, cá nhân hóa, fine-tune, hội thoại nhiều lượt, OCR/caption toàn kho và tự động phân loại nội dung chưa nằm trong phạm vi mặc định. Có thể đưa một phần vào nếu benchmark chứng minh cần để đạt yêu cầu đã chốt.

## 6. Trạng thái giao diện

- Chưa tìm: hướng dẫn ngắn, ví dụ minh họa phù hợp lĩnh vực sau khi chốt Q01.
- Đang tìm: giữ query và filters; hủy hoặc bỏ qua response của request cũ khi người dùng tìm lại.
- Có kết quả: thumbnail tải lười, xem chi tiết, phân trang, feedback tùy chọn.
- Rỗng: thông báo không có kết quả trong phạm vi; gợi ý nới filter hoặc mô tả lại. Không giả dạng lỗi dependency thành kết quả rỗng.
- Lỗi: cho retry; giữ dữ liệu đã nhập; request_id phục vụ hỗ trợ.
- Ảnh mất quyền/xóa: gỡ khỏi lần hiển thị mới; detail trả hành vi không tiết lộ sự tồn tại ngoài quyền.

## 7. Điều kiện hoàn thành MVP

FR01–FR09 có bằng chứng kiểm thử; benchmark đủ hai mốc dữ liệu; mục tiêu semantic, QPS và yêu cầu phục hồi được chốt trước nghiệm thu. Có danh sách hạn chế, runbook, cấu hình versioned, báo cáo chất lượng và kết quả pilot. Không coi tài liệu thiết kế hoặc demo tìm được vài ảnh là nghiệm thu hệ thống.
