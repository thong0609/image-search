# Images-search

Baseline chạy bằng CLI: CSV → tải ảnh → nhãn đánh giá → vector → tìm kiếm → báo cáo.
Giữ scaffold API/frontend, migration và các adapter hạ tầng để phát triển sau.

## Chạy baseline

Baseline dùng Qdrant để lưu và tìm vector. Cài Python 3.12, uv và Docker, sau đó:

```bash
uv sync --frozen --extra baseline
uv run --extra baseline image-search-baseline prepare data/general_10m_part_02_18-11-2026_CHIEU_To_Huy_Thong.csv
uv run --extra baseline image-search-baseline download --limit 20
```

Ảnh và kết quả được lưu trong `var/`, ngoài Git. Bỏ `--limit` để tải toàn bộ;
chạy lại để tiếp tục và thử lại URL lỗi. Đọc các bước còn lại trong
[hướng dẫn chạy baseline](docs/baseline/baseline-usage.md), gồm bước sửa query/đáp án trước khi đo.
Bộ nhãn và quy tắc đánh giá nằm trong [tài liệu benchmark](docs/baseline/benchmark-design.md).

## Planner OpenAI

Planner phân loại câu và tách mục tiêu/dependency, chưa thực thi retrieval.

```bash
uv sync --frozen --extra baseline --extra planner
uv run --extra planner image-search-planner check tests/fixtures/planner-cases.jsonl
```

Cấu hình `OPENAI_API_KEY` trong `.env` để chạy model thật. Xem
[hướng dẫn planner](docs/design/planner.md) để thử một câu, chạy batch và chấm điểm.
`src/image_search/planner/` chứa schema, settings, router, CLI và scorer;
`tests/fixtures/planner-cases.jsonl` chứa 60 câu và nhãn kế hoạch riêng.

## Embedding SigLIP2

Tái sử dụng index 1.886 ảnh, 768 chiều; mã hóa text của từng bước planner cùng
checkpoint/processor, chuẩn hóa L2. Model nạp một lần trong mỗi tiến trình.

```bash
uv sync --frozen --extra baseline --extra planner
image-search-embedding check --output-dir var/embeddings/siglip2/check-new
image-search-embedding text "bên trong cửa hàng" --output-dir var/embeddings/siglip2/text-new
image-search-embedding plans var/planner-v2/dev/predictions.jsonl --output-dir var/embeddings/siglip2/plans-new
```

