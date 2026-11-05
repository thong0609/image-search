# Kế hoạch quy mô 100.000–1.000.000 ảnh

Trạng thái: cập nhật ngày 05/11/2026. Kho riêng 100k–1M ảnh và Qdrant lưu vector/search metadata đã được xác nhận; cấu hình triển khai còn là đề xuất. Chưa có benchmark hoặc hệ thống được triển khai.

Truy cập đã chốt: khách search và xem thumbnail; detail/download cần login; mọi user tìm/xem cùng toàn kho. Không có feedback trong MVP.

## 1. Phạm vi đã chốt

- MVP: tìm bằng văn bản trên kho ảnh riêng, 100.000–1.000.000 ảnh.
- Mở rộng: tìm bằng ảnh và tích hợp nguồn ảnh bên ngoài.
- Chưa chốt: lĩnh vực ảnh, metadata, ngôn ngữ truy vấn, tải truy vấn, ngân sách, tốc độ cập nhật và yêu cầu sẵn sàng.

Một triệu ảnh chưa tự nó quyết định phải dùng hệ phân tán. Cần đo đồng thời dung lượng, QPS, bộ lọc, recall và tải nhập dữ liệu. Khuyến nghị giữ backend chung codebase, chạy API và worker riêng, có thể bố trí tài nguyên độc lập.

## 2. Lựa chọn hệ lưu trữ

Qdrant là vector database đã chọn và lưu cả payload metadata tìm kiếm. DB quan hệ tách biệt giữ nghiệp vụ, tài khoản/role, jobs, outbox và published point pointers; PostgreSQL là ứng viên cho DB quan hệ. Không lưu embedding hoặc bản sao đầy đủ search metadata trong SQL. Xem [thiết kế Qdrant](qdrant-design.md).

