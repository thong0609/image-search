"use client";

import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { LoaderCircle } from "lucide-react";
import { apiRequest } from "@/lib/api/client";
import { Button } from "@/components/ui/button";

type Status = { status: "preparing" | "ready" | "failed" };

export function ServerPreparation({ children }: { children: ReactNode }) {
  const { data, error, refetch } = useQuery({
    queryKey: ["server-preparation"],
    queryFn: ({ signal }) =>
      apiRequest<Status>("/health/search", {
        signal: AbortSignal.any([signal, AbortSignal.timeout(5000)]),
      }),
    refetchInterval: (query) =>
      query.state.data?.status === "ready" ? 15000 : 1000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
  });

  if (!error && data?.status === "ready") return children;
  if (data?.status === "failed") {
    return (
      <main className="grid min-h-dvh place-content-center gap-4 px-6 text-center">
        <p role="alert">Tìm kiếm chưa sẵn sàng. Vui lòng thử lại sau.</p>
        <Button variant="outline" onClick={() => refetch()}>
          Thử lại
        </Button>
      </main>
    );
  }
  return (
    <div
      role="status"
      aria-label="Đang chuẩn bị máy chủ"
      className="grid min-h-dvh place-items-center"
    >
      <LoaderCircle
        aria-hidden="true"
        className="size-8 animate-spin text-primary"
      />
      <span className="sr-only">Đang chuẩn bị máy chủ</span>
    </div>
  );
}
