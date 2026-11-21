import { Suspense } from "react";
import Link from "next/link";
import { MessageCircle } from "lucide-react";
import { RunDetail } from "@/components/runs/run-detail";
import { Skeleton } from "@/components/ui/skeleton";

async function Run({ params }: { params: PageProps<"/runs/[id]">["params"] }) {
  const { id } = await params;
  return (
    <>
      <RunDetail key={id} runId={id} />
      <div className="mx-auto mt-6 flex max-w-5xl justify-center">
        <Link
          href={`/chat?run=${encodeURIComponent(id)}`}
          className="inline-flex h-11 items-center gap-2 rounded-full border border-border bg-card px-5 text-sm font-medium outline-none transition-colors hover:bg-accent focus-visible:ring-4 focus-visible:ring-ring/30"
        >
          <MessageCircle className="size-4" /> Ask the agent about this report
        </Link>
      </div>
    </>
  );
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
