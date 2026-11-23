# Baseline v2 — mốc đã hoàn thành

Chốt v2 theo phạm vi code baseline và đánh giá sơ bộ, không có tuyên bố nhãn gold độc lập.
Đã truy vấn 400 câu cho mỗi phương pháp, gồm đủ single, multi-target và multi-hop.
Chấm 356 câu dương; 42 unknown vẫn có kết quả nhưng không chấm; 2 âm catalog báo riêng.
Cả ba phương pháp đều trả ảnh cho hai câu âm (chưa có ngưỡng từ chối).

Code trong `scripts/` cần các artifact local đã mô tả ở
[thiết kế benchmark](benchmark-design.md). Dữ liệu, ảnh, model, index và các file HTML
trong `var/` không được đưa lên Git; bản clone mới cần chuẩn bị lại dữ liệu nguồn.
Các script sửa nhãn đọc snapshot local; không chạy lại để ghi đè nhãn đã chỉnh tay.
Báo cáo số liệu này được lưu trong Git để giữ lại kết quả của mốc v2.

Kiểm tra: Ruff đạt, 47 test baseline đạt; đã kiểm tra hash, chấm lại 1.068 dòng điểm,
đủ 1.200 dự đoán, 3.600 lượt đo và 9 trang xem ảnh. Không tune theo kết quả.

## Kết quả theo split, loại và nhóm câu

400 câu được truy vấn; 356 câu có nhãn dương được chấm, 42 unknown không chấm.
Corpus 1.886 ảnh; test đã từng được xem. Chấm known positives, không chấm precision.
Không dùng kết quả để chọn câu hoặc tune RRF. RRF chuẩn 1:1, k=60, candidates=100.

| Split/loại | Phương pháp | Số câu | Known Recall@10 | Known nDCG@10 | Đủ mục tiêu@10 | p50 ms |
|---|---|---:|---:|---:|---:|---:|
| dev/multi-hop/canonical | vector | 17 | 0.353 | 0.266 | 0.353 | 108.0 |
| dev/multi-hop/canonical | keyword | 17 | 0.824 | 0.626 | 0.824 | 2.4 |
| dev/multi-hop/canonical | hybrid | 17 | 0.706 | 0.438 | 0.706 | 98.2 |
| dev/multi-hop/robustness | vector | 8 | 0.125 | 0.079 | 0.125 | 109.8 |
| dev/multi-hop/robustness | keyword | 8 | 0.750 | 0.533 | 0.750 | 2.5 |
| dev/multi-hop/robustness | hybrid | 8 | 0.375 | 0.214 | 0.375 | 102.8 |
| dev/multi-target/canonical | vector | 52 | 0.084 | 0.069 | 0.040 | 106.3 |
| dev/multi-target/canonical | keyword | 52 | 0.580 | 0.604 | 0.670 | 2.1 |
| dev/multi-target/canonical | hybrid | 52 | 0.416 | 0.358 | 0.560 | 98.4 |
| dev/multi-target/robustness | vector | 8 | 0.000 | 0.000 | 0.000 | 106.2 |
| dev/multi-target/robustness | keyword | 8 | 0.523 | 0.667 | 0.500 | 1.9 |
| dev/multi-target/robustness | hybrid | 8 | 0.493 | 0.366 | 0.750 | 98.2 |
| dev/single/canonical | vector | 75 | 0.073 | 0.067 | 0.167 | 106.0 |
| dev/single/canonical | keyword | 75 | 0.769 | 0.873 | 0.968 | 1.6 |
| dev/single/canonical | hybrid | 75 | 0.467 | 0.405 | 0.791 | 98.4 |
| dev/single/robustness | vector | 8 | 0.016 | 0.031 | 0.375 | 106.7 |
| dev/single/robustness | keyword | 8 | 0.578 | 1.000 | 1.000 | 1.2 |
| dev/single/robustness | hybrid | 8 | 0.363 | 0.538 | 1.000 | 97.0 |
| test/multi-hop/canonical | vector | 15 | 0.333 | 0.135 | 0.333 | 108.3 |
| test/multi-hop/canonical | keyword | 15 | 0.933 | 0.627 | 0.933 | 2.5 |
| test/multi-hop/canonical | hybrid | 15 | 0.600 | 0.362 | 0.600 | 98.3 |
| test/multi-hop/robustness | vector | 8 | 0.125 | 0.048 | 0.125 | 105.7 |
| test/multi-hop/robustness | keyword | 8 | 0.750 | 0.533 | 0.750 | 2.5 |
| test/multi-hop/robustness | hybrid | 8 | 0.625 | 0.292 | 0.625 | 98.0 |
| test/multi-target/canonical | vector | 56 | 0.022 | 0.048 | 0.000 | 106.1 |
| test/multi-target/canonical | keyword | 56 | 0.632 | 0.635 | 0.759 | 2.2 |
| test/multi-target/canonical | hybrid | 56 | 0.352 | 0.325 | 0.343 | 98.6 |
| test/multi-target/robustness | vector | 8 | 0.011 | 0.021 | 0.000 | 106.5 |
| test/multi-target/robustness | keyword | 8 | 0.617 | 0.719 | 0.750 | 2.0 |
| test/multi-target/robustness | hybrid | 8 | 0.273 | 0.409 | 0.375 | 100.0 |
| test/single/canonical | vector | 69 | 0.115 | 0.107 | 0.276 | 105.6 |
| test/single/canonical | keyword | 69 | 0.800 | 0.866 | 0.966 | 1.6 |
| test/single/canonical | hybrid | 69 | 0.587 | 0.500 | 0.793 | 97.9 |
| test/single/robustness | vector | 8 | 0.063 | 0.139 | 0.500 | 107.3 |
| test/single/robustness | keyword | 8 | 0.548 | 1.000 | 1.000 | 1.6 |
| test/single/robustness | hybrid | 8 | 0.339 | 0.671 | 0.875 | 97.8 |
| unassigned/single/canonical | vector | 24 | 0.073 | 0.430 | 0.917 | 105.3 |
| unassigned/single/canonical | keyword | 24 | 0.104 | 0.433 | 0.792 | 1.5 |
| unassigned/single/canonical | hybrid | 24 | 0.132 | 0.586 | 0.958 | 97.3 |

