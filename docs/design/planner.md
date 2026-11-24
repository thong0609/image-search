# Planner v1

Planner dùng OpenAI để route câu hỏi và tạo kế hoạch. Chưa thực thi retrieval,
resolve entity trong catalog, graph hoặc tích hợp FE/BE.

## Cách chạy

Từ repository root, Python 3.12:

```bash
uv sync --frozen --extra baseline --extra planner
uv run --extra planner image-search-planner check tests/fixtures/planner-cases.jsonl
```

Đặt `OPENAI_API_KEY` trong `.env` hoặc môi trường. Không gửi key qua đối số CLI
hoặc lưu key vào Git. Đổi model qua `IMAGE_SEARCH_PLANNER_MODEL` hoặc `--model`.
Mặc định snapshot `gpt-5-mini-2025-08-07`; cần tài khoản có quyền sử dụng model.

```bash
uv run --extra planner image-search-planner route "Tìm 2 ảnh mặt tiền cửa hàng A và 1 ảnh bên trong cửa hàng B."
uv run --extra planner image-search-planner run tests/fixtures/planner-cases.jsonl --split dev --limit 3 --output-dir var/planner-v1/smoke
uv run --extra planner image-search-planner run tests/fixtures/planner-cases.jsonl --split dev --output-dir var/planner-v1/dev
uv run --extra planner image-search-planner evaluate tests/fixtures/planner-cases.jsonl var/planner-v1/dev/predictions.jsonl --split dev
```

Chỉ sau khi chốt prompt trên dev mới chạy test; không chỉnh prompt theo test:

```bash
uv run --extra planner image-search-planner run tests/fixtures/planner-cases.jsonl --split test --output-dir var/planner-v1/test
uv run --extra planner image-search-planner evaluate tests/fixtures/planner-cases.jsonl var/planner-v1/test/predictions.jsonl --split test
```

Mỗi query có một request logic, SDK retry lỗi transient tối đa 1 lần theo mặc định.
Batch tuần tự, ghi kết quả sau từng câu; không ghi đè thư mục đã có. Nếu bị ngắt,
chấm phần đã lưu hoặc tạo input/output mới cho phần chưa chạy; chưa có resume tự động.
Lỗi key/quyền/quota dừng batch, không gọi tiếp cả tập. Timeout/refusal/invalid plan
được ghi thành lỗi riêng, không biến thành route single hoặc câu âm.

Model chỉ nhận prompt và text. Không gửi `expected`, split, nhãn type của benchmark,
ảnh, record/entity ID hoặc kết quả retrieval. Dùng Responses API + JSON schema strict,
Pydantic kiểm tra lại logic; `store=false` trong request.

## Kế hoạch trả về

- `query_type`: single, multi-target, multi-hop hoặc unclear.
- `needs_clarification`, `clarification_question`: cần hỏi lại thì steps rỗng.
- `steps`: id, target_id, action, search_text, entity_mention, conditions, count, depends_on.
- `action`: resolve_entity (xác định entity từ mô tả bridge) hoặc retrieve_images.
- `entity_mention`: tên được nêu trực tiếp trong câu; không có thì null, không tự bịa ID.
- `conditions`: cụm điều kiện/phủ định trích từ câu; không tự thêm điều kiện.
- `count`: số ảnh nêu rõ; không nêu thì null, không tự mặc định 1.

Một mục tiêu không dependency là single; một mục tiêu có dependency là multi-hop.
Nhiều mục tiêu là multi-target, vẫn có thể chứa dependency. Một ảnh cần cả cổng và
biển hiệu không tự bị tách thành hai mục tiêu. Một ảnh ngoài và một ảnh trong là
hai mục tiêu dù cùng entity.

