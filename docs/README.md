# Tài liệu dự án

Bộ tài liệu này mô tả dự án tìm ảnh địa danh bằng tiếng Việt. Đã có scaffold phase 0 và migration; nghiệp vụ tìm kiếm, dataset, crawler và benchmark chưa được triển khai. Cách cài/chạy/kiểm tra hiện hành ở [README dự án](../README.md).

## Đọc theo nhu cầu

| Tài liệu | Nội dung |
|---|---|
| [Kế hoạch MVP địa danh](landmark-mvp-plan.md) | Phạm vi, crawler, metadata, query modes, frontend và giả định local |
| [PRD](prd.md) | Yêu cầu sản phẩm và tiêu chí chấp nhận |
| [Lộ trình triển khai](delivery-plan.md) | Các giai đoạn BE/FE, đầu ra và điều kiện hoàn tất |
| [Quyết định](decisions.md) | Lựa chọn đã chốt, đề xuất và việc còn mở |
| [Thiết kế hệ thống](system-design.md) | Thành phần và luồng tìm kiếm/nhập ảnh |
| [Hợp đồng API](api-contract.md) | Request, response, phân trang, lỗi và quyền |
| [Mô hình dữ liệu](data-model.md) | Schema SQL 9 bảng |
| [Qdrant](qdrant-design.md) | Vector/payload và đồng bộ catalog |
| [Pipeline nhập ảnh](ingestion-design.md) | Import, crawl artifact, retry, cập nhật và xóa |
| [Graph và VLM](graph-reranking-design.md) | Entity/relations, fusion, rerank và consistency |
| [Auth](auth-design.md) | Access/refresh, login/logout, roles và media |
| [Vận hành](operations.md) | Local/deploy, quan sát, backup, maintenance và khôi phục |

PRD là nguồn chuẩn cho phạm vi; API contract là nguồn chuẩn cho giao tiếp; data model là nguồn chuẩn cho 9 bảng. Cập nhật cả quyết định và tài liệu liên quan khi phạm vi thay đổi. Lệnh chạy/build/test backend đã có trong README dự án; frontend scaffold cũng có lệnh dev/lint/typecheck/build trong README.
