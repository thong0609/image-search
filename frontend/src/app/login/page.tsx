import { Suspense } from "react";
import { LoginScreen } from "@/features/auth/account-screen";
export default function Page() {
  return (
    <Suspense>
      <LoginScreen />
    </Suspense>
  );
}
