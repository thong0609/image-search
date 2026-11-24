"use client";

import { useRef, useState, type FormEvent } from "react";
import { Search, X } from "lucide-react";

type Props = {
  initial: string;
  onSearch: (query: string) => void;
  autoFocus?: boolean;
};

export function SearchBox({ initial, onSearch, autoFocus }: Props) {
  const [text, setText] = useState(initial);
  const input = useRef<HTMLInputElement>(null);

  function submit(event: FormEvent) {
    event.preventDefault();
    const query = text.trim();
    if (!query) return;
    input.current?.blur();
    onSearch(query);
  }

  return (
    <form
      role="search"
      onSubmit={submit}
      className="flex h-12 w-full items-center rounded-full border border-input bg-background pl-5 pr-2 transition-shadow focus-within:shadow-md hover:shadow-md"
    >
      <input
        ref={input}
        type="text"
        value={text}
        onChange={(event) => setText(event.target.value)}
        maxLength={500}
        autoFocus={autoFocus}
        enterKeyHint="search"
        aria-label="Bạn muốn tìm ảnh gì?"
        placeholder="Bạn muốn tìm ảnh gì?"
        className="min-w-0 flex-1 bg-transparent text-base outline-none placeholder:text-muted-foreground"
      />
      {text && (
        <button
          type="button"
          aria-label="Xóa câu tìm kiếm"
          onClick={() => {
            setText("");
            input.current?.focus();
          }}
          className="grid size-9 cursor-pointer place-items-center rounded-full text-muted-foreground hover:bg-muted"
        >
          <X size={18} />
        </button>
      )}
      <button
        type="submit"
        aria-label="Tìm kiếm"
        className="grid size-9 cursor-pointer place-items-center rounded-full text-primary hover:bg-muted"
      >
        <Search size={20} />
      </button>
    </form>
  );
}
