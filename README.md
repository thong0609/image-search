# Images-search

Tìm ảnh bằng câu tiếng Việt trên kho riêng (1.886 ảnh có metadata). Câu hỏi được planner tách thành mục
tiêu và nơi chứa, xác định nơi chứa qua Neo4j hoặc qua ảnh khác, rồi tìm bằng vector SigLIP2 + BM25 gộp
RRF. Kết quả luôn là danh sách ảnh cho từng mục tiêu.

Trạng thái: đã có tìm kiếm, đăng nhập, quản trị tài khoản/kho ảnh và nhập CSV theo batch.
Reranking chưa triển khai.
Xem [lộ trình](docs/planning/delivery-plan.md) và [kết quả đo](docs/evaluation/results.md).

## Cài đặt

Cần Python 3.12, uv, Docker Compose v2. Frontend cần Node 24.22.2 (`frontend/.nvmrc`) và npm 11.19.1.

```bash
cp .env.example .env            # đổi mật khẩu, thêm OPENAI_API_KEY
uv sync --frozen --extra baseline --extra planner
docker compose --profile graph up -d postgres qdrant neo4j
```

`.env`: `IMAGE_SEARCH_GRAPH_PASSWORD` cho Neo4j;  `POSTGRES_PASSWORD` phải khớp
`IMAGE_SEARCH_DATABASE_URL`. Mọi dịch vụ chỉ bind localhost; không commit `.env`.

## Chạy

1. [Chuẩn bị dữ liệu và index](docs/guides/data-and-baseline.md).
2. [Nhập graph](docs/guides/graph.md), rồi [khởi tạo tài khoản và catalog website](docs/guides/website.md).
3. [Tìm kiếm và đánh giá](docs/guides/search.md).

Màn hình tìm ảnh ở `/`, công cụ xem từng bước ở `/playground`:

```bash
HF_HUB_OFFLINE=1 uv run uvicorn image_search.main:app --host 127.0.0.1 --port 8000
cd frontend && cp .env.example .env.local && npm ci && npm run dev   # http://127.0.0.1:3000
```

## Cấu trúc

```text
src/image_search/
  main.py, config.py, health.py   ứng dụng FastAPI, cấu hình, readiness
  search.py, playground.py        dịch vụ tìm ảnh, xem từng bước
  api/v1/                         API tìm ảnh, playground, health
  planner/                        prompt, phân tích câu, kế hoạch
  retrieval/                      engine, executor, danh sách kết quả, BM25
  embedding/                      encoder SigLIP2 và index ảnh
  graph/                          dựng graph quan hệ từ metadata
  baseline/                       dữ liệu, nhãn, baseline tìm cả câu
  adapters/                       Qdrant, Neo4j, PostgreSQL, object storage
  ingestion/, worker.py           nhập CSV, embedding batch và công bố snapshot
  auth/                           xác thực, tài khoản và CLI quản trị
  smoke.py                        kiểm tra stack local
scripts/                          đánh giá retrieval và route planner
migrations/                       schema PostgreSQL (Alembic)
frontend/                         Next.js: màn hình tìm ảnh và playground
tests/                            unit, integration, fixtures
docs/                             hướng dẫn, thiết kế, đánh giá, kế hoạch
data/, var/                       dữ liệu và artifact local, ngoài Git
```

Website cần PostgreSQL cho đăng nhập, trạng thái ảnh và phân trang.
Xem [khởi tạo website và chạy worker CSV](docs/guides/website.md):

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
