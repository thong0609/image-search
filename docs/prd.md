# Yêu cầu sản phẩm MVP

Trạng thái: bản nháp review v0.1. Phạm vi đã xác nhận được tách khỏi giả định và đề xuất trong [decisions.md](decisions.md).

Ràng buộc kỹ thuật đã xác nhận ngày 05/11/2026: Qdrant lưu vector và search metadata, tách biệt DB quan hệ; không dùng pgvector. DB quan hệ giữ nghiệp vụ/quyền và đã chọn PostgreSQL.

Cập nhật phạm vi 06/11/2026 (C12): kết hợp vector search, keyword search và graph search; dùng VLM rerank sau fusion. Vai trò hai thành phần đã được xác nhận; graph engine, model VLM và tham số vận hành còn là đề xuất.

Cập nhật C13: schema SQL còn 9 bảng; các API import/item vẫn giữ tài nguyên logic qua jobs. Reindex dùng maintenance window có chặn ghi/drain và khoảng dừng search tại cutover; không cam kết dual-write/catch-up hoặc rollback online tự động.

## 1. Bài toán và giá trị

Người dùng cần tìm ảnh phù hợp với mô tả trong kho riêng mà không phải nhớ tên file hoặc duyệt thủ công từng thư mục. Kết quả cần đủ liên quan để người dùng chọn được ảnh, có thể xem nguồn và xem toàn bộ ảnh đang hiển thị trong kho, không phân biệt tài khoản.

MVP nhận văn bản tiếng Việt, tạm chọn địa danh để người dùng hình dung nơi đó; hỗ trợ single, multi-target và multi-hop (C14/C18). Chưa có dataset; bổ sung thu thập web có kiểm soát nhập vào kho trước search (C15). Quy mô 100k–1M là mục tiêu kiến trúc, thử local trước trên sample nhỏ; không giả định có sẵn caption/tags/OCR. Chi tiết [MVP địa danh](landmark-mvp-plan.md).

## 2. Vai trò và hành trình

Có tài khoản, login/logout bằng access token + refresh token, không dùng session đăng nhập; có phân quyền chức năng. Ba vai trò visitor/user/admin đã chốt theo [thiết kế xác thực](auth-design.md). Khách tìm/xem thumbnail không cần login; detail và download cần login; mọi tài khoản có cùng phạm vi toàn kho. Chính sách truy cập này đã được xác nhận qua Q11.

| Vai trò | Nhu cầu | Quyền |
| --- | --- | --- |
| visitor | Tìm kiếm và xem danh sách/thumbnail | Khách chưa đăng nhập, không mở detail/download hoặc quản trị |
| user | Tìm kiếm, xem chi tiết và tải ảnh | Toàn kho đã công bố; không quản trị |
| admin | Quản trị ảnh và tài khoản/role/status | Quản trị ứng dụng toàn hệ thống; quyền hạ tầng vận hành cấp riêng |

Hành trình chính: nhập mô tả → chọn filters → xem lưới thumbnail → chọn ảnh → login nếu đang là khách → mở chi tiết hoặc download. Giao diện giữ lại query và filters khi quay lại danh sách; trạng thái loading, lỗi và rỗng có hướng xử lý rõ ràng.

## 3. Yêu cầu chức năng và chấp nhận

| ID | Yêu cầu | Tiêu chí chấp nhận |
| --- | --- | --- |
| FR01 | Tìm bằng văn bản | Query hợp lệ tạo danh sách có thứ tự; trả request_id; query trắng hoặc vượt giới hạn bị từ chối rõ ràng |
| FR02 | Lọc kết quả | Collection, hướng ảnh, kích thước có hành vi được định nghĩa; mọi item trả về thỏa bộ lọc; collection là phân loại, không là ACL |
| FR03 | Xem kết quả/chi tiết | Có thumbnail, kích thước, nguồn và tiêu đề nếu tồn tại; khách chỉ nhận thumbnail; detail/download trả 401 nếu chưa login, mọi user active xem/tải được toàn kho |
| FR04 | Phân trang | Trang tiếp theo không lặp item trong cùng phiên tìm kiếm; thay query/filters yêu cầu phiên mới |
| FR05 | Nhập ảnh theo batch | Có import_id, số thành công/thất bại và lỗi từng item; tiếp tục được sau worker crash |
| FR06 | Cập nhật và xóa ảnh | Content version cũ không được tái công bố; ảnh đã tombstone không còn xuất hiện trong response mới |
| FR07 | Đã loại khỏi MVP: feedback | Giữ ID lịch sử; không có bảng, endpoint hoặc UI feedback |
| FR08 | Quan sát pipeline | admin xem tiến độ, lỗi và retry trên toàn kho |
| FR09 | Phân quyền chức năng | user không gọi được admin APIs; admin quản trị cả ảnh và tài khoản; search không phân quyền theo ảnh/collection |
| FR10 | Đăng nhập và tài khoản hiện tại | Login hợp lệ cấp access/refresh; refresh rotate một lần và phát hiện reuse; sai/disabled không cấp; me dùng bearer access hợp lệ |
| FR11 | Đăng xuất | Logout thu hồi refresh family hiện tại, gọi lặp an toàn; refresh và access token của family bị từ chối sau revoke |
| FR12 | Quản trị tài khoản và mật khẩu | Admin tạo/khóa/đổi role; đổi mật khẩu bản thân yêu cầu mật khẩu hiện tại; tăng auth_version và thu hồi mọi refresh family khi role/status/password đổi |
| FR13 | Tải ảnh | User active tạo download URL/response cho ảnh đã công bố; khách nhận 401; search response không lộ URL ảnh gốc |
| FR14 | Tìm theo thực thể và quan hệ bằng graph | Liên kết query với entity, traversal có giới hạn trả image_id/version; điều kiện quan hệ bắt buộc phải được kiểm chứng; không trả ảnh cũ/xóa hoặc bỏ điều kiện khi graph lỗi |
| FR15 | VLM rerank ứng viên | Chấm query với ảnh đúng version trong shortlist sau fusion; chỉ sắp xếp ID hợp lệ; lưu model/prompt/config; lỗi hoặc fallback thể hiện theo API, không gọi VLM lại khi phân trang |
| FR16 | Thu thập ảnh/facts từ nguồn web đã cấu hình | Admin tạo crawl job có seed/quota/checkpoint; giữ nguồn/license/attribution/revisions, validate/dedup rồi nhập pipeline hiện tại; không gọi crawler trong search |
| FR17 | Query nhiều mục tiêu | “Ảnh Hạ Long, ảnh Cát Bà” trả nhóm theo từng target; nhóm thiếu ảnh được báo rõ, không lấp bằng target khác; budget chung hữu hạn |
| FR18 | Query multi-hop có bằng chứng | Thực thể/path lấy từ facts có nguồn/revision, trả evidence references; thiếu dữ liệu không bịa quan hệ, VLM không thay hard constraints |

