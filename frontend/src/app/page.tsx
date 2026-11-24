import { Suspense } from "react";
import { SearchScreen } from "@/features/search/search-screen";

export default function Home() {
  return (
    <Suspense>
      <SearchScreen />
    </Suspense>
  );
}
