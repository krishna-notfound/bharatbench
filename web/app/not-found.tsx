import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="flex flex-col items-center gap-4 py-24 text-center">
      <p className="font-mono text-5xl font-semibold tabular-nums text-primary">
        404
      </p>
      <h1 className="text-2xl font-semibold tracking-tight">Page not found</h1>
      <p className="max-w-md text-sm text-muted-foreground">
        That page does not exist. Start a new test or browse earlier runs.
      </p>
      <div className="flex gap-2">
        <Link href="/" className={buttonVariants({ size: "lg" })}>
          New test
        </Link>
        <Link href="/runs" className={buttonVariants({ variant: "outline", size: "lg" })}>
          Runs
        </Link>
      </div>
    </div>
  );
}
