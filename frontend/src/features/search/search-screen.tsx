"use client";

import { useCallback, useState, type ReactNode } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { apiRequest, ApiError } from "@/lib/api/client";
import { GridSkeleton, ImageGrid } from "./image-grid";
import { ImagePanel } from "./image-panel";
import { SearchBox } from "./search-box";
import type { SearchResponse } from "./types";

const EXAMPLES = [
  "Ảnh mặt nước có thuyền ở Bến thuyền Tràng An Ninh Bình",
  "1 ảnh chợ nổi Cái Răng và 1 ảnh đền ở Tuyên Quang",
  "Ảnh nhân viên bán bánh bao trong bến xe ở Hà Nội có mặt tiền bật đèn chữ xanh ban đêm",
];

function errorMessage(error: unknown) {
  if (error instanceof ApiError && error.status === 503)
    return "Tìm kiếm chưa sẵn sàng. Kiểm tra backend, Qdrant và Neo4j rồi thử lại.";
  if (error instanceof ApiError && error.status === 422)
    return "Câu tìm kiếm không hợp lệ hoặc dài quá 500 ký tự.";
  return "Không kết nối được máy chủ. Vui lòng thử lại.";
}

function Brand({ large = false }: { large?: boolean }) {
  return (
    <Link
      href="/"
      className={
        large
          ? "text-5xl font-semibold tracking-tight sm:text-6xl"
          : "shrink-0 text-2xl font-semibold tracking-tight"
      }
    >
      tìm<span className="text-primary">ảnh</span>
    </Link>
  );
}

export function SearchScreen() {
  const router = useRouter();
  const query = (useSearchParams().get("q") ?? "").trim();
  const search = useCallback(
    (text: string) => router.push(`/?q=${encodeURIComponent(text)}`),
    [router],
  );

  if (!query) return <Landing onSearch={search} />;
  // key: câu mới thì bỏ ảnh đang chọn và đồng bộ lại ô tìm kiếm.
  return <Results key={query} query={query} onSearch={search} />;
}

function Landing({ onSearch }: { onSearch: (query: string) => void }) {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-8 px-4 pb-32">
      <h1>
        <Brand large />
      </h1>
      <div className="w-full max-w-xl">
        <SearchBox initial="" onSearch={onSearch} autoFocus />
      </div>
      <div className="flex max-w-3xl flex-wrap justify-center gap-2">
        {EXAMPLES.map((example) => (
          <button
            key={example}
            type="button"
            onClick={() => onSearch(example)}
            className="cursor-pointer rounded-full bg-muted px-4 py-2 text-left text-sm hover:bg-input focus-visible:outline-2 focus-visible:outline-ring"
          >
            {example}
          </button>
        ))}
      </div>
    </main>
  );
}

type ResultsProps = { query: string; onSearch: (query: string) => void };

function Results({ query, onSearch }: ResultsProps) {
  const [selected, setSelected] = useState<string | null>(null);
  const { data, error, isFetching, refetch } = useQuery({
    queryKey: ["search", query],
    queryFn: ({ signal }) =>
      apiRequest<SearchResponse>("/v1/search", {
        method: "POST",
        json: { query },
        signal,
      }),
    // Mỗi lượt tìm gọi planner có phí: quay lại câu cũ thì dùng lại kết quả.
    staleTime: Infinity,
  });

  const groups = data?.groups ?? [];
  const items = groups.flatMap((group) =>
    group.items.map((item) => ({ key: `${group.id}:${item.id}`, item })),
  );
  const current = items.findIndex((entry) => entry.key === selected);

  const close = useCallback(() => {
    setSelected(null);
    if (current >= 0)
      document.getElementById(`result-${items[current].key}`)?.focus();
  }, [current, items]);
  const move = useCallback(
    (step: 1 | -1) => {
      const next = items[current + step];
      if (!next) return;
      setSelected(next.key);
      document
        .getElementById(`result-${next.key}`)
        ?.scrollIntoView({ block: "nearest" });
    },
    [current, items],
  );

  return (
    <>
      <header className="sticky top-0 z-10 flex items-center gap-4 border-b border-input bg-background px-4 py-4 sm:gap-8 sm:px-6">
        <Brand />
        <div className="min-w-0 max-w-2xl flex-1">
          <SearchBox initial={query} onSearch={onSearch} />
        </div>
      </header>
      <div className="flex items-start gap-5 px-4 py-4 sm:px-6">
        <main className="min-w-0 flex-1" aria-busy={isFetching}>
          <div role="status" className="sr-only">
            {isFetching
              ? "Đang tìm ảnh"
              : data && `Tìm thấy ${items.length} ảnh`}
          </div>
          {isFetching ? (
            <>
              <p className="mb-4 text-sm text-muted-foreground">
                Đang phân tích câu hỏi và tìm ảnh, có thể mất hơn 10 giây…
              </p>
              <GridSkeleton />
            </>
          ) : error ? (
            <Message title={errorMessage(error)}>
              <Button variant="outline" onClick={() => refetch()}>
                Thử lại
              </Button>
            </Message>
          ) : data?.question ? (
            <Message title={data.question}>
              <p className="text-muted-foreground">
                Hãy viết lại câu tìm kiếm rõ hơn ở ô phía trên.
              </p>
            </Message>
          ) : items.length === 0 ? (
            <Message title="Không có ảnh phù hợp." />
          ) : (
            <div className="space-y-10">
              {groups.map((group) => (
                <section key={group.id} aria-label={group.label}>
                  {groups.length > 1 && (
                    <h2 className="mb-3 text-lg">{group.label}</h2>
                  )}
                  {group.approximate && (
                    <p className="mb-3 text-sm text-muted-foreground">
                      Chưa xác định được đúng nơi bạn tìm, đây là các ảnh gần
                      nhất.
                    </p>
                  )}
                  <ImageGrid
                    group={group.id}
                    items={group.items}
                    selected={selected}
                    onSelect={setSelected}
                  />
                </section>
              ))}
            </div>
          )}
        </main>
        {current >= 0 && (
          <ImagePanel
            item={items[current].item}
            onClose={close}
            onMove={move}
          />
        )}
      </div>
    </>
  );
}

function Message({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="mx-auto flex max-w-xl flex-col items-center gap-4 py-20 text-center">
      <p className="text-lg">{title}</p>
      {children}
    </div>
  );
}