Các filter khác như màu, phong cách, nhãn nội dung chỉ thêm khi có dữ liệu và tiêu chí đánh giá. Không hứa embedding sẽ thực thi chính xác yêu cầu đếm đối tượng hoặc phủ định.

## 4. Yêu cầu phi chức năng

| ID | Yêu cầu | Cách xác nhận |
| --- | --- | --- |
| NFR01 | Quy mô | Thử ở 100k và 1M ảnh đại diện, báo dữ liệu và cấu hình |
| NFR02 | Độ trễ | Mục tiêu đề xuất p95 API warm < 2 giây, gắn QPS chưa chốt Q03; không gồm tải ảnh trình duyệt |
| NFR03 | Chất lượng | Báo nDCG@10, Precision@10, Success@K theo nhóm truy vấn; ngưỡng semantic chờ Q08 |
| NFR04 | Độ đúng của ANN | Mục tiêu đề xuất Recall@100 ≥ 95% so với exact cùng filters, đo riêng với semantic quality |
| NFR05 | Phục hồi | Worker crash không mất tiến độ đã commit; kiểm thử backup/restore theo RPO/RTO chờ Q06 |
| NFR06 | Khả năng thay model | Maintenance chặn/drain ghi, dựng index mới trên dữ liệu đứng yên, kiểm chứng, cutover; rollback chỉ khi bản cũ còn khớp dữ liệu hoặc rebuild trước |
| NFR07 | Bảo vệ dữ liệu | Không công khai bucket riêng; logs không chứa token, signed URL hoặc ảnh riêng |

## 5. Ngoài phạm vi MVP

Graph search và VLM rerank thuộc phạm vi hiện tại; OCR/caption hoặc trích quan hệ bằng VLM toàn kho không tự được đưa vào chỉ vì đã có reranker.

Feedback, ACL theo ảnh/collection, tìm bằng ảnh, ảnh + văn bản, crawl toàn web không giới hạn, gọi API nguồn ảnh trực tiếp mỗi lượt search, cá nhân hóa, fine-tune, hội thoại nhiều lượt, OCR/caption toàn kho và tự động phân loại nội dung chưa nằm trong phạm vi mặc định. Có thể đưa một phần vào nếu benchmark chứng minh cần để đạt yêu cầu đã chốt.

## 6. Trạng thái giao diện

- Chưa tìm: ví dụ tiếng Việt về địa danh; phân biệt một target, nhiều targets và multi-hop.
- Nhiều targets: hiển thị nhóm riêng với tên địa danh/ảnh và trạng thái thiếu ảnh; bằng chứng multi-hop là facts/source path, không chain-of-thought.
- Đang tìm: giữ query và filters; hủy hoặc bỏ qua response của request cũ khi người dùng tìm lại.
- Có kết quả: thumbnail tải lười, xem chi tiết, phân trang.
- Rỗng: thông báo không có kết quả trong phạm vi; gợi ý nới filter hoặc mô tả lại. Không giả dạng lỗi dependency thành kết quả rỗng.
- Bảo trì: thông báo thao tác ghi đang tạm dừng; server trả 503 MAINTENANCE_MODE có Retry-After cho ghi catalog/import/graph và search khi cutover; giữ dữ liệu đã nhập. Auth tiếp tục nếu dependency sẵn sàng.
- Lỗi: cho retry; giữ dữ liệu đã nhập; request_id phục vụ hỗ trợ.
- Ảnh xóa/chưa công bố: gỡ khỏi lần hiển thị mới; detail trả 404.
- Khách chọn ảnh/download: chuyển login, thành công quay về ảnh đã chọn; chỉ chấp nhận đường dẫn returnTo nội bộ.
- Tài khoản: login/logout, me/đổi mật khẩu; admin có màn hình quản trị kho và tài khoản/role/status.

## 7. Điều kiện hoàn thành MVP

FR01–FR06 và FR08–FR18 có bằng chứng kiểm thử; FR07 đã loại khỏi MVP; benchmark đủ hai mốc dữ liệu; mục tiêu semantic, QPS và yêu cầu phục hồi được chốt trước nghiệm thu. Có danh sách hạn chế, runbook, cấu hình versioned, báo cáo chất lượng và kết quả pilot. Không coi tài liệu thiết kế hoặc demo tìm được vài ảnh là nghiệm thu hệ thống.
