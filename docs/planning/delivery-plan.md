# Lộ trình triển khai

Ưu tiên thử nghiệm chất lượng tìm kiếm trên dataset hiện có; tích hợp website sau cùng.
Mục tiêu cuối: **p90 toàn pipeline < 300 ms**. Đánh giá chất lượng và độ trễ ở mỗi bước.

| Bước | Công việc chính | Trạng thái |
|---|---|---|
| 1 | Chuẩn bị dataset, bộ câu hỏi và baseline đối chứng | Đã có v1/v2; nhãn còn giới hạn |
| 2 | Planner: phân loại câu, tách mục tiêu và dependency | Đã thử OpenAI prompt v2; tạm giữ nguyên |
| 3 | Embedding: chọn/thử model ảnh–văn bản, mã hóa ảnh và lập index | Đã kiểm tra/tái sử dụng index SigLIP2; tạo vector theo từng bước planner và đo độ trễ |
| 4 | Retrieval: mã hóa query của từng bước, tìm vector/keyword và kết hợp hybrid | Đã có vector/BM25/RRF theo mục tiêu, đã chạy thử query dev thật |
| 5 | Thực thi kế hoạch: graph quan hệ entity cho multi-hop, retrieval theo từng mục tiêu | Graph 319 entity/301 quan hệ đã nhập từ extraction Codex trực tiếp; planner v3 chưa benchmark mới |
| 6 | Reranking: sắp xếp lại shortlist bằng model phù hợp | Chưa triển khai |
| 7 | Đánh giá toàn pipeline, chọn cấu hình và tối ưu chất lượng/độ trễ | Đã đo luồng không rerank trên 400 câu; multi-hop và SLO chưa đạt |
| 8 | Tích hợp API/backend và frontend, kiểm thử luồng người dùng | Sau cùng |

Embedding ảnh được tạo offline và lưu trực tiếp vào Qdrant; embedding query chỉ ở RAM khi tìm kiếm.
Metadata model/index và metadata tìm kiếm nằm trong Qdrant; lọc entity trực tiếp theo payload.
BM25 dựng trong RAM từ Qdrant; runtime không đọc metadata nguồn local.
Không lưu file vector hoặc thêm backend khác.
Baseline hiện có index cho 1.886 ảnh, không cần mã hóa lại nếu model/tiền xử lý/corpus không đổi.
Planner OpenAI hiện chưa đạt ngân sách độ trễ; xử lý ở bước tối ưu, chưa coi là cấu hình online cuối.

Tham khảo: [kết quả baseline](../baseline/baseline-v2-results.md),
[planner](../design/planner.md), [thiết kế hệ thống](../design/system-design.md).


Plan graph hiện tại nằm ở [graph search, mục 10](../design/graph-reranking-design.md#10-plan-graph-quan-hệ-từ-metadata-yes).
Tin metadata `yes`, bỏ node nguồn, ưu tiên quan hệ entity–entity. Mục 8–9 mô tả
graph cũ chưa được migration. Graph mới đã nhập không dùng API trích xuất; benchmark planner v3 còn chờ.