Dùng `HF_HUB_OFFLINE=1` nếu chỉ muốn đọc model đã có trong cache local.
Vector text chỉ tồn tại trong RAM; CLI ghi mapping `steps.jsonl` và báo cáo `embedding.json`, không ghi vector ra đĩa.
Chi tiết và phép đo: [embedding cho retrieval](docs/baseline/baseline-usage.md#embedding-cho-retrieval).

## Retrieval theo planner

Tìm vector/BM25/RRF riêng theo từng mục tiêu. Nhận kế hoạch đã lưu, không gọi OpenAI.
Neo4j giải điều kiện `LOCATED_IN`, `PART_OF`, `BRANCH_OF`; Qdrant lọc ảnh theo
entity đích trước top-K. BM25 dùng cùng tập ảnh và gộp RRF 1:1.
Entity chưa biết tên được nhận diện qua ảnh khác ([visual bridge](docs/baseline/baseline-usage.md#visual-bridge)),
kết quả đánh dấu suy đoán chưa xác minh. Quan hệ ngoài graph và không nhìn thấy được trả
`unsupported_graph_relation`.

```bash
image-search-retrieval var/retrieval-v1/planner/predictions.jsonl --method all --output-dir var/retrieval-v1/new-results
```

Query được mã hóa trực tiếp bằng SigLIP2 rồi tìm trong Qdrant.
Cần Qdrant đã có dữ liệu và graph Neo4j đã import, cùng snapshot; runtime không đọc CSV/JSONL nguồn hoặc keyword index trên đĩa; [hướng dẫn chi tiết](docs/baseline/baseline-usage.md#retrieval-theo-kế-hoạch).

## Graph quan hệ Neo4j

**Trạng thái 24/11/2026:** Codex đã trực tiếp lập extraction, không gọi API.
Graph thật đã thay bằng 1.886 Image và 319 Entity; 1.932 cạnh DEPICTS,
220 LOCATED_IN, 61 BRANCH_OF, 20 PART_OF. Không còn node nguồn.
Phạm vi đọc gồm tên/loại của cả 185 nhóm và các câu caption/tiêu đề thể hiện quan hệ;
chưa gán nhãn đầy đủ mọi chi tiết trong 2.062 caption. Có 40 ghi chú thiếu/ngoài schema.

Dữ liệu đã điền ở `var/graph-manual-v1/reviewed.jsonl`, bảng quyết định dễ đọc ở
`decisions.tsv`, graph đã nhập ở `graph.json`, kết quả kiểm tra ở `import.json` và
`functional-checks.json`. Replay 400 kế hoạch v2 (vector/keyword/hybrid) và báo cáo
ở `var/graph-manual-v1/replay-v2/report.md`; không gọi lại planner. Multi-hop v2
không có predicate vẫn unsupported, không coi đây là benchmark multi-hop mới.
Chạy lại phần chấm mà không chạy model/retrieval:

```bash
uv run python scripts/report_retrieval_replay.py var/graph-manual-v1/replay-v2
```

Các file dataset/artifact này không đưa vào Git.
Giữ hash của từng nhóm metadata để từ chối extraction cũ khi dữ liệu thay đổi.

```bash
uv sync --frozen --extra baseline --extra planner
docker compose --profile graph up -d neo4j
# Xuất metadata để đọc/điền Extraction trực tiếp, không gọi API.
uv run image-search-graph prepare --output var/graph-manual-v1/groups-new.jsonl
# Dựng artifact từ reviewed.jsonl, không gọi API/ghi Neo4j; dùng output chưa tồn tại.
uv run image-search-graph build var/graph-manual-v1/reviewed.jsonl --output var/graph-manual-v1/graph-new.json
# Import khi đã sẵn sàng thay graph của dataset.
uv run image-search-graph import var/graph-manual-v1/graph-new.json
uv run image-search-graph check
```

Lệnh `extract` qua API vẫn có nếu sau này được yêu cầu; không dùng cho lần dựng graph này.
Planner online dùng OpenAI trực tiếp với `OPENAI_API_KEY` trong `.env`,
model `gpt-5-mini-2025-08-07`. Endpoint được cố định `https://api.openai.com/v1`.
Nếu biến môi trường shell ghi đè model trong `.env`, chỉ định model trong lệnh chạy.

Import thay dataset trong một transaction; sai mapping Qdrant bị chặn trước khi ghi.
Browser: <http://localhost:7474>, Bolt `bolt://localhost:7687`; user `neo4j`, mật khẩu
trong `.env`. Volume `images-search_neo4j-data` (`/data`). Không cần embed lại ảnh.

Đánh giá planner v3 mới sẽ gọi API; chỉ chạy khi được yêu cầu chi phí tương ứng.
Dev trước rồi khóa cấu hình chạy test:

```bash
HF_HUB_OFFLINE=1 uv run python scripts/run_pipeline_evaluation.py --split dev --output-dir var/pipeline-graph-v1/dev
uv run python scripts/report_pipeline_evaluation.py var/pipeline-graph-v1/dev
HF_HUB_OFFLINE=1 uv run python scripts/run_pipeline_evaluation.py --split test --output-dir var/pipeline-graph-v1/test
uv run python scripts/report_pipeline_evaluation.py var/pipeline-graph-v1/test
RUN_NEO4J_INTEGRATION=1 uv run pytest -q
```

Báo cáo tách ba loại câu hỏi, Recall/nDCG, trạng thái thiếu kết quả và p50/p90/p95;
không dùng test labels để trích graph. [Plan và trạng thái](docs/design/graph-reranking-design.md#10-plan-graph-quan-hệ-từ-metadata-yes).

## Scaffold hiện có

Backend modular monolith: một codebase, API và worker chạy riêng. Phase 0 đã có scaffold; crawler/search/auth nghiệp vụ và model handlers triển khai ở các phase sau. hướng dẫn chạy ở `docs/baseline/`, đặc tả hệ thống ở `docs/design/`, kế hoạch sản phẩm ở `docs/planning/`.

## Cấu trúc

- `src/image_search/api/v1/`: HTTP routes; hiện có `/health/live`, `/health/ready`; thêm router nghiệp vụ khi triển khai từng feature.
- `src/image_search/modules/`: search, crawling, catalog, ingestion, graph, auth, jobs; nghiệp vụ giao tiếp với hệ ngoài qua ports.
- `src/image_search/adapters/`: PostgreSQL, Qdrant, local object storage; graph/embedding/VLM có chỗ mở rộng.
- `src/image_search/main.py`: app factory và wiring dependencies; `config.py`: cấu hình môi trường.
- `src/image_search/retrieval/`: catalog, ba nhánh retrieval, executor và CLI theo kế hoạch.
- `src/image_search/embedding/`: encoder SigLIP2 dùng chung với image index và CLI mã hóa text/plan.
- `src/image_search/baseline/`: pipeline baseline độc lập; `cli.py` nhận lệnh,
  `records.py` đọc CSV, `download.py` tải ảnh, `benchmark.py` quản lý bộ nhãn,
  `vectors.py` tạo index/tìm kiếm, `keyword.py` tìm BM25 và gộp RRF,
  `evaluate.py` chấm điểm, `utils.py` đọc/ghi file
  và thông tin lần chạy, `settings.py` chứa class `BaselineSettings` đọc cấu hình từ `.env`.
- `migrations/`: Alembic, migration đầu tạo 9 bảng ứng dụng (Alembic thêm bảng version riêng).
- `assets/sample-images/`: fixture PPM tự tạo 2×2, không dùng ảnh riêng.
- `tests/`: unit và integration; `var/`: dữ liệu local ngoài Git.

## Cài đặt và chạy local

Cần Python 3.12, uv và Docker Compose v2. Chạy từ repository root. Docker phải đang hoạt động. Cổng 5432, 6333 và 8000 phải còn trống.

```bash
cp .env.example .env
uv sync --frozen
```

Sửa `.env`: đặt `POSTGRES_PASSWORD` và phần password trong `IMAGE_SEARCH_DATABASE_URL` giống nhau. Nếu password có ký tự đặc biệt thì URL-encode trong database URL. Giá trị `change-me` chỉ là placeholder local. PostgreSQL/Qdrant chỉ bind localhost; API key/model endpoint chưa cần cho phase 0.

```bash
docker compose up -d
uv run alembic upgrade head
uv run uvicorn image_search.main:app --reload --host 127.0.0.1 --port 8000
```

Mở `http://127.0.0.1:8000/docs`. Liveness chỉ kiểm tra process; readiness kiểm tra 9 bảng PostgreSQL, kết nối Qdrant và storage có thể ghi. Readiness trả 503 nếu chưa chạy dịch vụ/migration. Chưa kiểm tra model hoặc active search config vì các phase đó chưa triển khai.

Terminal khác:

```bash
uv run image-search-worker --once
uv run image-search-smoke --api-url http://127.0.0.1:8000
```

Worker phase 0 kiểm tra dependencies rồi thoát; bỏ `--once` để chạy vòng chờ 10 giây, dừng bằng Ctrl+C. Worker chưa claim/xử lý jobs. Smoke decode fixture, lưu immutable object ngoài Git, rồi kiểm tra API readiness; không nhập ảnh vào catalog hoặc tạo vector. Để chỉ kiểm tra fixture/storage khi chưa có dịch vụ, chạy `uv run image-search-smoke`.

Dừng stack bằng `docker compose stop`; khởi động lại bằng `docker compose up -d`. Dữ liệu nằm trong named volumes. Không xóa volumes khi muốn giữ dữ liệu. Schema mới chỉ có ở migration, chưa có tài khoản mặc định hoặc seed model.

## Kiểm tra và build

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run alembic upgrade head --sql
uv build
```

`pytest` chạy unit tests và mặc định skip integration. Với database local dành riêng cho phát triển đã migrate, chạy:

```bash
RUN_INTEGRATION=1 uv run pytest tests/integration
uv run alembic check
```

Integration cần PostgreSQL/Qdrant thật; chỉ chạy trên DB thử nghiệm. Dùng Alembic để thay đổi schema; không dùng `metadata.create_all()` khi chạy app. `uv run alembic revision --autogenerate -m "Describe change"` tạo migration mới để review trước khi apply.

## Ranh giới module

Route validate request và gọi use case; service chứa nghiệp vụ. Adapter chứa client/SQL/I/O và được inject từ composition root. Các module không tự đọc `.env` hoặc tạo network client trong business rules. Giữ ports nhỏ theo use case; chỉ tạo interface/implementation khi dùng đến. `shared/` hiện chứa logging; chỉ thêm helper dùng chung khi có nơi sử dụng thực tế.

## Tài liệu

- [Lộ trình giai đoạn](docs/planning/delivery-plan.md), [PRD](docs/planning/prd.md).
- [Schema 9 bảng](docs/design/data-model.md), [hệ thống](docs/design/system-design.md), [API](docs/design/api-contract.md).
- [Mục lục thiết kế](docs/README.md).

Baseline hiện dùng encoder CPU, tìm kiếm cosine chính xác và không cần VLM API.
Intel RAM chia sẻ 16 GB không được coi là VRAM dedicated. Chất lượng model cần được đo
trên bộ nhãn đã xác nhận; xem hướng dẫn baseline để đổi checkpoint và tạo index mới.


## Frontend thử planner và retrieval

Cài Node.js theo `frontend/.nvmrc` (24.22.2) và npm 11.19.1. Node/npm trong WSL cần được cài trong Linux distro, không chỉ trên Windows. Nếu đã dùng nvm: `cd frontend && nvm install && nvm use`.

```bash
cd frontend
cp .env.example .env.local
npm ci
npm run dev
```

Mở http://127.0.0.1:3000. `BACKEND_ORIGIN` trong `.env.local` trỏ FastAPI (mặc định http://127.0.0.1:8000); chạy backend riêng theo hướng dẫn phía trên. Next.js proxy `/v1/*` và `/health/*` tới backend; thử http://127.0.0.1:3000/health/ready khi backend và DB đang chạy. Khởi động lại Next.js sau khi đổi origin.

```bash
npm run lint
npm run typecheck
npm run format:check
npm run build
npm run start
```

Trang chính đã có playground: nhập query, chọn **Chỉ planner** hoặc **Planner + tìm ảnh**,
xem route, các bước/dependency, ảnh từng target, token và thời gian. Mỗi lần chạy gọi
OpenAI; bấm câu ví dụ chỉ điền text. Dùng prompt hiện hành trong router.py, không tự đổi
sang prompt đang thử trong var/. Mặc định chỉ planner để dễ kiểm tra phân loại.

Backend cho playground (terminal ở repo root, dùng `.env` đã có OPENAI_API_KEY):

```bash
uv sync --frozen --extra baseline --extra planner
docker compose --profile graph up -d qdrant neo4j
HF_HUB_OFFLINE=1 uv run uvicorn image_search.main:app --host 127.0.0.1 --port 8000
```

Cần graph/index đã nhập như hướng dẫn ở trên; không tự xây lại graph hoặc embed ảnh
khi mở giao diện. Model/index được nạp ở lần tìm ảnh đầu tiên và dùng lại trong process.
Chế độ chỉ planner không cần nạp Qdrant/Neo4j/encoder. PostgreSQL không cần cho playground;
readiness scaffold vẫn kiểm tra SQL, tách khỏi khả năng chạy playground.

`start` chạy production build trên port 3000 sau khi dừng dev server. Stack FE giữ nguyên.
Đây là công cụ local để thử chất lượng, không phải auth/API website production.
Chi tiết API và hành vi lỗi ở [frontend/README.md](frontend/README.md).


Vector retrieval của pipeline dùng Qdrant tại `http://localhost:6333`, collection
`image_search_siglip2_v1`. Khởi động bằng `docker compose up -d qdrant`, rồi chạy
`uv run image-search-qdrant` để lập index ảnh trực tiếp vào Qdrant (cần extra `baseline`; dùng lại collection nếu đã có).
Xem [hướng dẫn Qdrant](docs/baseline/baseline-usage.md#lưu-vector-vào-qdrant)
cho cấu hình và nơi lưu dữ liệu. Với collection cũ, chạy
`uv run image-search-qdrant --sync-metadata` một lần để nạp metadata từ nguồn đã pin.
Tên entity, caption, nhãn, các record nguồn và đường dẫn ảnh nằm trong payload Qdrant;
BM25 dựng trong RAM từ payload, dùng cùng thuật toán và RRF 1:1 như trước.
