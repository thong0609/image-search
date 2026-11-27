# Kết quả đánh giá

Nhãn và giới hạn của từng bộ ở [benchmark](benchmarks.md). Mọi số là hybrid RRF 1:1 nếu không ghi khác;
một lượt planner mỗi câu. Corpus 1.886 ảnh.

## Pipeline trên v2 completed v1 (400 câu)

Benchmark mới đủ 230 dev / 170 test; chấm 398 câu dương, 2 câu âm báo riêng.
Hybrid vector ảnh + BM25, RRF 1:1, text tắt, list_size=20; 3 vòng sau warmup, seed 42.
Planner v6: 263 lượt gọi mới, 137 kết quả tái sử dụng khớp text/prompt/model/reasoning;
biên dịch lại draft bằng code hiện tại. 263 lượt mới đều hợp lệ; một lỗi plan cũ giữ lại để đo fallback.

| Split / loại | Câu dương | R@10 | nDCG@10 | Đủ mục tiêu@10 |
|---|---:|---:|---:|---:|
| dev / single | 124 | 0,661 | 0,824 | 0,990 |
| dev / multi-target | 74 | 0,572 | 0,562 | 0,953 |
| dev / multi-hop | 31 | 0,870 | 0,726 | 0,870 |
| test / single | 82 | 0,800 | 0,882 | 0,964 |
| test / multi-target | 64 | 0,622 | 0,586 | 0,944 |
| test / multi-hop | 23 | 0,956 | 0,810 | 0,956 |

Mỗi bảng tổng theo loại lấy trung bình theo intent trên canonical + robustness, nên không phải
trung bình tỷ lệ câu hay trung bình hai hàng canonical/robustness trong báo cáo riêng. Multi-target
ghép các nhóm round-robin rồi chấm top 10 chung. Nhóm thị giác toàn kho dev báo riêng:
24 câu, R@10=0,230, nDCG@10=0,661, có ảnh đúng trong top 10 ở 23/24 câu, top 20 ở 24/24.

Embedding + retrieval: p50 **220 ms**, p90 **649 ms**, p95 **856 ms**; không gồm startup/planner.
Planner mới, 4 request đồng thời: p50 7,46 s, p90 10,93 s; không coi đây là độ trễ tuần tự đầu cuối.
Không có đơn giá trong cấu hình nên không báo chi phí ước tính.

Loại kế hoạch khớp nhãn: single 206/208, multi-target 138/138, multi-hop 44/54
(9 thành single, 1 lỗi cấu trúc). Đây chỉ là route, chưa chấm toàn bộ nội dung plan.
Cả hai câu âm đều nhận 20 ảnh fallback; chế độ danh sách chưa từ chối khi không có tên trong kho.

Artifact: `var/evaluation-v2-completed-v1/report.md`, `summary.json`, `query-scores.jsonl`,
`route-mismatches.jsonl`, `plans.jsonl`, `retrieval/hybrid/results.html`.
Đã kiểm tra đủ 400 prediction, 1.200 timing và hash input/code không thay đổi.
Nhãn đã biết chưa đầy đủ, 334 câu kế thừa nhãn cũ; nhãn mới dựa trên metadata approve=yes.
Có ảnh chung giữa dev/test, chưa có kiểm chứng độc lập. Không so trực tiếp với v2 cũ vì tập câu khác.
Không sửa code, prompt hay nhãn theo kết quả lần chạy.

## Baseline tìm cả câu, v2 test canonical

| Loại (số câu) | Phương pháp | Recall@10 | Đủ mọi mục tiêu@10 | p50 / p90 ms |
|---|---|---:|---:|---:|
| single (69) | vector | 0,115 | 0,276 | 106 / 130 |
| | keyword | 0,800 | 0,966 | 1,6 / 1,9 |
| | hybrid | 0,587 | 0,793 | 98 / 113 |
| multi-target (56) | vector | 0,022 | 0,000 | 106 / 126 |
| | keyword | 0,632 | 0,759 | 2,2 / 2,5 |
| | hybrid | 0,352 | 0,343 | 99 / 112 |
| multi-hop (15) | vector | 0,333 | 0,333 | 108 / 146 |
| | keyword | 0,933 | 0,933 | 2,5 / 2,8 |
| | hybrid | 0,600 | 0,600 | 98 / 110 |

Bảng đầy đủ theo split và nhóm: `var/evaluation-v2-all/comparison.md`.

## Pipeline, plan v6 đã lưu (`var/list-v1/`, 25/11/2026)

`strict` chỉ trả kết quả đúng kế hoạch; `danh sách` là chế độ mặc định.

| Nhóm | Strict R@10 | Danh sách R@10 |
|---|---:|---:|
| v1 test: single (12) / multi-target (10) / multi-hop (6) | 0,757 / 0,497 / 1,000 | 0,757 / 0,602 / 0,833 |
| v2 test mẫu: single (18) / multi-target (12) | 0,792 / 0,506 | 0,792 / 0,727 |
| v2 test: multi-hop (23) | 1,000 | 0,913 (top 20: 23/23) |
| v2 dev mẫu: single (29) / multi-target (18) / multi-hop (19) | 0,693 / 0,339 / 0,842 | 0,772 / 0,593 / 0,947 |
| v3 multi-hop (24): có đích top 10 | 15/24 | 19/24 |
| v3 multi-hop (24): đích ở hạng 1 | 11/24 | 11/24 |

