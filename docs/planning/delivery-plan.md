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
| 8 | API/website production, đăng nhập | Chưa triển khai; có playground local |

Chi tiết: [luồng tìm kiếm](../design/search-pipeline.md), [kết quả](../evaluation/results.md),
[quyết định](decisions.md).
