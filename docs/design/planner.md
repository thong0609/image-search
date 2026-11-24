# Planner

Planner dùng OpenAI để route câu hỏi và tạo kế hoạch. CLI chỉ lập kế hoạch;
executor và playground local dùng kế hoạch để chạy retrieval/graph trong phạm vi đã hỗ trợ.

## Prompt đang dùng: phân tích phạm vi, code suy ra route

`planner-draft-scope-v6`. Model không còn trả `query_type`, bước hoặc dependency. Model điền
`QueryDraft` (`src/image_search/planner/draft.py`): nội dung ảnh đích, nơi chứa, và `owner`
của từng điều kiện (ảnh hay nơi chứa). `compile_plan` suy ra `Step`, dependency, `query_type`;
`QueryPlan` và executor giữ nguyên. Kết quả lưu thêm `draft`, và `raw_output` khi plan sai.

Luật code chính (`tests/unit/test_planner_draft.py`):

- Nơi chứa chưa có tên và có điều kiện riêng: resolve_entity rồi retrieve_images (multi-hop).
- Nơi chứa có tên riêng: single; mô tả kèm theo giữ ở `identity_text`, chỉ dùng khi graph
  không có tên đó.
- Một quan hệ trực tiếp với anchor có tên: bộ lọc graph trong bước trả ảnh (single).
  Từ hai quan hệ hoặc đường đi dài hơn: resolve_entity.
- Ảnh đích chính là nơi đó: mọi mô tả là điều kiện ảnh. "Bên trong X" là cảnh khác của X.
- Cụm đứng trước nơi chứa trong câu không thể bổ nghĩa cho nơi đó.
- Bước trả ảnh của multi-hop được dựng không chứa đặc điểm nhận diện.

`IMAGE_SEARCH_PLANNER_REASONING_EFFORT` mặc định `low`: với mức mặc định của model, 3/36 câu
ở lượt dev đầu hết 4.096 token và độ trễ cao hơn.

### Kết quả 25/11/2026

Một lượt/câu, GPT-5 mini. Prompt cũ là `planner-graph-multihop-scope`; `data20` là 20 câu dev
multi-hop, bỏ q0300/q0320 (bridge và đích cùng một đối tượng; nhãn giữ nguyên, chờ duyệt).
"Đúng vai" yêu cầu đặc điểm nhận diện chỉ ở resolve và nội dung đích chỉ ở retrieve.

| Phép đo | Prompt cũ | v6 |
|---|---:|---:|
| data20 route, bỏ 2 câu nhãn nghi vấn | 11/18 | 15/18 |
| data20 đúng vai | 11/18 | 15/18 |
| data20 cả 20 câu | 11/20 | 16/20 |
| Cặp scope: bỏ sót multi-hop | 0/16 | 0/16 |
| Cặp scope: nhận nhầm single thành multi-hop | 2/16 | 2/16 |
| Single/multi-target v2 (50 dev + 30 test) | chưa đo | 80/80 |
| Fixture test | chưa đo | 29/30 |
| p50 / p90 planner trên data20 (giây) | 26,1 / 32,7* | 15,2 / 18,4 |

*Độ trễ cũ là toàn pipeline, 2 worker; chủ yếu là planner. Chưa đạt SLO 300 ms.
v5 (trước luật tên riêng) chạy 2 lượt data20: 31/36 route, 30/36 đúng vai; kết quả dao động
giữa các lượt. Lỗi còn lại ổn định: q0310 ("có ảnh trên cao…"), scope-09/14 (nhận nhầm).

Replay hybrid không gọi API, plan v2 trong `pipeline-v1` so với plan mới (Recall@10):

| Nhóm | Plan v2 | v6 |
|---|---:|---:|
| Holdout test: single (18) | 0,731 | 0,792 |
| Holdout test: multi-target (12) | 0,507 | 0,507 |
| Dev: single (29) | 0,679 | 0,658 |
| Dev: multi-target (18) | 0,341 | 0,340 |
| data20 multi-hop (19), so với prompt cũ | 0,263 | 0,000 |

