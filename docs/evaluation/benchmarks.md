# Bộ benchmark

Dữ liệu, ảnh, model và artifact ở `var/`, ngoài Git. Nhãn là ứng viên, chưa duyệt độc lập.

| Bộ | Phạm vi | Trạng thái | Đường dẫn |
|---|---|---|---|
| v1 | 58 câu (29 dev, 29 test) | Lịch sử, bắt hồi quy | `var/benchmark-v1/` |
| v2 | 400 câu, 323 họ ý định: 208 single, 138 multi-target, 54 multi-hop | Test đã bị tune theo lỗi; bắt hồi quy | `var/benchmark-v2/` |
| v3 | 24 multi-hop dương, 8 câu về nơi không có trong kho | Đã dùng để chọn cách ghép danh sách; nay là dev | `var/multihop-v3/` |
| Fixture planner | 60 câu tổng hợp | Test planner | `tests/fixtures/planner-cases.jsonl` |
| Cặp scope | 32 câu: 16 cặp multi-hop/single gần giống | Test planner | `tests/fixtures/planner-scope-cases.jsonl` |

**Chưa có holdout độc lập.** Cần bộ mới, được người khác duyệt, trước khi kết luận chất lượng.

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
