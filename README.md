# Images-search

Tìm ảnh bằng câu tiếng Việt trên kho riêng (1.886 ảnh có metadata). Câu hỏi được planner tách thành mục
tiêu và nơi chứa, xác định nơi chứa qua Neo4j hoặc qua ảnh khác, rồi tìm bằng vector SigLIP2 + BM25 gộp
RRF. Kết quả luôn là danh sách ảnh cho từng mục tiêu.

Trạng thái: luồng tìm kiếm và playground local đã chạy; reranking, website production và đăng nhập chưa có.
Xem [lộ trình](docs/planning/delivery-plan.md) và [kết quả đo](docs/evaluation/results.md).

## Cài đặt

Cần Python 3.12, uv, Docker Compose v2. Frontend cần Node 24.22.2 (`frontend/.nvmrc`) và npm 11.19.1.

```bash
cp .env.example .env            # đổi mật khẩu, thêm OPENAI_API_KEY
uv sync --frozen --extra baseline --extra planner
docker compose --profile graph up -d qdrant neo4j
```

`.env`: `IMAGE_SEARCH_GRAPH_PASSWORD` cho Neo4j; nếu dùng PostgreSQL thì `POSTGRES_PASSWORD` phải khớp
`IMAGE_SEARCH_DATABASE_URL`. Mọi dịch vụ chỉ bind localhost; không commit `.env`.

## Chạy

1. [Chuẩn bị dữ liệu và index](docs/guides/data-and-baseline.md).
2. [Nhập graph](docs/guides/graph.md).
3. [Tìm kiếm và đánh giá](docs/guides/search.md).

Playground:

```bash
HF_HUB_OFFLINE=1 uv run uvicorn image_search.main:app --host 127.0.0.1 --port 8000
cd frontend && cp .env.example .env.local && npm ci && npm run dev   # http://127.0.0.1:3000
```

## Cấu trúc

```text
src/image_search/
  main.py, config.py, health.py   ứng dụng FastAPI, cấu hình, readiness
  playground.py, api/v1/          API playground và health
  planner/                        prompt, phân tích câu, kế hoạch
  retrieval/                      engine, executor, danh sách kết quả, BM25
  embedding/                      encoder SigLIP2 và index ảnh
  graph/                          dựng graph quan hệ từ metadata
  baseline/                       dữ liệu, nhãn, baseline tìm cả câu
  adapters/                       Qdrant, Neo4j, PostgreSQL, object storage
  worker.py, smoke.py             scaffold cho giai đoạn sau
scripts/                          đánh giá retrieval và route planner
migrations/                       schema PostgreSQL (Alembic)
frontend/                         Next.js playground
tests/                            unit, integration, fixtures
docs/                             hướng dẫn, thiết kế, đánh giá, kế hoạch
data/, var/                       dữ liệu và artifact local, ngoài Git
```

PostgreSQL, migration, worker và object storage là scaffold cho website; luồng tìm kiếm và playground
không cần chúng:

```bash
docker compose up -d && uv run alembic upgrade head
uv run image-search-worker --once
uv run image-search-smoke --api-url http://127.0.0.1:8000
```

## Kiểm tra

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest                                    # unit
RUN_NEO4J_INTEGRATION=1 uv run pytest            # thêm Neo4j, dùng namespace test riêng
RUN_INTEGRATION=1 uv run pytest tests/integration  # cần PostgreSQL trống đã migrate
cd frontend && npm run lint && npm run typecheck && npm run format:check && npm run build
```

Tài liệu: [mục lục](docs/README.md).
