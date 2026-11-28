# Lộ trình triển khai

Ưu tiên thử nghiệm chất lượng tìm kiếm trên dataset hiện có; tích hợp website sau cùng.
Mục tiêu cuối: **p90 toàn pipeline < 300 ms**. Đánh giá chất lượng và độ trễ ở mỗi bước.

| Bước | Công việc chính | Trạng thái |
|---|---|---|
| 1 | Dataset, bộ câu hỏi và baseline đối chứng | Đã có v1/v2/v3; chưa có holdout độc lập |
| 2 | Planner: tách mục tiêu, nơi chứa và điều kiện | Đã có (prompt v6, code suy ra route); độ trễ chưa đạt |
| 3 | Embedding và index ảnh | Đã có SigLIP2 trong Qdrant |
| 4 | Retrieval vector/keyword/hybrid | Đã có, RRF 1:1 |
| 5 | Thực thi kế hoạch: graph, visual bridge, danh sách kết quả | Đã có; một số quan hệ chưa hỗ trợ |
| 6 | Reranking | Chưa triển khai |
| 7 | Đánh giá, tối ưu chất lượng và độ trễ | Đang làm; SLO chưa đạt |
| 8 | API/website, đăng nhập | Đã có tìm kiếm/filter/phân trang, đăng nhập, tài khoản và gỡ ảnh; đã có nhập CSV, batch worker và công bố snapshot mới |

Chi tiết: [luồng tìm kiếm](../design/search-pipeline.md), [kết quả](../evaluation/results.md),
[quyết định](decisions.md).

Triển khai website ngày 26/11/2026: [hướng dẫn và phạm vi còn lại](../guides/website.md).

## Graph offline mở — cập nhật 28/11/2026

Luồng đã duyệt: CSV approve=yes → nhóm entity_id/chia batch → gpt-6-luna qua
ShopAIKey trả JSON records/triples → kiểm tra cấu trúc → chuẩn hóa entity/relationship
→ Neo4j và registry vector Qdrant → kiểm tra phiên bản mới trước khi kích hoạt.
System prompt do người dùng biên soạn nằm tại
`src/image_search/graph/offline/prompt.txt`; schema chỉ ràng buộc cấu trúc, không khóa
loại entity hoặc relationship. Không gửi toàn bộ graph cho model.

Mỗi batch có hash input + prompt + model + schema, lưu request/output/usage, retry hữu hạn
và giới hạn request mỗi lượt. Checkpoint hợp lệ được dùng lại. Không tự cắt metadata.
Mọi record phải xuất hiện đúng một lần, không self-loop/triple trùng hoặc relationship
sai UPPER_SNAKE_CASE. Cần kiểm tra ngữ nghĩa riêng; JSON hợp lệ không bảo đảm đúng sự thật.

Chuẩn hóa dự kiến: ID nguồn → tên/alias đã xác nhận → RapidFuzz và vector tìm ứng viên
→ LLM phân biệt với tập ứng viên nhỏ. Entity có ID, tên, alias, loại, phạm vi/chủ sở hữu;
relationship có ID, tên, alias, định nghĩa, hướng. Không tự merge theo top-1.
Không tạo SourceRecord/SourcePage/SourceLabel node; provenance đặt trên entity/cạnh và
metadata ảnh nằm ở Qdrant. Chỉ dùng metadata, không xác minh nguồn ngoài.

Trạng thái code: đã có prepare/extract/build/stage, checkpoint, validation, registry ID,
RapidFuzz/vector candidates, Luna phân biệt theo ngữ cảnh, checkpoint quyết định
merge/định nghĩa và staging Neo4j/Qdrant riêng.
Vector registry tạm tái sử dụng SigLIP2 đã pin của index ảnh; chưa chứng minh phù hợp cho
chuẩn hóa ngữ nghĩa. Quyết định Luna được lưu thành file, build có thể nhận file đã sửa
để kiểm duyệt lại. Chưa có cutover online, xóa incremental hoặc
job admin website cho luồng mới. Stage dùng snapshot đầy đủ bất biến; snapshot mới bỏ các
record đã xóa mà không sửa phiên bản cũ. Các hạng mục này phải hoàn tất và đo trước activation.
Không đổi hybrid mặc định hai nhánh. Xem [cách chạy](../guides/offline-graph.md).

Lượt thử 28/11: thêm extract-many 16 worker, namespaced record IDs cho nhiều CSV,
tracking HTML/JSON/JSONL, exponential retry và circuit breaker sau 10 lỗi API liên tiếp.
Đã chạy 5 CSV từ chiều 18/11 tới sáng 21/11: 14.083 record / 5.840 batch dự kiến.
Run đã pause: 16 request (12 HTTP 503, 4 thành công), lưu 4 record/14 triple;
chưa hoàn tất extraction hoặc normalize/stage. Không tự resume sau circuit breaker.
