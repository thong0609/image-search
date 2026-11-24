# Lộ trình triển khai

Ưu tiên thử nghiệm chất lượng tìm kiếm trên dataset hiện có; tích hợp website sau cùng.
Mục tiêu cuối: **p90 toàn pipeline < 300 ms**. Đánh giá chất lượng và độ trễ ở mỗi bước.

| Bước | Công việc chính | Trạng thái |
|---|---|---|
| 1 | Chuẩn bị dataset, bộ câu hỏi và baseline đối chứng | Đã có v1/v2; nhãn còn giới hạn |
| 2 | Planner: phân loại câu, tách mục tiêu và dependency | Đã thử OpenAI prompt v2; tạm giữ nguyên |
| 3 | Embedding: chọn/thử model ảnh–văn bản, mã hóa ảnh và lập index | Đã kiểm tra/tái sử dụng index SigLIP2; tạo vector theo từng bước planner và đo độ trễ |
| 4 | Retrieval: mã hóa query của từng bước, tìm vector/keyword và kết hợp hybrid | Đã có vector/BM25/RRF theo mục tiêu, đã chạy thử query dev thật |
| 5 | Thực thi kế hoạch: ghép retrieval theo từng mục tiêu, entity và bridge cho multi-hop | Đã có đường bằng chứng theo entity, tách giả thuyết và kiểm tra metadata; chưa xác minh thị giác |
| 6 | Reranking: sắp xếp lại shortlist bằng model phù hợp | Chưa triển khai |
| 7 | Đánh giá toàn pipeline, chọn cấu hình và tối ưu chất lượng/độ trễ | Sau khi có luồng hoàn chỉnh |
| 8 | Tích hợp API/backend và frontend, kiểm thử luồng người dùng | Sau cùng |

Embedding ảnh được tạo offline; embedding query được tạo khi tìm kiếm.
Baseline hiện có index cho 1.886 ảnh, không cần mã hóa lại nếu model/tiền xử lý/corpus không đổi.
Planner OpenAI hiện chưa đạt ngân sách độ trễ; xử lý ở bước tối ưu, chưa coi là cấu hình online cuối.

Tham khảo: [kết quả baseline](../baseline/baseline-v2-results.md),
[planner](../design/planner.md), [thiết kế hệ thống](../design/system-design.md).
