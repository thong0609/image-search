"use client";

import { useEffect, useRef } from "react";
import { ChevronLeft, ChevronRight, ExternalLink, X } from "lucide-react";
import type { SearchItem } from "./types";

type Props = {
  item: SearchItem;
  onClose: () => void;
  onMove: (step: 1 | -1) => void;
};

const iconButton =
  "grid size-10 cursor-pointer place-items-center rounded-full hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring";

export function ImagePanel({ item, onClose, onMove }: Props) {
  const close = useRef<HTMLButtonElement>(null);

  // Chỉ đưa focus vào panel khi mở, không giật lại khi chuyển ảnh.
  useEffect(() => close.current?.focus({ preventScroll: true }), []);
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.target instanceof HTMLInputElement) return;
      if (event.key === "Escape") onClose();
      else if (event.key === "ArrowLeft") onMove(-1);
      else if (event.key === "ArrowRight") onMove(1);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, onMove]);

  return (
    <aside
      aria-label="Chi tiết ảnh"
      className="fixed inset-0 z-20 overflow-y-auto bg-background lg:sticky lg:inset-auto lg:top-[81px] lg:z-0 lg:h-[calc(100dvh-97px)] lg:w-[40%] lg:shrink-0 lg:rounded-2xl lg:border lg:border-input"
    >
      <div className="sticky top-0 z-10 flex items-center justify-between bg-background/95 px-3 py-2">
        <span className="truncate pl-2 text-sm text-muted-foreground">
          {item.source_name ?? "Kho ảnh"}
        </span>
        <span className="flex shrink-0">
          <button
            type="button"
            aria-label="Ảnh trước"
            onClick={() => onMove(-1)}
            className={iconButton}
          >
            <ChevronLeft size={20} />
          </button>
          <button
            type="button"
            aria-label="Ảnh sau"
            onClick={() => onMove(1)}
            className={iconButton}
          >
            <ChevronRight size={20} />
          </button>
          <button
            ref={close}
            type="button"
            aria-label="Đóng"
            onClick={onClose}
            className={iconButton}
          >
            <X size={20} />
          </button>
        </span>
      </div>
      <div className="grid min-h-60 place-items-center bg-muted">
        {/* eslint-disable-next-line @next/next/no-img-element -- ảnh gốc do backend phục vụ */}
        <img
          key={item.id}
          src={`/v1/images/${item.id}`}
          alt={item.caption || item.title}
          style={{
            backgroundImage: `url(/v1/images/${item.id}/thumbnail)`,
          }}
          className="max-h-[60dvh] w-full bg-contain bg-center bg-no-repeat object-contain"
        />
      </div>
      <div className="space-y-4 p-5">
        <h2 className="text-xl">{item.title}</h2>
        {item.caption && <p className="leading-relaxed">{item.caption}</p>}
        {item.width && item.height && (
          <p className="text-sm text-muted-foreground">
            {item.width} × {item.height}
          </p>
        )}
        {item.source_url && (
          <a
            href={item.source_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex h-10 items-center gap-2 rounded-full bg-primary px-5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Xem trang nguồn <ExternalLink size={15} />
          </a>
        )}
      </div>
    </aside>
  );
}
