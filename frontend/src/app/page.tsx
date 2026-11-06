import { Button } from "@/components/ui/button";
export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col items-center justify-center gap-6 px-6">
      <h1 className="text-center text-3xl font-semibold tracking-tight">
        Tìm ảnh địa danh
      </h1>
      <div className="flex w-full flex-col gap-3 sm:flex-row">
        <label className="sr-only" htmlFor="query">
          Địa danh cần tìm
        </label>
        <input
          id="query"
          disabled
          placeholder="Tìm ảnh Hạ Long, Cát Bà…"
          className="h-12 min-w-0 flex-1 rounded-full border border-input px-5 text-base disabled:bg-muted"
        />
        <Button disabled className="h-12 rounded-full px-6">
          Tìm kiếm
        </Button>
      </div>
      <p className="text-center text-sm text-muted-foreground">
        Tính năng tìm kiếm đang được chuẩn bị.
      </p>
    </main>
  );
}