Multi-hop về 0 ở thời điểm đó: 5 câu trúng trước đây đều bị route nhầm sang single, còn
executor chưa có visual bridge. Đã bổ sung sau, dev R@10 0,842:
[visual bridge](../baseline/baseline-usage.md#visual-bridge). Bản v5 từng làm giảm single/multi-target vì cắt tên riêng
dài; v6 sửa lỗi này, còn q0102 bị tách "Phòng vắt sữa" khỏi tên.

Giới hạn: bộ cặp scope do cùng một tác giả viết, dễ hơn dataset và split test đã được xem khi
đo prompt cũ; text 54 câu multi-hop v2 cũng đã được xem. Fixture test cũ từng trùng ví dụ prompt
(q049), nay ví dụ đã thay. Holdout 30 câu không dùng để tune nhưng từng có trong lượt 400 câu.
Tổng chi phí thử nghiệm ước tính $1.21. Artifact: `var/planner-scope-v1/` (`v6-*` là bản
cuối, `old-scope` là mốc, `replay-*6` là replay).

```bash
uv run python scripts/evaluate_planner_routes.py tests/fixtures/planner-scope-cases.jsonl --split dev --rounds 3 --output-dir var/planner-scope-new
```

## Lịch sử: prompt planner-graph-multihop-scope

Prompt này đã được thay bằng bản trên. Đã sửa theo yêu cầu người dùng để mô tả rõ ảnh đích, entity chưa biết tên và điều kiện
nhận diện qua cảnh khác. Schema, model GPT-5 mini và executor giữ nguyên.

- Điều kiện trực tiếp mô tả ảnh cần trả: single, kể cả chưa có tên entity.
- Cần xác định entity từ cảnh/bộ phận khác trước khi lấy ảnh đích: resolve_entity →
  retrieve_images với dependency trong cùng target; một target như vậy là multi-hop.
- Bridge không trở thành điều kiện bắt buộc xuất hiện trong ảnh đích. Không tự đoán tên
  entity hoặc bỏ dependency chỉ vì executor chưa hỗ trợ visual bridge.
- Số cạnh graph, số điều kiện hay số ảnh không tự quyết định route. Nhiều target vẫn
  multi-target; GRAPH RULES chỉ mã hóa quan hệ sau khi hiểu phạm vi điều kiện.

Ví dụ: “phòng trưng bày có cửa sổ tròn” là single; “phòng trưng bày của bảo tàng có
cổng hình vòng cung” cần nhận diện bảo tàng từ cổng rồi tìm phòng, là multi-hop.
Các ví dụ minh họa quy tắc không cung cấp tên entity/ảnh đáp án trong dataset.

Đã gọi API trên đúng bộ 20 câu dataset multi-hop dev đã dùng ở các lượt trước:
20/20 request hợp lệ; route 11 multi-hop, 7 single, 2 unclear. Prompt ban đầu nhận
5/20 và prompt người dùng thử nhận 4/20 multi-hop theo nhãn v2. Một lượt mỗi prompt,
chưa chứng minh độ ổn định hay khả năng tổng quát hóa.

Cả 11 kế hoạch multi-hop vẫn unsupported ở executor vì cần nhận diện thị giác qua
cảnh khác. Hybrid Recall@10 canonical 0.2941, nDCG@10 0.2112 trên 17 câu có nhãn dương;
hai câu robustness recall=0. Một câu unknown không chấm retrieval. p50/p90 toàn pipeline
26.09/32.66 giây (2 worker); chi phí theo usage ước tính $0.082331, chưa đối soát hóa đơn.
Báo cáo và đối chiếu từng câu: `var/openai-multihop20-scope-v1/run/comparison.md`.

Tests dùng mock chỉ kiểm tra request/schema, không đo chất lượng model. Các lượt prompt
trước bên dưới là lịch sử; không áp dụng mặc nhiên cho prompt vừa sửa. Test và dataset
đã được xem trong quá trình thử nghiệm nên không coi là holdout độc lập mới.

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

`src/image_search/planner/`: draft, schemas, settings, router, cli, evaluate. Không có vòng
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
