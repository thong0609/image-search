# Bộ benchmark

Dữ liệu, ảnh, model và artifact ở `var/`, ngoài Git. Nhãn là ứng viên, chưa duyệt độc lập.

| Bộ | Phạm vi | Trạng thái | Đường dẫn |
|---|---|---|---|
| v1 | 58 câu (29 dev, 29 test) | Lịch sử, bắt hồi quy | `var/benchmark-v1/` |
| v2 | 400 câu, 323 họ ý định: 208 single, 138 multi-target, 54 multi-hop | Test đã bị tune theo lỗi; bắt hồi quy | `var/benchmark-v2/` |
| v2 completed v1 | 400 câu: 230 dev, 170 test; cả hai split đủ ba loại | Sửa 24 câu toàn kho, thay 42 câu chưa chốt; nhãn mới đối chiếu metadata approve=yes | `var/benchmark-v2-completed-v1/` |
| v3 | 24 multi-hop dương, 8 câu về nơi không có trong kho | Đã dùng để chọn cách ghép danh sách; nay là dev | `var/multihop-v3/` |
| Fixture planner | 60 câu tổng hợp | Test planner | `tests/fixtures/planner-cases.jsonl` |
| Cặp scope | 32 câu: 16 cặp multi-hop/single gần giống | Test planner | `tests/fixtures/planner-scope-cases.jsonl` |

**Chưa có holdout độc lập.** Cần bộ mới, được người khác duyệt, trước khi kết luận chất lượng.

### Bản hoàn thiện v2

| Split | Single | Multi-target | Multi-hop | Tổng |
|---|---:|---:|---:|---:|
| dev | 125 | 74 | 31 | 230 |
| test | 83 | 64 | 23 | 170 |

`queries.jsonl` và `answers.jsonl` là cặp dữ liệu mới. `changes.jsonl` lưu trước/sau và lý do
cho 66 câu thay đổi (55 unassigned và 11 câu đã có split nhưng đáp án unresolved).
`review.md` liệt kê metadata làm bằng chứng; `audit.json` giữ thống kê và hash.
398 câu dương, 2 câu âm kế thừa, không còn answerable=null hay split=unassigned.

24 câu thị giác toàn kho nằm ở dev, có thể dùng ảnh thuộc entity xuất hiện trong test;
không tuyên bố tách biệt entity/ảnh giữa hai split. Các câu thay mới có tên dùng entity cùng split
với nhãn cũ. Bằng chứng là metadata được tin cậy, chưa duyệt ảnh độc lập. 334 câu giữ nguyên
nhãn cũ, không được tự nâng thành nhãn đã duyệt. Chưa chạy planner/retrieval trên bản mới;
kết quả v2 cũ không áp dụng cho bản này. Không dùng kết quả retrieval để chọn câu hay đáp án.

## Nhãn và cách chấm

- Chỉ chấm đáp án đã biết (known positives); ảnh chưa gán nhãn không mặc nhiên sai, nên không báo
  precision. v2 chấm 356 câu dương, 42 câu chưa rõ đáp án không chấm.
- Lấy trung bình theo họ ý định trong từng split/loại/nhóm; canonical và robustness báo riêng.
- v2 đã cách ly 20 ảnh có nguồn địa điểm chưa đáng tin; không hạ yêu cầu hoặc coi ảnh cách ly là âm.
- Multi-hop v2 sinh từ metadata nên thuận lợi cho BM25. q0300/q0320 có bridge và đích cùng đối tượng,
  nhãn chờ chốt.
- v3 viết từ ảnh, không xem caption, trên entity chưa dùng trong multi-hop v2; hash ở `frozen.json`.
- Không chọn hoặc sửa câu theo việc một phương pháp trả đúng/sai. Mỗi lần đổi corpus/nhãn dùng phiên
  bản mới. Không tune theo tập test.

Công cụ chấm: [hướng dẫn tìm kiếm](../guides/search.md#đánh-giá).
