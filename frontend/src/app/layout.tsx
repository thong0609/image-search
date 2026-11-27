import type { Metadata } from "next";
import type { ReactNode } from "react";
import { QueryProvider } from "@/lib/providers/query-provider";
import "./globals.css";
import { ServerPreparation } from "@/features/server/server-preparation";
import { AuthProvider, AccountNav } from "@/features/auth/auth-provider";
export const metadata: Metadata = {
  title: "Tìm ảnh",
  description: "Tìm ảnh bằng câu tiếng Việt",
};
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="vi">
      <body>
        <QueryProvider>
          <ServerPreparation>
            <AuthProvider>
              <AccountNav />
              {children}
            </AuthProvider>
          </ServerPreparation>
        </QueryProvider>
      </body>
    </html>
  );
}
