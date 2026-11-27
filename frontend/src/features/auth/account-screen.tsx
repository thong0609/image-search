"use client";

import { useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { apiRequest } from "@/lib/api/client";
import { useAuth, authMessage } from "./auth-provider";

export const fieldClass =
  "w-full rounded-lg border border-input bg-background px-3 py-2 outline-offset-2";
export function LoginScreen() {
  const { login } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const data = new FormData(event.currentTarget);
    try {
      await login(String(data.get("email")), String(data.get("password")));
      const target = params.get("returnTo") ?? "/";
      const parsed = new URL(target, window.location.origin);
      router.replace(
        parsed.origin === window.location.origin &&
          target.startsWith("/") &&
          !target.startsWith("//")
          ? parsed.pathname + parsed.search
          : "/",
      );
    } catch (error) {
      setError(authMessage(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="mx-auto max-w-md space-y-6 px-5 py-16">
      <h1 className="text-3xl font-semibold">Đăng nhập</h1>
      <p className="text-muted-foreground">
        Đăng nhập để xem chi tiết và tải ảnh trong kho.
      </p>
      <form onSubmit={submit} className="space-y-5">
        <label className="block space-y-2">
          <span>Email</span>
          <input
            className={fieldClass}
            name="email"
            type="email"
            autoComplete="username"
            required
            maxLength={254}
          />
        </label>
        <label className="block space-y-2">
          <span>Mật khẩu</span>
          <input
            className={fieldClass}
            name="password"
            type="password"
            autoComplete="current-password"
            required
            maxLength={1024}
          />
        </label>
        {error && (
          <p role="alert" className="text-red-700">
            {error}
          </p>
        )}
        <Button type="submit" disabled={busy}>
          {busy ? "Đang đăng nhập…" : "Đăng nhập"}
        </Button>
      </form>
      <p className="text-sm text-muted-foreground">
        Liên hệ quản trị viên để được cấp tài khoản hoặc hỗ trợ mật khẩu.
      </p>
      <Link href="/" className="text-primary">
        Tiếp tục tìm ảnh với tư cách khách
      </Link>
    </main>
  );
}

export function AccountScreen() {
  const { user, ready, logout } = useAuth();
  const router = useRouter();
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  if (!ready) return <p className="p-8">Đang kiểm tra tài khoản…</p>;
  if (!user)
    return (
      <main className="p-8">
        <Link href="/login?returnTo=/account">Đăng nhập để xem tài khoản</Link>
      </main>
    );
  async function change(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    const form = new FormData(event.currentTarget);
    if (form.get("new_password") !== form.get("confirm")) {
      setMessage("Mật khẩu nhập lại không khớp.");
      setBusy(false);
      return;
    }
    try {
      await apiRequest("/v1/auth/change-password", {
        method: "POST",
        json: {
          current_password: form.get("current_password"),
          new_password: form.get("new_password"),
        },
      });
      await logout();
      router.replace("/login");
    } catch (error) {
      setMessage(authMessage(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="mx-auto max-w-lg space-y-7 px-5 py-12">
      <h1 className="text-3xl font-semibold">Tài khoản</h1>
      <div>
        <p>{user.display_name}</p>
        <p className="text-muted-foreground">
          {user.email} ·{" "}
          {user.role === "admin" ? "Quản trị viên" : "Người dùng"}
        </p>
      </div>
      <form className="space-y-4" onSubmit={change}>
        <h2 className="text-xl">Đổi mật khẩu</h2>
        {[
          ["current_password", "Mật khẩu hiện tại"],
          ["new_password", "Mật khẩu mới (ít nhất 12 ký tự)"],
          ["confirm", "Nhập lại mật khẩu mới"],
        ].map(([name, label]) => (
          <label key={name} className="block space-y-2">
            <span>{label}</span>
            <input
              className={fieldClass}
              name={name}
              type="password"
              autoComplete={
                name === "current_password"
                  ? "current-password"
                  : "new-password"
              }
              required
              minLength={name === "current_password" ? 1 : 12}
              maxLength={1024}
            />
          </label>
        ))}
        <p className="text-sm text-muted-foreground">
          Đổi mật khẩu sẽ đăng xuất trên mọi thiết bị.
        </p>
        <Button disabled={busy}>Đổi mật khẩu</Button>
      </form>
      {message && (
        <p role="alert" className="text-red-700">
          {message}
        </p>
      )}
      <Button
        variant="outline"
        onClick={async () => {
          try {
            await logout();
            router.replace("/");
          } catch (error) {
            setMessage(authMessage(error));
          }
        }}
      >
        Đăng xuất
      </Button>
    </main>
  );
}
