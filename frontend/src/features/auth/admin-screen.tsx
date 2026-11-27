"use client";

import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { apiRequest } from "@/lib/api/client";
import { useAuth, authMessage, type Account } from "./auth-provider";
import { fieldClass } from "./account-screen";

export function AdminScreen() {
  const { user, ready } = useAuth();
  if (!ready) return <p className="p-8">Đang kiểm tra tài khoản…</p>;
  if (!user)
    return (
      <p className="p-8">
        <Link href="/login?returnTo=/admin">Đăng nhập để quản trị</Link>
      </p>
    );
  if (user.role !== "admin")
    return <p className="p-8">Bạn không có quyền quản trị.</p>;
  return (
    <main className="mx-auto max-w-6xl space-y-8 px-5 py-10">
      <h1 className="text-3xl font-semibold">Quản trị</h1>
      <nav className="flex gap-5 border-b pb-4">
        <Link href="/admin">Tài khoản</Link>
        <Link href="/admin/images">Kho ảnh</Link>
        <Link href="/admin/imports">Nhập CSV</Link>
      </nav>
      <Users />
    </main>
  );
}

function Users() {
  const cache = useQueryClient();
  const [cursor, setCursor] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const { data, error, isPending } = useQuery({
    queryKey: ["admin-users", cursor],
    queryFn: () =>
      apiRequest<{ items: Account[]; next_cursor: string | null }>(
        `/v1/admin/users?limit=50${cursor ? `&cursor=${cursor}` : ""}`,
      ),
  });
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    const form = event.currentTarget;
    const values = Object.fromEntries(new FormData(form));
    try {
      await apiRequest("/v1/admin/users", { method: "POST", json: values });
      form.reset();
      await cache.invalidateQueries({ queryKey: ["admin-users"] });
      setMessage("Đã tạo tài khoản.");
    } catch (error) {
      setMessage(authMessage(error));
    } finally {
      setBusy(false);
    }
  }
  async function update(account: Account, changes: object) {
    setBusy(true);
    setMessage("");
    try {
      await apiRequest(`/v1/admin/users/${account.id}`, {
        method: "PATCH",
        headers: { "If-Match": `"${account.revision}"` },
        json: changes,
      });
      await cache.invalidateQueries({ queryKey: ["admin-users"] });
    } catch (error) {
      setMessage(authMessage(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <section className="rounded-xl border border-input p-5">
        <h2 className="mb-5 text-xl">Cấp tài khoản</h2>
        <form
          onSubmit={create}
          className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
        >
          <label>
            Họ tên
            <input
              className={fieldClass}
              name="display_name"
              required
              maxLength={100}
            />
          </label>
          <label>
            Email
            <input
              className={fieldClass}
              name="email"
              type="email"
              required
              maxLength={254}
            />
          </label>
          <label>
            Mật khẩu ban đầu
            <input
              className={fieldClass}
              name="initial_password"
              type="password"
              autoComplete="new-password"
              minLength={12}
              maxLength={1024}
              required
            />
          </label>
          <label>
            Vai trò
            <select className={fieldClass} name="role">
              <option value="user">Người dùng</option>
              <option value="admin">Quản trị viên</option>
            </select>
          </label>
          <Button disabled={busy}>Tạo tài khoản</Button>
        </form>
      </section>
      {message && <p role="status">{message}</p>}
      {error && <p role="alert">{authMessage(error)}</p>}
      {isPending ? (
        <p>Đang tải…</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <caption className="mb-4 text-left text-xl">
              Danh sách tài khoản
            </caption>
            <thead>
              <tr>
                {["Tên / email", "Vai trò", "Trạng thái", "Thao tác"].map(
                  (label) => (
                    <th key={label} className="border-b p-3">
                      {label}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {data?.items.map((account) => (
                <tr key={account.id}>
                  <td className="border-b p-3">
                    {account.display_name}
                    <br />
                    <span className="text-sm text-muted-foreground">
                      {account.email}
                    </span>
                  </td>
                  <td className="border-b p-3">
                    {account.role === "admin" ? "Quản trị viên" : "Người dùng"}
                  </td>
                  <td className="border-b p-3">
                    {account.status === "active" ? "Hoạt động" : "Đã khóa"}
                  </td>
                  <td className="space-x-2 border-b p-3">
                    <Button
                      variant="outline"
                      disabled={busy}
                      onClick={() => {
                        if (
                          window.confirm(
                            `Đổi vai trò của ${account.email}? Tài khoản sẽ phải đăng nhập lại.`,
                          )
                        )
                          void update(account, {
                            role: account.role === "admin" ? "user" : "admin",
                          });
                      }}
                    >
                      Đổi vai trò
                    </Button>
                    <Button
                      variant="outline"
                      disabled={busy}
                      onClick={() => {
                        if (
                          window.confirm(
                            `${account.status === "active" ? "Khóa" : "Mở khóa"} ${account.email}?`,
                          )
                        )
                          void update(account, {
                            status:
                              account.status === "active"
                                ? "disabled"
                                : "active",
                          });
                      }}
                    >
                      {account.status === "active" ? "Khóa" : "Mở khóa"}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
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
    </>
  );
}