Một phần mức tăng multi-target là do không còn cắt theo số ảnh. v2 test multi-hop chỉ đạt 0,261 trước
khi sửa theo lỗi của chính tập này; v3 phản ánh chất lượng sát hơn.

v3 trước khi có chế độ danh sách, so với tìm cả câu: ảnh đầu đúng nơi 17/24 so với 13/24, đích ở hạng 1
11/24 so với 6/24, đích trong top 10 15/24 so với 17/24.

Cách ghép đã thử trên v3 (đích@1 / đích@10): xen kẽ nơi đầu với cả câu 11/19 (đang dùng); RRF hai danh
sách 7/16; xen kẽ ba nơi đầu 11/18; ba nơi đầu và cả câu 11/19.

## A/B nhánh vector text SigLIP2 (25/11/2026)

Trạng thái: **đang xem xét**, lưu trên branch `experiment/text-retrieval-review`.
Cấu hình đang sử dụng vẫn là hybrid hai nhánh vector ảnh + BM25; nhánh text tắt mặc định.

Đã chạy lại 184 plan trong `var/list-v1/v{1,2,3}.jsonl`, mỗi cấu hình 3 vòng sau warmup,
seed 42; không gọi OpenAI. Trong từng cặp, plan, vector ảnh, metadata, graph và mọi cấu hình khác
đều khớp. Tắt: ảnh + BM25 (RRF 1:1). Bật: thêm text `entity_name. mo_ta` (RRF 1:1:1).
Giữ `bridge_margin=0.1`; baseline tìm cả câu vẫn dùng hai nhánh.

| Nhóm | Câu chấm | R@10 tắt → bật | nDCG@10 tắt → bật |
|---|---:|---:|---:|
| v1 test multi-hop | 6 | 0,833 → 1,000 | 0,750 → 0,725 |
| v2 dev multi-hop canonical | 17 | 0,941 → 0,824 | 0,769 → 0,671 |
| v2 dev multi-target canonical | 18 | 0,593 → 0,566 | 0,568 → 0,554 |
| v2 test multi-hop canonical | 15 | 0,933 → 1,000 | 0,792 → 0,745 |
| v2 test multi-target canonical | 12 | 0,727 → 0,683 | 0,666 → 0,642 |
| v2 test single canonical | 18 | 0,792 → 0,794 | 0,894 → 0,931 |
| v3 holdout multi-hop canonical | 24 | 0,729 → 0,729 | 0,577 → 0,553 |

Trên v3, đích ở hạng 1 giảm **11/24 → 8/24**, đích trong top 10 giảm **19/24 → 18/24**.
R@10 tính tỷ lệ ảnh đúng đã biết nên có thể không đổi dù số câu có đích trong top 10 giảm.

| Bộ | p50 tắt → bật (ms) | p90 tắt → bật (ms) |
|---|---:|---:|
| v1 | 222,5 → 219,9 | 281,7 → 273,6 |
| v2 | 219,6 → 233,0 | 315,5 → 319,3 |
| v3 | 233,0 → 251,0 | 289,4 → 323,0 |

Độ trễ gồm embedding + retrieval, không gồm planner/startup. Các lượt chạy tuần tự nên chênh lệch
nhỏ không chứng minh cải thiện tốc độ. Chất lượng trung bình theo intent trong từng nhóm, chỉ chấm
câu answerable=true; nhãn không bao phủ mọi ảnh đúng. Các bộ đã được dùng để phát triển, kết quả
chưa chứng minh khả năng tổng quát trên dữ liệu mới.

**Quyết định: giữ `IMAGE_SEARCH_RETRIEVAL_TEXT_VECTORS=false` mặc định.** Nhánh đã triển khai,
có thể bật để thử tiếp nhưng chưa cải thiện hybrid đồng đều. Không chỉnh margin hay trọng số theo
kết quả này. Dữ liệu chạy, gallery và bảng đầy đủ nằm ở `var/text-vectors-ab-v1/`, đặc biệt
`comparison.md`, `comparison.json` và `v*-{off,on}/quality.json`.
Lệnh tái lập ở [hướng dẫn tìm kiếm](../guides/search.md).

Phép đo nháp SigLIP2 so với multilingual-e5 trước đó chỉ có log đến bước mã hóa ảnh, không có
bảng kết quả. Chưa biết e5 hoặc thứ tự label ở cuối có tốt hơn; chưa thay encoder hay thêm label.

## Planner v6

| Phép đo | Prompt trước | v6 |
|---|---:|---:|
| 20 câu multi-hop dev, bỏ q0300/q0320 | 11/18 | 15/18 |
| Multi-hop test v2 | chưa đo | 17/23 |
| v3 multi-hop | chưa đo | 32/32 |
| Single/multi-target v2 (80 câu) | chưa đo | 80/80 |
| Cặp scope: nhận nhầm single thành multi-hop | 2/16 | 2/16 |
| Fixture test | chưa đo | 29/30 |

Kết quả dao động giữa các lượt (v5 hai lượt: 31/36). Cặp scope do một tác giả viết và dễ hơn dataset.

## Độ trễ

Planner p50 khoảng 10–15 giây, p90 14–22 giây. Embedding + retrieval ở chế độ danh sách: p50 291–336 ms,
p90 419–473 ms. **Chưa đạt mục tiêu p90 toàn pipeline < 300 ms.**
