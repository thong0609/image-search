# Images-search

Dự án tìm ảnh địa danh bằng tiếng Việt. Truy vấn hỗ trợ một địa danh, nhiều địa danh trong cùng câu, và suy luận qua quan hệ địa lý. Ảnh được thu thập từ nguồn web đã cấu hình rồi nhập vào kho; search chỉ dùng nội dung đã kiểm chứng và công bố.

Kiến trúc tìm kiếm: vector + keyword + graph → hợp nhất theo từng mục tiêu → VLM rerank → kết quả có nhóm và nguồn. CLIP/SigLIP 2, graph engine và VLM endpoint cụ thể vẫn cần benchmark.

Đã chốt: FastAPI, PostgreSQL, Qdrant; một người phát triển; local Intel Raptor Lake-P với RAM chia sẻ 16 GB, có thể gọi VLM API ngoài. Schema SQL gồm 9 bảng. Chưa có code hoặc lệnh build/test.

## Tài liệu

- [Kế hoạch MVP địa danh](docs/landmark-mvp-plan.md): phạm vi, crawler, metadata và giả định local.
- [Lộ trình triển khai theo giai đoạn](docs/delivery-plan.md): đầu ra và cổng hoàn tất mỗi phase.
- [PRD](docs/prd.md): yêu cầu và phạm vi sản phẩm.
- [Quyết định](docs/decisions.md): điều đã chốt và câu hỏi còn mở.
- [Thiết kế hệ thống](docs/system-design.md) và [API](docs/api-contract.md).
- [Mô hình dữ liệu 9 bảng](docs/data-model.md), [Qdrant](docs/qdrant-design.md), [pipeline nhập ảnh](docs/ingestion-design.md), [graph/VLM](docs/graph-reranking-design.md), [auth](docs/auth-design.md) và [vận hành](docs/operations.md).

Chưa có dataset, benchmark, crawler hay model chạy thực tế.
