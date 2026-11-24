import type { Metadata } from "next";
import type { ReactNode } from "react";
import { QueryProvider } from "@/lib/providers/query-provider";
import "./globals.css";
export const metadata: Metadata = {
  title: "Tìm ảnh",
  description: "Tìm ảnh bằng câu tiếng Việt",
};
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="vi">
      <body>
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
