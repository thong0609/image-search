# Planner local thử nghiệm

Bật bằng `IMAGE_SEARCH_PLANNER_LOCAL_MODE=heuristic`; mặc định `off` giữ planner LLM.
Cần restart backend sau khi đổi cấu hình. Website search và playground đều dùng bộ quy tắc;
playground không dùng cache LLM như trước. Các câu không được quy tắc hỗ trợ tiếp tục gọi LLM.

Bộ quy tắc `heuristic-v1` chỉ nhận tên/alias không mơ hồ trong snapshot graph đang hoạt động,
cảnh bên trong/bên ngoài/mặt tiền/toàn cảnh/cổng của tên đó, một danh sách nhỏ mô tả ảnh trực tiếp,
và các mẫu nhiều mục tiêu rõ ràng. Mọi phần dư chưa hiểu đều chuyển sang LLM.
Tên được so toàn cụm bằng cùng chuẩn hóa với graph; tên có chữ “và” được thử trước phép tách.
Không suy đoán tên mới từ chữ hoa. Phủ định, tham chiếu hội thoại, quan hệ chưa hỗ trợ và multi-hop
chưa có quy tắc đều chuyển sang LLM. Đây chưa phải mô hình local đã huấn luyện.

Heuristic tạo QueryDraft rồi dùng compile_plan hiện có. Tên/alias lấy lúc nạp snapshot; khi active
collection đổi thì nạp lại. Không dùng câu hỏi hoặc đáp án benchmark để dựng danh sách tên.

Search trả thêm `planner` (route, reason, version, cached) và `timing_ms`. Thời gian queue/preparation,
embedding/retrieval tính ms. Các span `graph_ms`, `qdrant_ms`, `qdrant_filter_ms`, `bm25_ms`,
`fusion_ms`, `embedding_ms` nằm bên trong tổng service; không cộng tất cả span để tính tổng.
`request_ms` đo handler API, gồm đọc/ghi snapshot và hydrate metadata, trước serialize/HTTP transport.

Đánh giá offline bằng plan LLM đã lưu, không gọi API trả phí:

```bash
HF_HUB_OFFLINE=1 uv run python scripts/evaluate_heuristic.py \
  --queries var/benchmark-v2-completed-v1/queries.jsonl \
  --answers var/benchmark-v2-completed-v1/answers.jsonl \
  --plans var/evaluation-v2-completed-v1/plans.jsonl \
  --output-dir var/heuristic-v1/dev-run --split dev --workers 1 4 --website
```

Dùng thư mục output mới. `--website` dùng active index và visibility SQL; không ghi search snapshot.
`--rounds` mặc định 1, tăng khi đo độ ổn định. Chốt quy tắc trên dev trước khi đánh giá test.
Báo cáo gồm phân tuyến, chất lượng theo họ ý định, latency replay đo thật và ước lượng cộng thời gian
LLM lịch sử. Ước lượng lịch sử không phải phép đo HTTP end-to-end mới, nhất là khi tải đồng thời:
replay bỏ thời gian chờ LLM nên mô phỏng đến retrieval khác thực tế. Chỉ đo HTTP trên tải mục tiêu
mới có thể xác nhận SLA p90 ≤ 500 ms. Không dùng kết quả replay để tuyên bố đạt SLA.

Có thể thêm `--baseline-predictions` trỏ tới predictions.jsonl của lượt baseline và
`--timing-limit 12` để chạy lại chất lượng toàn split chỉ trên những câu đổi plan, đồng thời
đo timing trên mẫu ngẫu nhiên seed 42. Baseline phải cùng index, metadata, graph và plans;
visibility phải bằng toàn corpus. Mẫu timing nhỏ chỉ là smoke đo tốc độ, không xác nhận SLA.

## Kết quả thử ban đầu trên dev

230 câu: 20 câu đi heuristic (8,7%), 210 câu fallback. Không thấy sai query_type trong 20 câu
được nhận. So chất lượng theo họ ý định, không có chỉ số giảm; nhóm canonical multi-target
Recall@10 tăng 0,000312 và nDCG@10 tăng 0,000561; các nhóm còn lại không đổi. Đây là kiểm tra
trên dev, chưa phải đánh giá test độc lập. Tập test chưa dùng để chỉnh quy tắc.

Timing smoke chỉ 12 câu lấy ngẫu nhiên seed 42, một vòng, trên máy hiện tại:

| Tuyến replay | P90, 1 request | P90, 4 request đồng thời |
|---|---:|---:|
| Plan LLM đã lưu | 971 ms | 3.193 ms |
| Heuristic + fallback plan đã lưu | 834 ms | 3.284 ms |

Hai dòng đều loại thời gian gọi LLM; có SQL chuẩn bị, embedding, retrieval và chờ khóa.
Không được diễn giải chênh lệch nhỏ này thành heuristic nhanh hơn/chậm hơn: mẫu nhỏ và đo nối tiếp.
Phần lớn câu trong mẫu vẫn dùng plan LLM đã lưu. Chưa đạt SLA 500 ms ngay cả khi bỏ thời gian LLM.

Trong lượt tuần tự baseline, p90 embedding khoảng 312 ms, Qdrant filtered_ids khoảng 491 ms;
ở tải 4, p90 chờ khóa khoảng 2.307 ms. Các p90 thuộc những request khác nhau nên không cộng chúng.
Đây là các điểm cần ưu tiên đo/tối ưu tiếp. Số đo chưa bao gồm HTTP, serialize và ghi search session.
Artifact chi tiết: var/heuristic-v1/dev-final/{run,report}.json, routes.jsonl và predictions.

Chưa chọn hoặc huấn luyện model pretrained local, chưa hỗ trợ thêm phủ định/multi-hop bằng local,
chưa bật heuristic mặc định và chưa xác nhận SLA trên tải sản xuất. Giả định đo trên máy hiện tại,
1 và 4 request đồng thời. Phạm vi lượt này là triển khai thử giai đoạn đo và heuristic bảo thủ.
