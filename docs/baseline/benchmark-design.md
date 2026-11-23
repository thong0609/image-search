# Bộ benchmark baseline

## Trạng thái

Baseline v2 đã chốt code và chạy đủ 400 câu với vector, keyword và RRF chuẩn 1:1.
Bộ nhãn dùng đánh giá là ứng viên đã làm sạch; chưa được duyệt độc lập.
[Kết quả v2](baseline-v2-results.md) lưu số liệu và giới hạn của phép đo.

## Dữ liệu và nhóm câu hỏi

| Bộ | Phạm vi |
|---|---|
| V1 | 58 câu tổng hợp, giữ để so sánh lịch sử |
| V2 | 400 câu, 323 họ ý định, nguồn bằng chứng phủ 183 entity |
| V2 reviewed | Tập con 32 single đã xem ảnh và 12 multi-target ghép từ single |

V2 có 208 single, 138 multi-target, 54 multi-hop tạm gán.
356 câu có nhãn dương được chấm: 184 single, 124 multi-target, 48 multi-hop.
42 câu chưa xác định đáp án vẫn truy vấn nhưng không chấm; 2 âm catalog báo riêng.

Canonical và robustness báo riêng; các biến thể cùng họ giữ cùng split và đáp án.
24 câu thị giác toàn kho được báo riêng với split `unassigned`, không ép đáp án
vào một phía dev/test. Corpus/test đã được xem, không gọi là holdout độc lập.

## Nhãn và cách chấm

- Nhãn ảnh từ CSV không tự chứng minh mọi điều kiện trong câu hỏi được sinh thêm.
- Đã cách ly 20 ảnh có nguồn địa điểm chưa đáng tin, tác động 52 câu, loại 65 lượt
  ảnh khỏi mục tiêu theo địa điểm. 11 câu thiếu bằng chứng chuyển chưa xác định.
- Không hạ số ảnh yêu cầu, bỏ mục tiêu hoặc coi ảnh cách ly là nhãn âm.
- Câu toàn kho có thể giữ ảnh chưa rõ địa điểm nếu nội dung thị giác còn phù hợp.
- Known Recall/nDCG chỉ đo đáp án đúng đã biết. Ảnh chưa gán nhãn không mặc nhiên sai;
  chưa báo precision vì chưa duyệt đủ top-K.
- Lấy trung bình theo họ ý định trong từng nhóm, báo đủ mọi mục tiêu@10 và độ trễ.
- Multi-hop hiện đo tìm ảnh đích; chưa xác minh bridge cần thiết nên không kết luận
  khả năng suy luận. Câu sinh từ metadata có thể có lợi cho BM25.

Muốn nâng chất lượng nhãn: xem ảnh, kiểm tra địa điểm/điều kiện, pool thêm đáp án,
kiểm chứng bridge và distractor, chốt split rồi review độc lập. Không chọn hoặc
sửa câu theo việc một phương pháp trả đúng/sai.

## File và lệnh hiện dùng

Dữ liệu/model/ảnh/index trong `var/` được giữ local, ngoài Git.

| Đường dẫn | Nội dung |
|---|---|
| `var/benchmark-v1/` | Nhãn và báo cáo v1 |
| `var/benchmark-v2/` | `queries.jsonl`, `answers.jsonl`, `review.html`, manifest, change log và provenance |
| `var/evaluation-v2-all/` | Báo cáo chính `comparison.md`, `recall-latency.md`, trang ảnh `index.html` |
| `var/benchmark-v2-reviewed/` | Manifest, quyết định duyệt ảnh và tập con reviewed |
| `var/evaluation-v2-reviewed/` | Kết quả tập con reviewed |
| `var/gold-review-v2/visual-items.json` | Danh sách ảnh phục vụ kiểm tra hash tập reviewed |

Chạy từ repository root sau khi đã có artifact local tương ứng:

```bash
.venv/bin/python scripts/review_benchmark_v2.py
HF_HUB_OFFLINE=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/evaluate_all_v2.py
.venv/bin/python scripts/summarize_all_v2.py
```

Script đánh giá từ chối ghi đè kết quả đã tồn tại. Chạy lại cần phiên bản output mới.
Manifest chốt hash đầu vào; không sửa file đã chốt để tái sử dụng kết quả cũ.
`verification.json` xác nhận đã chấm lại 1.068 dòng điểm, đủ 1.200 dự đoán,
3.600 lượt đo và 9 trang ảnh.

Snapshot `before-*`, contact sheet và script sửa nhãn lịch sử đã được dọn.
Lịch sử xử lý vẫn có trong change log/provenance local và Git commit `f8958e4`.
Giữ ảnh gốc, model và index để tiếp tục tìm kiếm và đánh giá.