## Giới hạn

- Nhãn v2 là ứng viên, chưa duyệt độc lập; chỉ chấm known positives.
- Multi-hop chưa kiểm chứng bridge; điểm chỉ phản ánh tìm ảnh đích.
- 42 câu chưa biết đáp án vẫn truy vấn nhưng không chấm; hai câu âm catalog báo riêng.
- Câu toàn kho và robustness báo riêng; không gộp tất cả thành một điểm.
- Câu sinh từ metadata có thể thiên về BM25; corpus/test đã được xem.

## Recall và độ trễ trên test/canonical v2

Recall và tỷ lệ đủ mục tiêu trung bình theo intent_id. Độ trễ tính từ ba lượt/câu, sau warmup, không gồm nạp model/index. Đơn vị ms.

| Loại | Phương pháp | Câu | Known Recall@10 | Đủ mọi mục tiêu@10 | p50 | p90 | p95 | p99 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| single | vector | 69 | 0.1152 | 0.2759 | 105.57 | 129.78 | 141.58 | 185.05 |
| single | keyword | 69 | 0.8003 | 0.9655 | 1.62 | 1.88 | 1.95 | 2.10 |
| single | hybrid | 69 | 0.5871 | 0.7931 | 97.85 | 112.51 | 122.83 | 152.01 |
| multi-target | vector | 56 | 0.0224 | 0.0000 | 106.13 | 126.24 | 141.15 | 180.84 |
| multi-target | keyword | 56 | 0.6317 | 0.7593 | 2.18 | 2.48 | 2.58 | 2.92 |
| multi-target | hybrid | 56 | 0.3522 | 0.3426 | 98.56 | 111.86 | 120.88 | 137.04 |
| multi-hop | vector | 15 | 0.3333 | 0.3333 | 108.35 | 145.69 | 169.87 | 183.84 |
| multi-hop | keyword | 15 | 0.9333 | 0.9333 | 2.52 | 2.81 | 2.88 | 3.15 |
| multi-hop | hybrid | 15 | 0.6000 | 0.6000 | 98.30 | 109.98 | 113.49 | 134.48 |
