# Chạy tìm kiếm

Cách hoạt động ở [luồng tìm kiếm](../design/search-pipeline.md). Cần Qdrant đã có index và Neo4j đã
nhập graph cùng snapshot; runtime không đọc CSV/JSONL nguồn.

```bash
uv sync --frozen --extra baseline --extra planner
docker compose --profile graph up -d qdrant neo4j
```

## Planner

Đặt `OPENAI_API_KEY` trong `.env`; không truyền key qua đối số. Mỗi câu một request có phí.

```bash
uv run image-search-planner check tests/fixtures/planner-cases.jsonl          # không gọi API
uv run image-search-planner route "Tìm 2 ảnh mặt tiền cửa hàng A và 1 ảnh bên trong cửa hàng B."
uv run image-search-planner run <queries.jsonl> --split dev --output-dir var/planner-new
uv run image-search-planner evaluate tests/fixtures/planner-cases.jsonl var/planner-new/predictions.jsonl
```

- Batch chạy tuần tự, ghi sau từng câu, không ghi đè thư mục đã có; lỗi key/quota dừng batch.
- Chỉ gửi prompt và câu hỏi; không gửi nhãn, đáp án hoặc ảnh. `store=false`.
- `run.json` ghi model, hash prompt/code/input; không có key.
- Cấu hình `IMAGE_SEARCH_PLANNER_*` trong [.env.example](../../.env.example). `REASONING_EFFORT`
  mặc định `low`.

## Retrieval theo kế hoạch đã lưu

Không gọi OpenAI. Input là JSONL của planner (`query_id`, `status`, `plan`, `text`).

```bash
HF_HUB_OFFLINE=1 uv run image-search-retrieval var/planner-new/predictions.jsonl --method hybrid --output-dir var/retrieval-new
```

- `--method vector|keyword|hybrid|all`; `--rounds` mặc định 3; `--strict` chỉ trả kết quả đúng kế
  hoạch, không lấp bằng tìm cả câu; `--aliases` nhận JSON alias → danh sách entity ID.
- Mỗi phương pháp có `predictions.jsonl`, `timings.jsonl`, `report.json`, `results.html`.
- Cấu hình `IMAGE_SEARCH_RETRIEVAL_*` và `IMAGE_SEARCH_EMBEDDING_*` trong `.env.example`.

## Đánh giá

```bash
# Chất lượng và độ trễ; không gọi API. Thêm --plans để cộng độ trễ planner.
uv run python scripts/evaluate_retrieval.py var/retrieval-new --queries <queries.jsonl> --answers <answers.jsonl>
# Route của planner nhiều lượt, báo bỏ sót và nhận nhầm multi-hop. Gọi API có phí.
uv run python scripts/evaluate_planner_routes.py tests/fixtures/planner-scope-cases.jsonl --split dev --rounds 3 --output-dir var/routes-new
```

## Giao diện

```bash
HF_HUB_OFFLINE=1 uv run uvicorn image_search.main:app --host 127.0.0.1 --port 8000
cd frontend && npm run dev   # http://127.0.0.1:3000
```

- `/`: nhập câu hỏi, xem lưới ảnh theo từng mục tiêu, bấm ảnh để xem chi tiết và trang nguồn. Câu nằm
  trong URL (`?q=`). Mỗi câu mới gọi OpenAI; quay lại câu cũ dùng kết quả đã có trong trình duyệt.
- `/playground`: xem kế hoạch, token và thời gian từng bước.
- Model và index nạp ở lượt tìm đầu tiên (khoảng 10 giây thêm). Không cần PostgreSQL. Chưa có đăng nhập
  hoặc quản trị; chỉ chạy local.

### API

| Endpoint | Nội dung |
|---|---|
| `POST /v1/search` | `{"query": "..."}`, 1–500 ký tự |
| `GET /v1/images/{id}` | Ảnh gốc trong corpus |
| `GET /v1/images/{id}/thumbnail` | Ảnh thu nhỏ tối đa 640×480, tạo khi cần ở `var/objects/thumbnails/` |
| `POST /v1/playground/run` | Công cụ xem từng bước |

`/v1/search` trả `groups` (mỗi mục tiêu: `label`, `approximate`, `items` gồm `id`, `title`, `caption`,
kích thước, `source_url`, `source_name`), `question` khi cần làm rõ, `planned=false` khi planner lỗi và
chỉ tìm bằng nguyên câu. Lỗi hạ tầng trả 503, không lộ chi tiết. Đây là bản demo, rút gọn so với
[đặc tả API](../design/api-contract.md): chưa có bộ lọc, phân trang và đăng nhập.
