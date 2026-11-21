import type { Metadata } from "next";
import { RunsList } from "@/components/runs/runs-list";

export const metadata: Metadata = { title: "Sessions — BharatBench" };

export default function RunsPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-8 py-8 md:py-12">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">
          Sessions
        </h1>
        <p className="mt-2 text-muted-foreground">
          Every test you have started, newest first.
        </p>
      </div>
      <RunsList />
    </div>
  );
}
