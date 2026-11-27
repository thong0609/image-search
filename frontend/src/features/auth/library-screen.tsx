"use client";
import { useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { useAuth, authMessage } from "./auth-provider";
type Item = {
  id: string;
  title: string;
  lifecycle: string;
  metadata_revision: number;
  current_version: number | null;
};
export function LibraryScreen() {
  const { user, ready } = useAuth();
  if (!ready) return <p className="p-8">Đang kiểm tra tài khoản…</p>;
  if (!user)
    return (
      <p className="p-8">
        <Link href="/login?returnTo=/admin/images">Đăng nhập để quản trị</Link>
      </p>
    );
  if (user.role !== "admin")
    return <p className="p-8">Bạn không có quyền quản trị.</p>;
  return <Library />;
}
function Library() {
  const [cursor, setCursor] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const cache = useQueryClient();
  const { data, error, isPending } = useQuery({
    queryKey: ["admin-images", cursor],
    queryFn: () =>
      apiRequest<{ items: Item[]; next_cursor: string | null }>(
        `/v1/admin/images?limit=30${cursor ? `&cursor=${cursor}` : ""}`,
      ),
  });
  async function remove(item: Item) {
    if (!window.confirm(`Gỡ ảnh “${item.title}” khỏi kho công khai?`)) return;
    setBusy(true);
    setMessage("");
    try {
      await apiRequest(`/v1/admin/images/${item.id}`, {
        method: "DELETE",
        headers: { "If-Match": `"${item.metadata_revision}"` },
      });
      await cache.invalidateQueries({ queryKey: ["admin-images"] });
      cache.removeQueries({ queryKey: ["search"] });
      setMessage("Đã gỡ ảnh khỏi tìm kiếm, xem và tải ảnh.");
    } catch (error) {
      setMessage(authMessage(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="mx-auto max-w-6xl space-y-6 px-5 py-10">
      <h1 className="text-3xl font-semibold">Quản trị kho ảnh</h1>
      <nav className="flex gap-5 border-b pb-4">
        <Link href="/admin">Tài khoản</Link>
        <Link href="/admin/images">Kho ảnh</Link>
        <Link href="/admin/imports">Nhập CSV</Link>
      </nav>
      <p className="text-muted-foreground">
        Ảnh đã gỡ không còn xuất hiện trong kết quả mới và không thể xem hoặc
        tải từ website.
      </p>
      {message && <p role="status">{message}</p>}
      {error && <p role="alert">{authMessage(error)}</p>}
      {isPending ? (
        <p>Đang tải kho ảnh…</p>
      ) : (
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {data?.items.map((item) => (
            <article
              key={item.id}
              className="overflow-hidden rounded-xl border border-input"
            >
              {item.lifecycle === "active" && (
                <>
                  {/* eslint-disable-next-line @next/next/no-img-element -- thumbnail served by API */}
                  <img
                    src={`/v1/images/${item.id}/thumbnail`}
                    alt={item.title}
                    className="h-40 w-full object-cover"
                    loading="lazy"
                  />
                </>
              )}
              <div className="space-y-3 p-4">
                <h2>{item.title}</h2>
                <p className="text-sm text-muted-foreground">
                  {item.lifecycle === "active" ? "Đang công bố" : "Đã gỡ"} ·
                  phiên bản {item.current_version}
                </p>
                <Button
                  variant="outline"
                  disabled={busy || item.lifecycle !== "active"}
                  onClick={() => remove(item)}
                >
                  Gỡ khỏi kho
                </Button>
              </div>
            </article>
          ))}
        </div>
      )}
      <div className="flex gap-3">
        <Button
          variant="outline"
          disabled={!cursor}
          onClick={() => setCursor(null)}
        >
          Về đầu
        </Button>
        <Button
          variant="outline"
          disabled={!data?.next_cursor}
          onClick={() => setCursor(data?.next_cursor ?? null)}
        >
          Trang sau
        </Button>
      </div>
    </main>
  );
}
