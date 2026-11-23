# Bộ câu hỏi benchmark v2

V2 là draft 400 câu / 323 họ ý định, chưa freeze và chưa có điểm benchmark.
Sau sửa: 208 single, 138 multi-target, 54 câu còn mang loại multi-hop tạm thời.
Nguồn bằng chứng vẫn phủ 183 entity. Tất cả câu còn `reviewed=false`.

## Các lỗi đã sửa

- Câu theo entity yêu cầu “vài tấm” được sửa thành “một ảnh”, khớp `required=1`.
  Câu toàn kho có yêu cầu số lượng tương tự cũng được sửa.
- Chuẩn hóa hai tên nguồn không tự nhiên: Ga Hà Nội trên đường Lê Duẩn và
  Nghĩa trang Liệt sĩ Quốc gia Vị Xuyên, Hà Giang. Không sửa metadata nguồn.
- `v2-q0136`: pool theo “đường ray HOẶC sân ga”, bổ sung cả `csv-175`.
  Ảnh này đã được assistant xem và xác nhận có sân ga/đường ray; chưa là review độc lập.
- 24 câu nhiều điều kiện: 7 mặt tiền/bên trong, 4 ngày/đêm, 7 toàn cảnh/cận cảnh,
  6 phối cảnh/thi công. Hai mục tiêu không dùng chung image ID.
- 48 biến thể chia đều 24 dev / 24 test; mỗi loại có 8 câu trong mỗi split.
  Gồm 24 không dấu, 16 từ đồng nghĩa, 6 lỗi gõ tên và 2 viết tắt.
  Mỗi biến thể có `canonical_query_id`, cùng split và đáp án với câu gốc.
- `v2-q0316` và `v2-q0318` bỏ bridge dư thừa, đổi thành single.
- Tách câu toàn kho, câu cần làm rõ, thiếu ngữ cảnh, thiếu thông tin và chưa biết
  đáp án thành các `evaluation_suite` riêng. Không coi unknown là câu âm.
- Thêm `family_weight`: mỗi họ ý định có tổng trọng số 1 trong từng suite/report_group.
  Canonical và robustness báo riêng. Thêm trần Known-Recall@10 cho từng mục tiêu.

Dev/test tạm gán hiện là 178/167. Có 55 câu chưa gán split: 24 câu toàn kho
thuộc suite riêng và 31 câu chưa xác định đáp án từ bản trước. Sau làm sạch nhãn,
thêm 11 câu chuyển chưa xác định nhưng giữ split dự kiến để truy vết họ ý định. Không ép chúng vào dev/test
hoặc bỏ đáp án đúng chỉ để tránh giao nhau giữa các nhóm.

## Phần còn cần duyệt

1. Xem toàn bộ ảnh ứng viên và pool thêm ảnh đúng từ vector/keyword/hybrid/catalog.
   Caption chỉ tạo ứng viên, không chứng minh nhãn đầy đủ.
2. Với câu thị giác, người viết độc lập cần xem ảnh trước khi đọc caption rồi viết lại câu.
   Các câu hiện tại vẫn tổng hợp từ metadata; chưa loại hết thiên lệch có lợi cho BM25.
3. Các câu thuộc `relational_review` chưa được dùng để kết luận khả năng suy luận.
   Cần kiểm tra bridge duy nhất, chạy ablation bỏ bridge và tìm distractor.
   Trường hợp Hồng Cúm `v2-q0307` vẫn chưa xác minh danh tính nguồn.
4. Hai câu âm v1 chỉ là vắng tên trong catalog. Chưa có âm thị giác tự nhiên được duyệt.
5. Chốt nhãn, split, review độc lập rồi mới freeze. Corpus/test đã được xem trước,
   không gọi đây là test holdout chưa từng tiếp xúc.

`evaluation-policy.json` quy định báo riêng từng suite, trung bình theo họ ý định,
ưu tiên Known-nDCG và đủ số ảnh yêu cầu. Recall chỉ là nhãn đã biết, cần đọc cùng
trần Recall. Precision cần duyệt đủ top-K; không coi ảnh chưa xét là sai.
**Policy này chưa được triển khai trong evaluator v1**; không dùng evaluator đó
để gộp toàn bộ v2 thành một điểm. Gate freeze vẫn từ chối draft.

