"use client";

import type { SearchItem } from "./types";

// Chiều cao hàng mong muốn: điện thoại thấp hơn để vừa hai cột.
const GRID = "flex flex-wrap gap-x-3 gap-y-5 [--row:80px] sm:[--row:200px]";

/** Ảnh quá dài/rộng vẫn giữ trong khung hợp lý để hàng không bị vỡ. */
function ratio(item: SearchItem) {
  if (!item.width || !item.height) return 4 / 3;
  return Math.min(Math.max(item.width / item.height, 0.6), 2.2);
}

type Props = {
  group: string;
  items: SearchItem[];
  selected: string | null;
  onSelect: (id: string) => void;
};

export function ImageGrid({ group, items, selected, onSelect }: Props) {
  return (
    <ul className={GRID}>
      {items.map((item) => {
        // Một ảnh có thể xuất hiện ở nhiều nhóm mục tiêu.
        const key = `${group}:${item.id}`;
        return (
          <li
            key={item.id}
            style={{
              flexGrow: ratio(item),
              flexBasis: `calc(${ratio(item)} * var(--row))`,
            }}
            className="min-w-[130px] max-w-full sm:max-w-[520px]"
          >
            <button
              type="button"
              id={`result-${key}`}
              aria-pressed={selected === key}
              onClick={() => onSelect(key)}
              className="group block w-full cursor-pointer text-left outline-none"
            >
              <span
                style={{ aspectRatio: ratio(item) }}
                className="block w-full overflow-hidden rounded-xl bg-muted group-focus-visible:ring-2 group-focus-visible:ring-ring group-aria-pressed:ring-4 group-aria-pressed:ring-primary"
              >
                {/* eslint-disable-next-line @next/next/no-img-element -- backend đã tạo ảnh thu nhỏ */}
                <img
                  src={`/v1/images/${item.id}/thumbnail`}
                  alt={item.caption || item.title}
                  loading="lazy"
                  decoding="async"
                  className="size-full object-cover transition-opacity group-hover:opacity-90"
                />
              </span>
              <span className="mt-1.5 block truncate text-xs text-muted-foreground">
                {item.source_name ?? "Kho ảnh"}
              </span>
              <span className="block truncate text-sm group-hover:underline">
                {item.title}
              </span>
            </button>
          </li>
        );
      })}
      <li aria-hidden className="h-0 grow-[100]" />
    </ul>
  );
}

export function GridSkeleton() {
  const ratios = [1.5, 1.2, 1.8, 0.8, 1.4, 1.6, 1, 1.5, 1.3, 1.7, 0.9, 1.4];
  return (
    <div aria-hidden className={GRID}>
      {ratios.map((value, index) => (
        <div
          key={index}
          style={{ flexGrow: value, flexBasis: `calc(${value} * var(--row))` }}
          className="min-w-[130px] animate-pulse motion-reduce:animate-none"
        >
          <div style={{ aspectRatio: value }} className="rounded-xl bg-muted" />
          <div className="mt-2 h-3 w-1/3 rounded bg-muted" />
          <div className="mt-2 h-3 w-2/3 rounded bg-muted" />
        </div>
      ))}
    </div>
  );
}