Giới hạn 5 mục tiêu cuối, 12 bước, số lượng tường minh 1–100. Dependency phải trỏ
về bước trước trong cùng target, không có ID trùng, chu kỳ hoặc bước không phục vụ
mục tiêu cuối. Không xác định được từ ngữ cảnh thiết yếu thì yêu cầu làm rõ.
Đây là kế hoạch thực thi dự kiến; model không xác nhận kho ảnh có đủ đáp án hay
bridge thực sự duy nhất. Việc đối chiếu entity/ảnh do executor sau này đảm nhiệm.

## Bộ kiểm tra và báo cáo

`tests/fixtures/planner-cases.jsonl` có 60 câu tổng hợp riêng cho planner, không lấy
đáp án ảnh v2 làm nhãn route. Mỗi split có 9 single, 9 multi-target, 9 multi-hop,
3 unclear. Hai câu multi-target chứa bước bridge. Mỗi intent nằm trong một split.
Nhãn do tác giả biên soạn, chưa có người duyệt độc lập; đây là bộ đánh giá thử.
Các entity minh họa là giả định, không cần có ảnh trong catalog để chấm hiểu câu.

`evaluate` tạo `report.json` cạnh predictions:

- Accuracy route, target, count, conditions, clarification, dependency shape và toàn plan.
- Confusion matrix theo loại, có cột ERROR; lỗi API vẫn nằm trong mẫu số.
- So đồ thị theo nội dung/dependency, không phụ thuộc tên ID do model chọn.
- Slot so sau chuẩn hóa Unicode/hoa thường/khoảng trắng; chưa chấm tương đương ngữ nghĩa.
  Các cách diễn đạt tương đương vẫn có thể bị chấm sai, cần xem case_scores để rà.
- Không so chuỗi search_text/câu làm rõ; hai phần này cần kiểm tra thủ công.
- p50/p90/p95 từ một lượt/câu, gồm retry, không gồm tạo client; chưa phải load test.
- Token usage và chi phí ước tính nếu cấu hình đầy đủ giá input/cached input/output.
  Thiếu giá thì chi phí là null, không được hiểu là miễn phí. Số liệu token thiếu
  được đếm riêng; request retry bị lỗi có thể có chi phí ngoài usage nhận được.

`run.json` ghi model, settings không có key, prompt version/hash, hash code và input.
`completed.json` ghi hash prediction khi batch hoàn tất. Evaluation kiểm tra các
file này nếu có; batch bị ngắt được chấm phần đã lưu và ghi số câu thực tế/tổng số câu.
Không báo accuracy giả bằng cách chạy nhãn expected qua chính scorer.

## Code và kiểm tra

`src/image_search/planner/`: schemas, settings, router, cli, evaluate. Không có vòng
lặp agent hoặc framework orchestration. Settings độc lập với baseline.

```bash
uv run --extra planner ruff check src/image_search/planner tests/unit/test_planner.py
uv run --extra planner pytest -q tests/unit/test_planner.py
```

Test sử dụng HTTP transport giả với SDK OpenAI thật, không truy cập mạng hoặc tốn phí.
Kiểm tra lỗi API, token/cost, ngăn lộ key, dependency, input và scorer.
Chưa có API key local thì chỉ xác nhận được code/fixture, chưa có số liệu model thật.

