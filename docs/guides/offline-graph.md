# Graph offline với triples

Cài dependency: `uv sync --frozen --extra baseline --extra planner`.
Cấu hình `SHOPAIKEY_API_KEY`, `SHOPAIKEY_MODEL=gpt-6-luna`,
`SHOPAIKEY_BASE_URL=https://api.shopaikey.com/v1` trong `.env`.
Các biến tùy chọn: `SHOPAIKEY_MAX_TOKENS=4096`, `SHOPAIKEY_TIMEOUT=180`,
`SHOPAIKEY_RETRIES=1`. Không dùng key planner để trích xuất.

```bash
uv run image-search-graph-offline prepare data/input.csv --output var/graph-v2/input.json
uv run image-search-graph-offline extract var/graph-v2/input.json --output-dir var/graph-v2/run --max-requests 10
uv run image-search-graph-offline build var/graph-v2/run/extractions.json --output var/graph-v2/graph.json
uv run image-search-graph-offline stage var/graph-v2/graph.json --output var/graph-v2/staged.json
```

`extract` gọi API trả phí, chạy tuần tự, tối đa số request khai báo gồm retry.
Chạy lại cùng lệnh dùng các batch thành công đã lưu; batch lỗi xem trong `attempts/`.
`usage.json` tổng token thành công; raw attempt giữ usage của output lỗi khi provider có trả.
Chi phí USD để null vì chưa có bảng giá provider xác nhận. Giới hạn request không phải giới hạn USD.
`extractions.json` chỉ ghi khi toàn bộ input hoàn tất.

`build` không gọi API. File `graph.candidates.json` đề xuất đối sánh RapidFuzz, không tự merge.
Có thể build lại với `--decisions var/graph-v2/decisions.json`:

```json
{"entities": {"id-can-gop": "id-chuan"}, "relations": {},
 "definitions": {"id-quan-he": "Bộ phận thuộc đối tượng sở hữu, hướng bộ phận tới chủ thể"}}
```

ID lấy từ graph.json. Merge phải được đối chiếu metadata; scope giữ entity phụ của từng nơi
riêng cho tới khi có quyết định. Loại chưa xác định ghi `unclassified`. Tên thay đổi tạo ID mới
nếu không có quyết định merge; không đoán alias. Quan hệ thiếu định nghĩa giữ chuỗi rỗng.

`stage` cần Qdrant, Neo4j, image index/model SigLIP2 đã có và cấu hình graph hiện hành.
Tạo collection `graph_registry_<generation>`, node OfflineEntity/OfflinePredicate,
cạnh OFFLINE_FACT với provenance record_ids. Mọi query ghi dùng tham số, không nội suy
relationship model trả vào Cypher. Metadata/image vectors cũ không bị thay đổi.
Registry text bị cắt token sẽ báo lỗi. Chạy lại cùng artifact upsert cùng ID.
Đây là staging, chưa được retrieval online sử dụng; chưa có lệnh activation.

Sau lần stage đầu, có thể dùng vector registry và RapidFuzz để lấy ứng viên, rồi gọi
Luna chuẩn hóa với tối đa 5 ứng viên/đối tượng. Chỉ gửi các triple và record liên quan,
không gửi toàn bộ graph. Model không chắc phải trả match_id=null. ID ngoài candidates bị từ chối.

```bash
uv run image-search-graph-offline vector-candidates var/graph-v2/graph.json --output var/graph-v2/candidates.json
uv run image-search-graph-offline resolve var/graph-v2/graph.json --candidates var/graph-v2/candidates.json --output-dir var/graph-v2/resolve --max-requests 10
uv run image-search-graph-offline build var/graph-v2/run/extractions.json --decisions var/graph-v2/resolve/decisions.json --output var/graph-v2/normalized.json
uv run image-search-graph-offline stage var/graph-v2/normalized.json --output var/graph-v2/normalized-staged.json
```

Resolve có thể chạy tiếp bằng checkpoint; không tự retry, lần chạy sau tiếp tục batch chưa xong.
File quyết định chứa alias merge và định nghĩa do Luna tạo; cần xem lại trước activation.
Vector registry tạm dùng SigLIP2 hiện có, chưa có số đo chất lượng semantic matching.
Giới hạn: chưa có đồng bộ admin job, xóa vật lý snapshot cũ hoặc cutover online.
Cần hoàn thiện phần truy vấn quan hệ mở và benchmark graph mới trước khi dùng.

## Nhiều file và nhiều worker

```bash
uv run image-search-graph-offline extract-many data/a.csv data/b.csv --output-dir var/graph-multi --workers 16 --max-requests 1000 --max-tokens 8192
```

Lấy approve=yes, nhóm từng entity trong từng file, tối đa 8 record/9.000 ký tự mỗi batch
(có thể chỉnh bằng --max-records, --max-chars). Record ID được thêm namespace tên file;
source_record_id giữ ID dòng gốc. Các file được xen kẽ khi xếp lịch. Không chạy hai tiến
trình trên cùng output-dir. `inputs.json` lưu đường dẫn/hash CSV và metadata gửi model.

Mỗi worker chỉ có một request đang chạy. Retry API lỗi HTTP hoặc kết nối chờ 2, 4, 8, 16…
giây theo số lần thử của batch; Retry-After dạng số lớn hơn được tôn trọng. Tối đa 10 attempt
mỗi batch. Một HTTP 200 reset bộ đếm lỗi API liên tiếp chung cho tất cả worker.
Đủ 10 lỗi API liên tiếp thì circuit breaker giữ trạng thái pause, kể cả request đang chạy
sau đó thành công. Không gửi thêm request/retry; các request đang bay được chờ hoàn tất.
Nếu một batch trả output không hợp lệ 3 lần, dừng riêng với reason repeated_invalid_output.
Giới hạn request bao gồm retry và được kiểm tra dưới khóa dùng chung cho các worker.

Theo dõi `tracking.html` (tự refresh 5 giây), `progress.json`, `events.jsonl` và log stdout.
Tracking hiển thị state, từng file, record/batch đã xong, in-flight, retry-waiting, lỗi, token
(gồm attempt lỗi nếu provider trả usage), triples, thời gian và ETA ước lượng. Token tracking
là của lượt chạy hiện tại; output checkpoint giữ usage của các lượt trước.
Tạo file `PAUSE` trong output-dir để tạm dừng thủ công. Xóa PAUSE và chạy lại cùng lệnh để
resume, dùng checkpoint thành công, reset bộ đếm circuit cho lượt mới. Không tự resume sau pause.
Chỉ khi mọi batch hoàn tất mới xuất extractions.json để build. Lượt extract-many chỉ trích xuất;
chuẩn hóa và stage dùng các lệnh tương ứng phía trên.