Benchmark tập trung chọn Qdrant topology, HNSW/search effort, payload indexes, RAM/disk và concurrency; không so sánh để quay lại pgvector. [Tài liệu Qdrant indexing](https://qdrant.tech/documentation/manage-data/indexing/) mô tả vector index và payload index cho bộ lọc.

DB quan hệ ghi intent/outbox trong cùng transaction; worker upsert Qdrant với point revision bất biến rồi công bố pointer có điều kiện sau khi xác minh ghi/đọc. Search phải kiểm tra lifecycle/version/pointer từ DB quan hệ trước trả kết quả. Theo dõi sync lag, xử lý retry và reconciliation vì không có transaction xuyên hai hệ.

HNSW là ứng viên cho truy vấn online. Exact search dùng để tạo baseline ANN recall trên một tập truy vấn có kiểm soát; không bắt buộc chạy exact cho mọi request. Chưa bật quantization hoặc chia shard trước khi benchmark chỉ ra lợi ích cần thiết.

## 3. Dung lượng: tách vector khỏi ảnh

Giả định một vector mỗi ảnh, 768 chiều, float32:

| Hạng mục giả định | 100.000 ảnh | 1.000.000 ảnh |
| --- | --- | --- |
| Vector thô | 307,2 MB ≈ 293 MiB | 3,072 GB ≈ 2,86 GiB |
| Ảnh gốc trung bình 2 MB | 200 GB | 2 TB |
| Thumbnail trung bình 100 KB | 10 GB | 100 GB |

MB/GB/TB trong bảng dùng đơn vị thập phân; MiB/GiB dùng đơn vị nhị phân. Dung lượng trung bình ảnh là giả định để minh họa, cần thay bằng thống kê thực tế.

Chưa tính index, metadata, WAL, backup, replica, model, cache, khoảng trống vận hành và vector của model mới trong lúc reindex. Nếu thêm caption embedding hoặc crop embedding thì số vector mỗi ảnh tăng. Không dùng bảng này để kết luận tổng RAM hay tổng chi phí cloud.

## 4. Nhập dữ liệu lần đầu và cập nhật

Pipeline: đọc nguồn → kiểm tra ảnh → checksum/metadata/thumbnail → batch image embedding → batch upsert → xác nhận ready.

- Lưu manifest nhập với image_id, nguồn, content_version và trạng thái từng ảnh. Có thể tiếp tục từ checkpoint sau khi dừng.
- Dùng batch có giới hạn; không nạp một triệu file hoặc vector vào RAM cùng lúc.
- Tách concurrency tải/giải mã ảnh với batch inference; điều chỉnh theo RAM/VRAM và throughput thực đo.
- Upsert có tính idempotent; công bố trạng thái ready sau khi vector và metadata phù hợp đã sẵn sàng.
- Giới hạn tải batch và ưu tiên tài nguyên cho truy vấn người dùng. Job import không được làm tăng p95 quá mục tiêu.
- Cập nhật/xóa theo content_version; tránh tác vụ cũ ghi đè hoặc khôi phục ảnh đã xóa.

Thời gian nhập tối thiểu có thể ước lượng T = N / throughput end-to-end đo được. Minh họa cho một triệu ảnh: 10 ảnh/giây ≈ 27,8 giờ; 50 ảnh/giây ≈ 5,6 giờ; 100 ảnh/giây ≈ 2,8 giờ. Đây là phép tính theo throughput giả định, không phải tốc độ một model/GPU đã được kiểm chứng. Nếu throughput chưa bao gồm build index, retry và kiểm tra cuối, phải cộng riêng các phần đó.

## 5. Benchmark trước khi chốt công nghệ

Chạy hai mốc dữ liệu 100.000 và 1.000.000 ảnh thật đại diện. Có thể thử ở mốc nhỏ trước; nghiệm thu quy mô cần dữ liệu đủ đa dạng, không nhân bản vector của cùng một ảnh để thay thế.

Ma trận tải đề xuất để khám phá: 1, 5 và 20 QPS; thay bằng tải mục tiêu khi có thông tin. Đây không phải yêu cầu người dùng đã xác nhận. Chạy cả truy vấn không lọc và có lọc, trường hợp tập hợp thỏa bộ lọc khoảng 50%, 10% và 1%, cùng kịch bản search public, detail/download đã login. Collection là filter tùy chọn, không là quyền.

Đo p50/p95/p99, lỗi, ANN Recall@K so với exact trên cùng phạm vi lọc, CPU/RAM/disk I/O, chi phí và thời gian build/rebuild index. Đo thêm khi import đang chạy, khi cache lạnh và khi sau restart. Công bố kết quả warm/cold riêng.

Mục tiêu thử ban đầu: p95 API warm < 2 giây; ANN Recall@100 ≥ 95% so với exact. Đây là mục tiêu đề xuất để thảo luận, không phải kết quả đo hay thay thế đánh giá độ liên quan ngữ nghĩa. Chốt QPS, phần cứng, filters và tập truy vấn đi kèm trước nghiệm thu.

Chọn cấu hình Qdrant đơn giản nhất đạt đồng thời chất lượng, SLO và chi phí trên mốc một triệu ảnh. So sánh các cấu hình trên cùng vector, truy vấn, metric và ngân sách tài nguyên; đo cả số candidate bị catalog loại do chưa công bố/cũ và chi phí recheck DB quan hệ.

## 6. Thay model và phục hồi

Tạo index/collection mới theo model_revision và processor_revision; giữ chỉ mục cũ phục vụ trong lúc tính lại embedding. Chụp mốc dữ liệu rồi bắt kịp cập nhật/xóa phát sinh trong quá trình reindex. Kiểm tra số lượng, content_version, published pointers, truy vấn mẫu và chất lượng trước khi chuyển cấu hình đọc.

Giữ index cũ trong khoảng rollback đã thỏa thuận; dự toán dung lượng cho hai phiên bản. Cần ghi rõ điểm rollback còn an toàn khi dữ liệu tiếp tục cập nhật.

Định nghĩa RPO/RTO, kiểm tra restore metadata và vector, và xác nhận ảnh gốc còn truy cập được sau phục hồi. Một node có thể đủ cho thử nghiệm nhưng không mặc định đáp ứng yêu cầu sẵn sàng cao.

## 7. Đường mở rộng nguồn ảnh bên ngoài

Trong MVP, lưu source_type, source_id, external_id nếu có, license/provenance và ảnh thuộc nguồn nào. Chỉ cần adapter kho riêng hoạt động; chưa triển khai connector giả cho các nguồn chưa chọn.

Sau MVP có hai cách tích hợp:

1. Nhập ảnh được cấp phép vào pipeline hiện tại: dùng chung embedding/index, quản lý lịch đồng bộ và xóa.
2. Gọi API nhà cung cấp lúc tìm kiếm: tạo nhánh retrieval riêng, đặt timeout/quota, xử lý thiếu một nguồn và hợp nhất kết quả.

Score từ các nguồn thường khác thang đo; dùng fusion theo thứ hạng làm baseline rồi đánh giá trên tập truy vấn có nhãn. Giữ nguồn gốc trong kết quả, có khóa định danh kèm namespace nguồn và xử lý ảnh trùng giữa các nguồn. Việc tìm bằng ảnh chỉ áp dụng cho nguồn có khả năng hoặc quyền xử lý phù hợp.