Tham khảo chính thức: [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[GPT-5 mini](https://developers.openai.com/api/docs/models/gpt-5-mini).


## Mốc thử nghiệm OpenAI planner-v1

Đã chạy 30 câu dev thực tế với prompt `planner-v1`, model
`gpt-5-mini-2025-08-07`; chưa chạy test hoặc chỉnh prompt theo kết quả dev.
Route đúng 24/30 (80%): single 9/9, multi-target 9/9, multi-hop 4/9,
unclear 2/3. Toàn plan khớp nhãn mẫu 53,3%; slot exact-match còn nhạy với
cách viết entity/điều kiện và nhãn mẫu chưa được duyệt độc lập.

Planner có p50 14,54 giây, p90 25,87 giây, p95 26,55 giây.
Yêu cầu người dùng: **p90 toàn pipeline < 300 ms**. Cấu hình gọi OpenAI trực tiếp
hiện tại không đạt. Mốc này giữ code/prompt làm đối chứng; chưa chọn làm planner online.
Chưa triển khai phương án thay thế trong mốc này.

Artifact local: `var/planner-v1/dev/report.json`, `report.md`, `review.html`,
`review-notes.md`; run ghi hash prompt/code/input, usage và kết quả từng câu.
Các artifact và key `.env` không đưa vào Git. Prompt được lưu trực tiếp trong
`src/image_search/planner/router.py`, có version và SHA-256 trong mỗi lần chạy.


## Prompt planner-v2

Prompt hiện tại bổ sung thứ tự quyết định route, ví dụ đối lập cùng ảnh/nhiều mục tiêu/
bridge, giữ đầy đủ entity mention, phân biệt số ảnh và số đối tượng, hỏi lại khi mâu thuẫn.
Chỉ thay prompt; giữ model/settings/nhãn/scorer như v1. Trên 30 câu dev:

| Chỉ số | V1 | V2 |
|---|---:|---:|
| Route | 80% | 100% |
| Single | 9/9 | 9/9 |
| Multi-target | 9/9 | 9/9 |
| Multi-hop | 4/9 | 9/9 |
| Unclear | 2/3 | 3/3 |
| Toàn plan exact-match | 53,3% | 80% |
| p90 planner | 25,87 giây | 29,22 giây |

Đây là kết quả dev dùng chỉnh prompt, chưa phải holdout độc lập. Test chưa chạy.
Còn regression count ở q040: model tự gán 1 khi người dùng không nêu số ảnh.
Các ca lệch conditions cần kiểm tra thủ công vì scorer exact-match và nhãn mẫu còn
thiếu/khác cách chia cụm. SLO p90 toàn pipeline < 300 ms vẫn không đạt.

Artifact: `var/planner-v2/dev/comparison.md`, `review.html`, `review-notes.md` và
`verification.json`. Kết quả v1 giữ nguyên; prompt v1 đã lưu trong commit `eceadae`.


## Kết quả test prompt v2

Đã chạy 30 câu test sau khi chốt prompt v2 trên dev, giữ model/settings/nhãn/scorer.
Không sửa prompt hoặc gọi lại để chọn kết quả. Route đúng 29/30 (96,7%):

| Nhóm | Đúng route | Toàn plan exact-match |
|---|---:|---:|
| Single | 9/9 | 3/9 |
| Multi-target | 9/9 | 6/9 |
| Multi-hop | 8/9 | 3/9 |
| Unclear | 3/3 | 3/3 |
| Tổng | 29/30 | 15/30 |

Một câu multi-hop bị gom single. Còn lỗi tự gán count=1 khi không nêu số ảnh,
entity mention chứa thêm đối tượng và điều kiện chia cụm khác nhãn mẫu.
Toàn plan 50% trên test so với 80% dev; đây là exact-match theo nhãn tổng hợp,
chưa phải độ đúng ngữ nghĩa do người duyệt độc lập xác nhận. Template/entity giả
còn đơn giản, cần truy vấn thực để đánh giá khả năng khái quát hóa rộng hơn.

P50 12,34 giây, p90 27,15 giây, p95 29,10 giây. Không đạt SLO toàn pipeline 300 ms.
Không có lỗi API/schema. Câu unclear không chấm slot retrieval; trên 27 câu còn lại:
target 26/27, count 22/27, conditions 15/27, dependency shape 26/27.

Xem artifact local `var/planner-v2/test/report.md`, `review.html`, `review-notes.md`
và `verification.json`. Kết quả lưu hash và đã kiểm tra khớp prompt/cấu hình dev.
Test nay đã được xem; nếu tiếp tục tune theo các lỗi này cần một phép đánh giá
độc lập mới, không gọi kết quả chạy lại là test holdout ban đầu.
