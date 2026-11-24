import type { Metadata } from "next";
import { Playground } from "@/features/playground/playground";

export const metadata: Metadata = { title: "Playground · Tìm ảnh" };

export default function PlaygroundPage() {
  return <Playground />;
}
