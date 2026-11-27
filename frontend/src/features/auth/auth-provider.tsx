"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import {
  apiRequest,
  ApiError,
  setAccessToken,
  resetSearchOwner,
} from "@/lib/api/client";

export type Account = {
  id: string;
  email: string;
  display_name: string;
  role: "user" | "admin";
  status: "active" | "disabled";
  revision: number;
};
type LoginResult = { user: Account; access_token: string };
const AuthContext = createContext<{
  user: Account | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}>({ user: null, ready: false, login: async () => {}, logout: async () => {} });
let refreshPromise: Promise<LoginResult> | null = null;
let channel: BroadcastChannel | null = null;

export function refreshAccess() {
  if (!refreshPromise) {
    const run = () =>
      apiRequest<LoginResult>("/v1/auth/refresh", {
        method: "POST",
        json: {},
        headers: { "X-Auth-Request": "1" },
      });
    // Lock spans tabs; each refresh reads the newest HttpOnly cookie after acquiring it.
    refreshPromise = (
      navigator.locks
        ? navigator.locks.request("image-search-refresh", run)
        : run()
    )
      .then((result) => {
        setAccessToken(result.access_token);
        window.dispatchEvent(
          new CustomEvent("auth-user", { detail: result.user }),
        );
        return result;
      })
      .catch((error) => {
        setAccessToken(null);
        window.dispatchEvent(new CustomEvent("auth-user", { detail: null }));
        throw error;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Account | null>(null);
  const [ready, setReady] = useState(false);
  const cache = useQueryClient();
  useEffect(() => {
    const listener = (event: Event) =>
      setUser((event as CustomEvent<Account | null>).detail);
    window.addEventListener("auth-user", listener);
    channel = new BroadcastChannel("image-search-auth");
    channel.onmessage = () => {
      setAccessToken(null);
      setUser(null);
      resetSearchOwner();
      cache.clear();
    };
    refreshAccess()
      .catch(() => {})
      .finally(() => setReady(true));
    return () => {
      window.removeEventListener("auth-user", listener);
      channel?.close();
      channel = null;
    };
  }, [cache]);
  async function login(email: string, password: string) {
    const result = await apiRequest<LoginResult>("/v1/auth/login", {
      method: "POST",
      json: { email, password },
      headers: { "X-Auth-Request": "1" },
    });
    setAccessToken(result.access_token);
    setUser(result.user);
    resetSearchOwner();
    cache.clear();
    channel?.postMessage("changed");
  }
  async function logout() {
    await apiRequest("/v1/auth/logout", {
      method: "POST",
      json: {},
      headers: { "X-Auth-Request": "1" },
    });
    setAccessToken(null);
    setUser(null);
    resetSearchOwner();
    cache.clear();
    channel?.postMessage("changed");
  }
  return (
    <AuthContext.Provider value={{ user, ready, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
export function authMessage(error: unknown) {
  if (error instanceof ApiError) {
    const body = error.body as { error?: { message?: string } };
    if (body?.error?.message) return body.error.message;
  }
  return "Không kết nối được máy chủ. Vui lòng thử lại.";
}

export function AccountNav() {
  const { user, ready } = useAuth();
  return (
    <nav
      aria-label="Tài khoản"
      className="flex justify-end gap-4 border-b border-input px-6 py-3 text-sm"
    >
      <Link href="/">Tìm ảnh</Link>
      {user?.role === "admin" && (
        <>
          <Link href="/admin">Quản trị</Link>
          <Link href="/playground">Playground</Link>
        </>
      )}
      {ready && (
        <Link href={user ? "/account" : "/login"}>
          {user?.display_name ?? "Đăng nhập"}
        </Link>
      )}
    </nav>
  );
}
