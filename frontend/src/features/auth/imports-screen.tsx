"use client";
import { useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest, mediaRequest } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { useAuth, authMessage } from "./auth-provider";
import { fieldClass } from "./account-screen";
type Summary = {
  import_id: string;
  status: string;
  total: number;
  counts: Record<string, number>;
  error: string | null;
};
type Item = {
  id: string;
  line: number;
  entity_name: string;
  status: string;
  stage: string;
  error: string | null;
  retryable: boolean;
};
const labels: Record<string, string> = {
  pending: "Chờ xử lý",
  running: "Đang xử lý",
  succeeded: "Hoàn tất",
  failed: "Có lỗi",
  skipped: "Bỏ qua",
};
export function ImportsScreen() {
  const { user, ready } = useAuth();
  if (!ready) return <p className="p-8">Đang kiểm tra tài khoản…</p>;
  if (!user)
    return (
      <p className="p-8">
        <Link href="/login?returnTo=/admin/imports">Đăng nhập để nhập ảnh</Link>
      </p>
    );
  if (user.role !== "admin")
    return <p className="p-8">Bạn không có quyền quản trị.</p>;
  return <Imports />;
}
function Imports() {
  const cache = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [preview, setPreview] = useState<{
    total: number;
    counts: Record<string, number>;
    errors: { line: number; message: string }[];
  } | null>(null);
  const [collection, setCollection] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const { data: collections } = useQuery({
    queryKey: ["collections"],
    queryFn: () =>
      apiRequest<{ items: { id: string; name: string }[] }>("/v1/collections"),
  });
  const { data: recent } = useQuery({
    queryKey: ["imports"],
    queryFn: () => apiRequest<{ items: Summary[] }>("/v1/admin/imports"),
    refetchInterval: 3000,
  });
  const { data: report } = useQuery({
    queryKey: ["import", selected],
    enabled: !!selected,
    queryFn: () =>
      apiRequest<Summary & { items: Item[] }>(`/v1/admin/imports/${selected}`),
    refetchInterval: 3000,
  });
  async function upload(start: boolean) {
    if (!file) return;
    setBusy(true);
    setError("");
    const form = new FormData();
    form.set("file", file);
    try {
      if (start) {
        form.set(
          "collection_id",
          collection || collections?.items[0]?.id || "",
        );
        const result = await apiRequest<{ import_id: string }>(
          "/v1/admin/imports",
          { method: "POST", form, headers: { "Idempotency-Key": key } },
        );
        setSelected(result.import_id);
        await cache.invalidateQueries({ queryKey: ["imports"] });
      } else
        setPreview(
          await apiRequest("/v1/admin/imports/preview", {
            method: "POST",
            form,
          }),
        );
    } catch (error) {
      setError(authMessage(error));
    } finally {
      setBusy(false);
    }
  }
  async function retry() {
    if (!report) return;
    setBusy(true);
    setError("");
    try {
      const ids = report.items
        .filter((i) => i.retryable && i.status === "failed")
        .map((i) => i.id);
      for (let n = 0; n < Math.max(ids.length, 1); n += 100)
        await apiRequest(`/v1/admin/imports/${selected}/retry`, {
          method: "POST",
          json: { item_ids: ids.slice(n, n + 100) },
        });
      await cache.invalidateQueries({ queryKey: ["import", selected] });
    } catch (error) {
      setError(authMessage(error));
    } finally {
      setBusy(false);
    }
  }
  async function downloadErrors() {
    try {
      const blob = await mediaRequest(
        `/v1/admin/imports/${selected}/errors.csv`,
      );
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "import-errors.csv";
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      setError(authMessage(error));
    }
  }
  return (
    <main className="mx-auto max-w-6xl space-y-6 px-5 py-10">
      <h1 className="text-3xl font-semibold">Nhập ảnh từ CSV</h1>
      <nav className="flex gap-5 border-b pb-4">
        <Link href="/admin">Tài khoản</Link>
        <Link href="/admin/images">Kho ảnh</Link>
        <Link href="/admin/imports">Nhập CSV</Link>
      </nav>
      <section className="space-y-4 rounded-xl border border-input p-5">
        <p>
          CSV UTF-8, tối đa 10 MiB / 10.000 dòng. Chỉ xử lý dòng approve=yes.
          Bạn có thể đóng trang khi lượt nhập đang chạy.
        </p>
        <p className="break-words text-sm text-muted-foreground">
          Các cột: entity_id, entity_name, leaf_label, image_url, image_width,
          image_height, page_url, page_title, image_domain, mo_ta, approve.
        </p>
        <label className="block">
          File CSV
          <input
            type="file"
            accept=".csv,text/csv"
            className={fieldClass}
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              setPreview(null);
              setKey(crypto.randomUUID());
            }}
          />
        </label>
        <label className="block">
          Kho nhận ảnh
          <select
            className={fieldClass}
            value={collection}
            onChange={(event) => setCollection(event.target.value)}
          >
            {collections?.items.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <div className="flex gap-3">
          <Button disabled={!file || busy} onClick={() => upload(false)}>
            Kiểm tra CSV
          </Button>
          <Button disabled={!preview || busy} onClick={() => upload(true)}>
            Bắt đầu nhập
          </Button>
        </div>
        {preview && (
          <div>
            <p>
              {preview.total} dòng · {preview.counts.pending ?? 0} hợp lệ ·{" "}
              {preview.counts.skipped ?? 0} bỏ qua ·{" "}
              {preview.counts.failed ?? 0} lỗi
            </p>
            {preview.errors.slice(0, 20).map((e) => (
              <p key={e.line} className="text-sm text-red-700">
                Dòng {e.line}: {e.message}
              </p>
            ))}
          </div>
        )}
      </section>
      {error && (
        <p role="alert" className="text-red-700">
          {error}
        </p>
      )}
      <section>
        <h2 className="mb-3 text-xl">Lịch sử nhập</h2>
        <div className="space-y-2">
          {recent?.items.map((r) => (
            <button
              key={r.import_id}
              onClick={() => setSelected(r.import_id)}
              className="block w-full rounded-lg border border-input p-3 text-left"
            >
              {labels[r.status] ?? r.status} · {r.total} dòng · hoàn tất{" "}
              {r.counts.succeeded ?? 0}, lỗi {r.counts.failed ?? 0}, bỏ qua{" "}
              {r.counts.skipped ?? 0}
              <span className="block text-xs text-muted-foreground">
                {r.import_id}
              </span>
            </button>
          ))}
        </div>
      </section>
      {report && (
        <section className="space-y-4">
          <h2 className="text-xl">
            Chi tiết: {labels[report.status] ?? report.status}
          </h2>
          {report.error && <p role="alert">{report.error}</p>}
          <div className="flex gap-3">
            <Button variant="outline" onClick={downloadErrors}>
              Tải danh sách lỗi
            </Button>
            <Button
              disabled={busy || report.status !== "failed"}
              onClick={retry}
            >
              Thử lại phần lỗi
            </Button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr>
                  {["Dòng", "Nơi / thực thể", "Trạng thái", "Chi tiết"].map(
                    (x) => (
                      <th className="border-b p-2" key={x}>
                        {x}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {report.items.map((i) => (
                  <tr key={i.id}>
                    <td className="border-b p-2">{i.line}</td>
                    <td className="border-b p-2">{i.entity_name}</td>
                    <td className="border-b p-2">
                      {labels[i.status] ?? i.status}
                    </td>
                    <td className="border-b p-2">
                      {i.error ??
                        {
                          staged: "Đã embedding, chờ công bố",
                          published: "Đã công bố",
                          validation: "Kiểm tra CSV",
                        }[i.stage] ??
                        i.stage}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </main>
  );
}
