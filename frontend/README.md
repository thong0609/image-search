# Frontend

Next.js App Router, TypeScript, Tailwind, shadcn/ui, TanStack Query và fetch. Phiên bản Node ở `.nvmrc`,
npm ở `package.json`. Cách chạy ở [hướng dẫn tìm kiếm](../docs/guides/search.md#giao-diện).

```bash
cp .env.example .env.local   # BACKEND_ORIGIN, mặc định http://127.0.0.1:8000
npm ci && npm run dev
npm run lint && npm run typecheck && npm run format:check && npm run build
```

- `src/features/search/`: màn hình tìm ảnh (`/`): ô tìm kiếm, lưới ảnh, panel chi tiết.
- `src/features/playground/`: xem kế hoạch và từng bước (`/playground`), CSS riêng.
- `src/lib/api/client.ts`: gọi API cùng origin; refresh một lần khi access token hết hạn. `src/components/ui/`: UI dùng chung.
- Next proxy `/v1/*` và `/health/*` tới backend, timeout 180 giây. Không đặt khóa hoặc mật khẩu trong
  `NEXT_PUBLIC_*`.

Website hiện có `/login`, `/account`, `/admin`, `/admin/images`, `/admin/imports`; `/playground` cần admin.
Backend phải migrate PostgreSQL, khởi tạo khóa, đồng bộ catalog và tạo admin trước khi đăng nhập.
Xem [hướng dẫn website](../docs/guides/website.md). Access token chỉ giữ trong memory;
refresh cookie HttpOnly, các thao tác ảnh gốc dùng bearer token qua proxy backend.
