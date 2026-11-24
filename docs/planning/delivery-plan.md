# Trạng thái và hướng triển khai

## Đã hoàn thành

- Scaffold FastAPI/PostgreSQL/Qdrant, migration và frontend Next.js.
- Baseline v1/v2: đọc CSV, tải ảnh, vector SigLIP2, keyword BM25, RRF chuẩn 1:1.
- Chạy đủ 400 câu v2 theo ba loại single/multi-target/multi-hop, có báo cáo chất lượng,
  độ trễ và trang xem ảnh kết quả của từng phương pháp.
- Dọn artifact trung gian và tổ chức lại tài liệu.

Nguồn hiện tại là CSV đã duyệt; corpus benchmark có 1.886 ảnh.
Mốc baseline hoàn thành không đồng nghĩa sản phẩm/API nghiệp vụ đã hoàn thành.
Xem [kết quả baseline](../baseline/baseline-v2-results.md) và
[giới hạn nhãn benchmark](../baseline/benchmark-design.md).

## Hạng mục tiếp theo để lựa chọn

| Hạng mục | Đầu ra cần có | Cách kiểm tra |
|---|---|---|
| API tìm kiếm | Tích hợp baseline vào API với query/filters, lỗi rõ ràng | Contract và test query hợp lệ/rỗng, lỗi dịch vụ |
| Giao diện tìm ảnh | Search bar, grid, nguồn ảnh, loading/rỗng/lỗi | Chạy với API thật, desktop/mobile |
| Multi-target | Tách yêu cầu và trả nhóm theo từng mục tiêu | Mỗi nhóm đủ số lượng, không bù ảnh giữa nhóm |
| Graph/multi-hop | Quan hệ có bằng chứng và phiên bản | Duyệt facts, bridge/distractor và ablation |
| VLM rerank | Chấm shortlist qua adapter có timeout/budget | So chất lượng và độ trễ với baseline |
| Hoàn thiện benchmark | Query thật, nhãn độc lập, pool đáp án | Chốt phiên bản mới và đánh giá lại cùng cấu hình |

Đây là danh sách hạng mục đề xuất, chưa tự chọn bước tiếp theo hoặc nhà cung cấp.
Không còn kế hoạch thu thập Commons/Wikidata hay profile chỉ dành cho địa danh.
Dùng dataset hiện có để phát triển và đo trước khi mở rộng nguồn hoặc quy mô.

## Tài liệu liên quan

- [PRD](prd.md): yêu cầu sản phẩm.
- [Quyết định](decisions.md): lựa chọn còn hiệu lực và mục đã thay thế.
- [Thiết kế hệ thống](../design/system-design.md): ranh giới thành phần.
- [Frontend](../../frontend/README.md): toolchain và lệnh kiểm tra.
