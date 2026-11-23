# Images-search

Baseline chạy bằng CLI: CSV → tải ảnh → nhãn đánh giá → vector → tìm kiếm → báo cáo.
Giữ scaffold API/frontend, migration và các adapter hạ tầng để phát triển sau.

## Chạy baseline

Không cần Docker cho baseline. Cài Python 3.12 và uv, sau đó:

```bash
uv sync --frozen --extra baseline
uv run --extra baseline image-search-baseline prepare data/general_10m_part_02_18-11-2026_CHIEU_To_Huy_Thong.csv
uv run --extra baseline image-search-baseline download --limit 20
```

Ảnh và kết quả được lưu trong `var/`, ngoài Git. Bỏ `--limit` để tải toàn bộ;
chạy lại để tiếp tục và thử lại URL lỗi. Đọc các bước còn lại trong
[hướng dẫn chạy baseline](docs/baseline/baseline-usage.md), gồm bước sửa query/đáp án trước khi đo.
Bộ nhãn và quy tắc đánh giá nằm trong [tài liệu benchmark](docs/baseline/benchmark-design.md).

## Scaffold hiện có

Backend modular monolith: một codebase, API và worker chạy riêng. Phase 0 đã có scaffold; crawler/search/auth nghiệp vụ và model handlers triển khai ở các phase sau. hướng dẫn chạy ở `docs/baseline/`, đặc tả hệ thống ở `docs/design/`, kế hoạch sản phẩm ở `docs/planning/`.

## Cấu trúc

- `src/image_search/api/v1/`: HTTP routes; hiện có `/health/live`, `/health/ready`; thêm router nghiệp vụ khi triển khai từng feature.
- `src/image_search/modules/`: search, crawling, catalog, ingestion, graph, auth, jobs; nghiệp vụ giao tiếp với hệ ngoài qua ports.
- `src/image_search/adapters/`: PostgreSQL, Qdrant, local object storage; graph/embedding/VLM có chỗ mở rộng.
- `src/image_search/main.py`: app factory và wiring dependencies; `config.py`: cấu hình môi trường.
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


## Frontend phase 0

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

`start` chạy production build trên port 3000 sau khi dừng dev server. Trang hiện tại chỉ là shell tối giản với search chưa bật; không giả kết quả hoặc gọi model. Stack: Next.js App Router/TypeScript, Tailwind CSS, shadcn config + Button, TanStack Query và fetch. Thư mục theo feature và quy tắc tích hợp ở [frontend/README.md](frontend/README.md). FE scaffold thuộc phase 0; search/grid/grouping/auth/admin được triển khai từ phase tương ứng trong delivery plan. Cả Node và Next.js chạy local riêng Docker DB.
