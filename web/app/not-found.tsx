import Link from "next/link";
import { PRIMARY_CTA, SECONDARY_CTA } from "@/components/shell/surface";

export default function NotFound() {
  return (
    <div className="flex flex-col items-center gap-4 py-24 text-center">
      <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">
        I couldn&apos;t find that page
      </h1>
      <p className="max-w-md text-muted-foreground">
        It may have moved, or the link is mistyped. Start a new test or look at
        your earlier sessions.
      </p>
      <div className="mt-2 flex flex-col gap-3 sm:flex-row">
        <Link href="/new" className={PRIMARY_CTA}>
          New test
        </Link>
        <Link href="/runs" className={SECONDARY_CTA}>
          Sessions
        </Link>
      </div>
    </div>
  );
}
