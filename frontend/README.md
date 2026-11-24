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
- `src/lib/api/client.ts`: gọi API cùng origin, không tự thử lại. `src/components/ui/`: UI dùng chung.
- Next proxy `/v1/*` và `/health/*` tới backend, timeout 180 giây. Không đặt khóa hoặc mật khẩu trong
  `NEXT_PUBLIC_*`.
