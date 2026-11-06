# Images-search

Tìm ảnh địa danh tiếng Việt bằng vector + keyword + graph và VLM rerank. Backend modular monolith: một codebase, API và worker chạy riêng. Phase 0 đã có scaffold; crawler/search/auth nghiệp vụ và model handlers triển khai ở các phase sau.

## Cấu trúc

- `src/image_search/api/v1/`: HTTP routes; hiện có `/health/live`, `/health/ready`; thêm router nghiệp vụ khi triển khai từng feature.
- `src/image_search/modules/`: search, crawling, catalog, ingestion, graph, auth, jobs; nghiệp vụ giao tiếp với hệ ngoài qua ports.
- `src/image_search/adapters/`: PostgreSQL, Qdrant, local object storage; graph/embedding/VLM có chỗ mở rộng.
- `src/image_search/main.py`: app factory và wiring dependencies; `config.py`: cấu hình môi trường.
- `migrations/`: Alembic, migration đầu tạo 9 bảng ứng dụng (Alembic thêm bảng version riêng).
- `configs/`: cấu hình nguồn ví dụ, crawler mặc định tắt.
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

- [Lộ trình giai đoạn](docs/delivery-plan.md), [MVP địa danh](docs/landmark-mvp-plan.md), [PRD](docs/prd.md).
- [Schema 9 bảng](docs/data-model.md), [hệ thống](docs/system-design.md), [API](docs/api-contract.md).
- [Mục lục thiết kế](docs/README.md).

Chưa có dataset/crawl/model thực tế. Local ban đầu dùng encoder CPU và VLM API ở phase tương ứng; Intel RAM chia sẻ 16 GB không được coi là VRAM dedicated. Ngân sách và checkpoint vẫn cần chốt.


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
