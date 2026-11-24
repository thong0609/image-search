# Frontend playground

Next.js App Router, TypeScript, Tailwind, shadcn/ui configuration, TanStack Query and native fetch. Node version: `.nvmrc`; npm version: `package.json`. Commands and local backend setup are in the repository README. Trang chính là playground local để thử planner và retrieval trên dataset hiện có.

- app: routes/layout; features/playground: giao diện nhập query, kế hoạch và ảnh; components/ui: UI dùng chung.
- lib/api/client.ts: browser-only same-origin fetch transport, forwards AbortSignal, no automatic retries; auth lifecycle is added with the auth feature.
- QueryProvider: one QueryClient per browser mount, retries and refetch-on-focus disabled to avoid recreating search snapshots.
- components.json: shadcn aliases/theme config; Button is the starter component. Run CLI commands from frontend when adding components.
- Copy .env.example to .env.local. BACKEND_ORIGIN is server-side, used by rewrites for /v1/* and /health/*; use the same frontend hostname for auth/cookies during local development. Set FastAPI Origin allowlist to the frontend origin when auth is implemented.
- No model keys or database credentials in NEXT_PUBLIC_* variables. Backend authorization and cache cleanup on logout remain future auth work.

## Cách dùng playground

- Mở `http://127.0.0.1:3000`; backend chạy riêng tại `127.0.0.1:8000`.
- Mặc định **Chỉ planner**: xem route single/multi-target/multi-hop/unclear, steps,
  target_id, conditions, entity và dependency. Chế độ này không nạp encoder/đọc index ảnh.
- **Planner + tìm ảnh**: chọn hybrid (RRF 1:1), vector hoặc keyword; ảnh được trả theo target.
  Chế độ này cần Qdrant/Neo4j đã có dữ liệu, model SigLIP2 local cho vector/hybrid.
- Mỗi lần bấm chạy là một lượt gọi OpenAI bằng prompt hiện hành trong router.py;
  prompt thử nghiệm trong var/ không tự áp dụng. Chỉ bấm câu ví dụ thì chưa gọi API.
- Xem thời gian planner/startup/embedding/retrieval/tổng, token vào/ra và JSON chi tiết.
  Lần tìm ảnh đầu tiên tính cả nạp model/index. Không coi có ảnh là planner đã route đúng.
- Không tự retry request của trình duyệt. Trong lúc chạy nút bị khóa; backend chỉ nhận
  một lượt playground tại một thời điểm. SDK OpenAI giữ retry theo PlannerSettings.
- Khi retrieval lỗi, giữ kế hoạch đã tạo để xem; lỗi OpenAI/quota, cần hỏi lại,
  chưa hỗ trợ và không có kết quả được thể hiện riêng.
- Đây là playground local, chưa phải tích hợp website/auth production. Theo yêu cầu
  mới, phần FE thử nghiệm được làm trước các bước tối ưu/rerank.

API: `POST /v1/playground/run` nhận `{text, mode: "planner" | "search",
method: "hybrid" | "vector" | "keyword"}`; `GET /v1/playground/images/{image_id}`
chỉ đọc ảnh thuộc corpus đã nạp. Không trả đường dẫn local hoặc nhận đường dẫn từ browser.
Mọi key nằm ở backend trong `.env`. Next proxy timeout là 180 giây cho request dài;
không thay timeout/model/prompt của planner. Không cần PostgreSQL cho playground;
`/health/ready` của scaffold vẫn kiểm tra SQL riêng và có thể trả 503 nếu SQL chưa bật.

## Dependency audit at scaffold setup

The installed dependency tree reports 8 moderate advisories in development-only ESLint/typescript-eslint dependencies (minimatch). Runtime dependencies have no reported advisory in this audit. Keep the lockfile and review compatible tooling updates; do not use `npm audit fix --force`, which currently proposes downgrading the Next ESLint config to a different major. This is a point-in-time report; rerun audit when updating dependencies.
