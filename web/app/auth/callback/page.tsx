import type { Metadata } from "next";
import { Suspense } from "react";
import { CallbackView } from "@/components/auth/callback-view";

export const metadata: Metadata = { title: "Signing in — BharatBench" };

export default function AuthCallbackPage() {
  return (
    <Suspense fallback={null}>
      <CallbackView />
    </Suspense>
  );
}
