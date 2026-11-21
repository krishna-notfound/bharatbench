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
        <div className="space-y-6">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-80 rounded-xl" />
        </div>
      }
    >
      <Run params={params} />
    </Suspense>
  );
}