## File và cách tái lập

Dữ liệu nằm ngoài Git trong `var/benchmark-v2/`:

- `review.html`: xem câu, ứng viên, suite và việc cần duyệt.
- `queries.jsonl`, `answers.jsonl`: câu và nhãn ứng viên.
- `repair-changes.jsonl`: nội dung trước/sau theo ID; một số slot điều kiện và
  robustness đã được thay câu, không dùng ID đơn lẻ để so phiên bản.
- `repair-provenance.json`: hash nguồn/kết quả/script.
- `coverage.json`, `audit.json`: phân bố và kiểm tra.
- `evaluation-policy.json`: quy tắc chấm dự kiến.
- `label-cleanup-notes.md`: các lỗi nhãn đã sửa và giới hạn còn lại.

Hai snapshot `benchmark-v2-before-fixes/` và `benchmark-v2-before-label-cleanup/`
đã được dọn sau khi chốt v2. Lịch sử nhãn trước/sau và hash vẫn nằm trong
`repair-changes.jsonl`, `label-cleanup-changes.jsonl` và các file provenance.
Hai script sửa nhãn cũ cũng đã được dọn vì không còn snapshot đầu vào.
Có thể xem code lịch sử trong commit `f8958e4`.
Không dùng bộ v2 hiện tại làm đầu vào thay thế snapshot cũ.

Tạo lại trang review từ bộ v2 hiện tại:

```bash
.venv/bin/python scripts/review_benchmark_v2.py
```

Generator cũ đã được chặn khi có `repair-provenance.json` để tránh ghi đè nhãn.

## Cập nhật làm sạch nhãn

Đã cách ly 20 ảnh có nguồn địa điểm chưa đáng tin, tác động 52 câu và loại 65 lượt
ảnh khỏi các mục tiêu theo địa điểm. 11 câu chuyển sang chưa xác định, không hạ số
ảnh yêu cầu hoặc bỏ mục tiêu. Hiện có 356 câu ứng viên dương / 42 chưa xác định /
2 âm theo catalog. Tất cả vẫn chưa được review độc lập.

Các câu toàn kho giữ ảnh chưa rõ địa điểm nếu chưa có bằng chứng sai nội dung;
chúng được gắn cờ cần duyệt. Các alias cùng nơi không bị loại chỉ vì khác entity ID.
Trang review hiển thị mọi record nguồn của một ảnh, tránh che mất mâu thuẫn do
chỉ chọn record cuối. `source_record_ids` vẫn là lịch sử nguồn, có cả nguồn cách ly.

Chi tiết ở `var/benchmark-v2/label-cleanup-notes.md`, thay đổi theo câu trong
`label-cleanup-changes.jsonl`. Snapshot trước làm sạch đã được dọn.
Bước sửa cấu trúc cũ hiện bị chặn để không ghi đè nhãn đã làm sạch.

Dùng bộ v2 đã lưu để xem/chấm lại. Code làm sạch cũ nằm trong lịch sử Git.

Không chạy lại bước sửa nhãn trên bộ v2 đã chốt.
Quy tắc này chưa giải quyết ảnh gần trùng khác bytes, metadata sai ở một entity
đơn lẻ, hoặc độ đầy đủ của nhãn thị giác. Chưa có benchmark mới.

## Lần đánh giá trên phần đã duyệt ảnh

Đã chốt `var/benchmark-v2-reviewed/manifest.json`: 32 câu single từ draft,
12 câu multi-target ghép từ single đã duyệt, chia dev/test theo nguồn.
Đã xem 70 ảnh ứng viên: giữ 43 cặp câu/ảnh, loại hoặc để chờ 27 cặp.
Quyết định có trong `visual-decisions.jsonl`, được chốt trước khi chạy retrieval.
Đây là tập tham chiếu do assistant duyệt; chưa phải gold độc lập vì danh tính
địa điểm vẫn dựa CSV và nhãn đúng chưa được tìm đầy đủ. Không đưa các câu multi-hop
chưa kiểm chứng bridge vào phép đo này. Draft 400 câu vẫn được giữ để duyệt tiếp.

