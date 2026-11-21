import { Suspense } from "react";
import { RunDetail } from "@/components/runs/run-detail";
import { Skeleton } from "@/components/ui/skeleton";

async function Run({ params }: { params: PageProps<"/runs/[id]">["params"] }) {
  const { id } = await params;
  return <RunDetail key={id} runId={id} />;
}

export default function RunPage({ params }: PageProps<"/runs/[id]">) {
  return (
    <Suspense
      fallback={
        <div className="mx-auto max-w-5xl space-y-6 py-8">
          <Skeleton className="mx-auto size-24 rounded-full" />
          <Skeleton className="mx-auto h-6 w-64" />
          <Skeleton className="h-40 rounded-3xl" />
        </div>
      }
    >
      <Run params={params} />
    </Suspense>
  );
}
