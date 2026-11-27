"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { fieldClass } from "@/features/auth/account-screen";
export function filtersFromParams(params: {
  get: (key: string) => string | null;
}) {
  return {
    ...(params.get("collection")
      ? { collection_ids: [params.get("collection")] }
      : {}),
    ...(params.get("orientation")
      ? { orientation: params.get("orientation") }
      : {}),
    ...(params.get("min_width")
      ? { min_width: Number(params.get("min_width")) }
      : {}),
    ...(params.get("min_height")
      ? { min_height: Number(params.get("min_height")) }
      : {}),
  };
}
export function SearchFilters() {
  const params = useSearchParams();
  const router = useRouter();
  const { data } = useQuery({
    queryKey: ["collections"],
    queryFn: () =>
      apiRequest<{ items: { id: string; name: string }[] }>("/v1/collections"),
    staleTime: 60000,
  });
  return (
    <form
      aria-label="Bộ lọc ảnh"
      className="flex flex-wrap items-end gap-3 border-b px-6 py-3 text-sm"
      onSubmit={(event) => {
        event.preventDefault();
        const values = new FormData(event.currentTarget);
        const next = new URLSearchParams({ q: params.get("q") ?? "" });
        for (const [key, value] of values)
          if (value) next.set(key, String(value));
        router.push(`/?${next}`);
      }}
    >
      <label className="flex flex-col gap-1">
        Kho ảnh
        <select
          name="collection"
          defaultValue={params.get("collection") ?? ""}
          className={fieldClass}
        >
          <option value="">Tất cả</option>
          {data?.items.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1">
        Hướng ảnh
        <select
          name="orientation"
          defaultValue={params.get("orientation") ?? ""}
          className={fieldClass}
        >
          <option value="">Tất cả</option>
          <option value="landscape">Ngang</option>
          <option value="portrait">Dọc</option>
          <option value="square">Vuông</option>
        </select>
      </label>
      <label className="flex flex-col gap-1">
        Rộng tối thiểu (px)
        <input
          className={`${fieldClass} max-w-36`}
          type="number"
          name="min_width"
          min={1}
          defaultValue={params.get("min_width") ?? ""}
        />
      </label>
      <label className="flex flex-col gap-1">
        Cao tối thiểu (px)
        <input
          className={`${fieldClass} max-w-36`}
          type="number"
          name="min_height"
          min={1}
          defaultValue={params.get("min_height") ?? ""}
        />
      </label>
      <Button variant="outline">Áp dụng</Button>
      <Button
        type="button"
        variant="outline"
        onClick={() =>
          router.push(`/?q=${encodeURIComponent(params.get("q") ?? "")}`)
        }
      >
        Xóa bộ lọc
      </Button>
    </form>
  );
}
