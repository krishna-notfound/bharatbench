import { StartTest } from "@/components/home/start-test";
import { CARD } from "@/components/shell/surface";
import { cn } from "@/lib/utils";

const STEPS = [
  { t: "Add your app", d: "Drop an APK or paste a GitHub link." },
  { t: "Watch it run", d: "A live phone taps through your app under real-world strain." },
  { t: "Get the fixes", d: "Crashes and freezes, ranked by who they hurt." },
];

export function HomeHero() {
  return (
    <div className="space-y-12 md:space-y-16">
      <section className="space-y-8 text-center">
        <div className="mx-auto max-w-2xl space-y-4">
          <h1 className="text-4xl font-semibold tracking-tight md:text-6xl">
            The Real Phone Test
          </h1>
          <p className="text-base text-muted-foreground md:text-lg">
            Catch the crashes and ANRs that hurt your Play Store ranking, on the
            phones Indian users carry.
          </p>
        </div>
        <StartTest />
      </section>

      <section aria-labelledby="how-heading" className="space-y-4">
        <h2
          id="how-heading"
          className="text-center text-sm font-medium text-muted-foreground"
        >
          How it works
        </h2>
        <ol className="mx-auto grid max-w-3xl gap-3 md:grid-cols-3">
          {STEPS.map((s, i) => (
            <li
              key={s.t}
              className={cn(CARD, "flex items-start gap-3 p-4 text-left")}
            >
              <span className="grid size-7 shrink-0 place-items-center rounded-full bg-accent text-xs font-semibold text-primary">
                {i + 1}
              </span>
              <span className="text-sm">
                <span className="font-medium">{s.t}.</span>{" "}
                <span className="text-muted-foreground">{s.d}</span>
              </span>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
