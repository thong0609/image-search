# Kết quả đánh giá

Nhãn và giới hạn của từng bộ ở [benchmark](benchmarks.md). Mọi số là hybrid RRF 1:1 nếu không ghi khác;
một lượt planner mỗi câu. Corpus 1.886 ảnh.

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