Chạy cùng baseline hiện tại, corpus 1.886 ảnh, index SigLIP2 và BM25 hiện có;
RRF chuẩn 1:1, k=60, 100 ứng viên mỗi nhánh. Ba vòng/câu, seed 42, CPU 4 threads,
không tune theo kết quả. Single và multi-target báo riêng vì câu ghép phụ thuộc single.
Kết quả: `var/evaluation-v2-reviewed/comparison.md` và `comparison.json`.
Ở test single, Known-nDCG@10: vector 0.072, keyword 0.769, RRF 0.373.
Đủ cả mục tiêu ở test multi-target: vector 0/6, keyword 3/6, RRF 0/6.

Kiểm tra lại hash, chấm lại mọi dự đoán và số vòng đo đã đạt;
13 unit test cho scorer/keyword/RRF đạt. `verification.json` lưu kết quả kiểm tra.
Script chạy thực tế lưu cùng báo cáo ở `executed-script.py` và có hash trong
`experiment.json`; script repository sau đó chỉ sửa cách xuống dòng để qua lint.

```bash
.venv/bin/python scripts/freeze_reviewed_v2.py
HF_HUB_OFFLINE=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/evaluate_reviewed_v2.py
```

Hai script từ chối ghi đè phiên bản đã tồn tại. Muốn chạy lại phải dùng thư mục
phiên bản mới. Chưa đủ bằng chứng kết luận keyword tốt nhất cho mọi truy vấn người dùng:
câu vẫn được sinh từ metadata mà BM25 truy cập, test/corpus đã được xem,
và tập này chưa có âm hoặc multi-hop đã duyệt độc lập.

## Đánh giá toàn bộ v2 theo cả ba loại câu hỏi

Đã chạy `scripts/evaluate_all_v2.py` trên đủ 400 câu v2 hiện tại với vector,
keyword và RRF chuẩn 1:1 (k=60, 100 ứng viên/nhánh), mỗi câu ba vòng.
356 câu có nhãn dương được chấm: 184 single, 124 multi-target, 48 multi-hop.
42 câu chưa rõ đáp án được tìm kiếm nhưng không chấm; 2 câu âm theo catalog
được báo riêng ở `negative-results.json`. Không sửa nhãn theo kết quả retrieval.

Báo cáo: `var/evaluation-v2-all/comparison.md`, trang xem ảnh:
`var/evaluation-v2-all/index.html`. Có chín trang top-10 theo phương pháp/loại.
Câu gốc và robustness báo riêng, trung bình theo intent_id trong từng nhóm.
Câu toàn kho (`unassigned`) có nhóm riêng. Đây là đánh giá nhãn ứng viên;
multi-hop đo tìm ảnh đích theo nhãn hiện có, chưa chứng minh suy luận qua bridge.

Ở test/canonical, Known-nDCG@10 theo single / multi-target / multi-hop:

- Vector: 0.107 / 0.048 / 0.135.
- Keyword: 0.866 / 0.635 / 0.627.
- RRF 1:1: 0.500 / 0.325 / 0.362.

Đã kiểm tra hash đầu vào/script chạy, chấm lại 1.068 dòng điểm, kiểm tra đủ 1.200
kết quả truy vấn và 3.600 lượt đo, đủ câu trong chín trang ảnh. Kết quả kiểm tra:
`verification.json`. Script tổng hợp: `scripts/summarize_all_v2.py`.
Bản script chạy thực tế lưu tại `executed-script.py`, hash ở `experiment.json`.

## Dọn artifact sau khi chốt v2

Đã xóa contact sheet JPG dùng duyệt thủ công (gold-review-v2, hop-review, review),
file thử model, log retry cũ và bản repair-summary trùng nội dung overview.
Quyết định duyệt ảnh, danh sách image ID, change log, provenance và ảnh gốc vẫn giữ.
`gold-review-v2/visual-items.json` vẫn giữ vì manifest tập reviewed lưu hash của file này.
Không di chuyển các artifact còn lại vì manifest và HTML hiện tham chiếu đường dẫn đó.
Sơ đồ thư mục hiện dùng xem `var/README.md` trên máy local.
