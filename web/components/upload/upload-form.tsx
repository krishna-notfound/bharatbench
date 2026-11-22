"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  FileArchive,
  GitBranch,
  Link2,
  Loader2,
  UploadCloud,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/shell/states";
import { useFetch } from "@/components/shell/use-fetch";
import { CARD, PRIMARY_CTA } from "@/components/shell/surface";
import {
  AdvancedDisclosure,
  ProfileList,
} from "@/components/upload/profile-list";
import { createRun, getProfiles } from "@/lib/api";
import { importRun, looksLikeGithubRepo } from "@/lib/import";
import { formatBytes } from "@/lib/format";
import type { ProfileId } from "@/lib/types";
import { cn } from "@/lib/utils";

const MAX_BYTES = 200 * 1024 * 1024;
const DEFAULTS: ProfileId[] = ["budget_2gb", "flaky_network"];

type Source = "repo" | "apk" | "link";

const SOURCES: { id: Source; label: string; soon: boolean }[] = [
  { id: "repo", label: "GitHub repo", soon: false },
  { id: "apk", label: "Upload APK", soon: false },
  { id: "link", label: "APK link", soon: true },
];

const NEXT_STEPS = [
  "I look inside your app for security and performance risks.",
  "I run it on a budget phone with weak network and low storage.",
  "I rank what broke by how many real users it would hurt.",
];

function SourceTabs({
  value,
  onChange,
  disabled,
}: {
  value: Source;
  onChange: (s: Source) => void;
  disabled?: boolean;
}) {
  return (
    <div
      role="tablist"
      aria-label="Where is your app?"
      className="grid grid-cols-3 gap-1 rounded-full bg-muted p-1"
    >
      {SOURCES.map((s) => (
        <button
          key={s.id}
          type="button"
          role="tab"
          aria-selected={value === s.id}
          disabled={disabled}
          onClick={() => onChange(s.id)}
          className={cn(
            "rounded-full px-2 py-2 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-primary",
            value === s.id
              ? "bg-card text-foreground shadow-[0_1px_2px_rgba(30,27,46,0.08)]"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {s.label}
          {s.soon && (
            <span className="ml-1 hidden text-[10px] font-normal text-muted-foreground sm:inline">
              soon
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

function ComingSoon({
  icon,
  label,
  placeholder,
  copy,
}: {
  icon: React.ReactNode;
  label: string;
  placeholder: string;
  copy: string;
}) {
  return (
    <div className="space-y-3 p-2">
      <label className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
        {icon}
        {label}
      </label>
      <Input
        disabled
        placeholder={placeholder}
        aria-label={label}
        className="h-12 rounded-full px-5"
      />
      <p className="text-sm text-muted-foreground">
        <span className="font-medium text-foreground">Coming soon.</span>{" "}
        {copy}
      </p>
    </div>
  );
}

export function UploadForm() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [step, setStep] = useState<1 | 2>(1);
  const [source, setSource] = useState<Source>("apk");
  const [file, setFile] = useState<File | null>(null);
  const [repo, setRepo] = useState("");
  const [fileError, setFileError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [picked, setPicked] = useState<Set<ProfileId> | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const profiles = useFetch(getProfiles);

  const all = (profiles.data ?? []).filter((p) => p.fidelity !== "unsupported");
  const baseline = all.find((p) => p.id === "baseline");
  // low_storage cannot be applied on this test phone (redroid shares the host disk), so it is not offered
  const choices = all.filter((p) => p.id !== "baseline" && p.id !== "low_storage");
  const selected: Set<ProfileId> =
    picked ??
    new Set(DEFAULTS.filter((d) => choices.some((p) => p.id === d)));

  function accept(f: File | undefined) {
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".apk")) {
      setFile(null);
      setFileError(
        `That doesn't look like an Android app. I need a file ending in .apk, and "${f.name}" isn't one.`,
      );
      return;
    }
    if (f.size > MAX_BYTES) {
      setFile(null);
      setFileError(
        `That file is ${formatBytes(f.size)}, which is over my 200 MB limit. Try a smaller build.`,
      );
      return;
    }
    setFileError(null);
    setFile(f);
  }

  function toggle(id: ProfileId, on: boolean) {
    const next = new Set(selected);
    if (on) next.add(id);
    else next.delete(id);
    setPicked(next);
  }

  async function submit() {
    const fromRepo = source === "repo";
    if ((fromRepo ? !repoOk : !file) || selected.size === 0) return;
    setSubmitting(true);
    setProgress(fromRepo ? null : 0);
    try {
      const ids = all
        .map((p) => p.id)
        .filter((id) => selected.has(id) || id === "baseline");
      const run =
        fromRepo || !file
          ? await importRun(repo.trim(), ids)
          : await createRun(file, ids, setProgress);
      toast.success(
        fromRepo
          ? "Got the APK from GitHub. I've started your test."
          : "Upload complete. I've started your test.",
      );
      router.push(`/runs/${run.id}`);
    } catch (e) {
      toast.error(
        e instanceof Error
          ? e.message
          : "The upload didn't go through. Please try again.",
      );
      setSubmitting(false);
      setProgress(null);
    }
  }

  const repoOk = looksLikeGithubRepo(repo);
  const repoTouched = repo.trim().length > 0;
  const canContinue = source === "apk" ? !!file : source === "repo" && repoOk;
  const canSubmit = canContinue && selected.size > 0 && !submitting;

  return (
    <div className="space-y-10">
      <header className="space-y-2 text-center">
        <p className="text-sm font-medium text-primary">
          Step {step} of 2
        </p>
        <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">
          {step === 1 ? "Show me your app" : "Pick the conditions"}
        </h1>
        <p className="text-muted-foreground">
          {step === 1
            ? "Upload an APK or paste a GitHub link and I'll take it from here."
            : "Choose the kinds of trouble you want me to try."}
        </p>
      </header>

      {step === 1 ? (
        <>
          <section className={cn(CARD, "space-y-4 p-4 md:p-6")}>
            <SourceTabs value={source} onChange={setSource} />

            {source === "repo" && (
              <div className="space-y-3 p-2">
                <label
                  htmlFor="repo-url"
                  className="flex items-center gap-2 text-sm font-medium"
                >
                  <GitBranch className="size-4" />
                  GitHub repository
                </label>
                <Input
                  id="repo-url"
                  value={repo}
                  inputMode="url"
                  autoComplete="off"
                  placeholder="https://github.com/you/your-app"
                  onChange={(e) => setRepo(e.target.value)}
                  aria-invalid={repoTouched && !repoOk}
                  className="h-12 rounded-full px-5"
                />
                <p
                  className={cn(
                    "text-sm",
                    repoTouched && !repoOk
                      ? "text-destructive"
                      : "text-muted-foreground",
                  )}
                >
                  {repoTouched && !repoOk
                    ? "Use a link like github.com/owner/repo."
                    : "I test the APK attached to the repo's latest release. Building from source is coming soon."}
                </p>
              </div>
            )}
            {source === "link" && (
              <ComingSoon
                icon={<Link2 className="size-4" />}
                label="APK link"
                placeholder="https://example.com/app-release.apk"
                copy="Testing from a link isn't ready yet. Upload an APK for now."
              />
            )}
            {source === "apk" && (
              <div>
                <div
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDragging(true);
                  }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setDragging(false);
                    accept(e.dataTransfer.files[0]);
                  }}
                  className={cn(
                    "rounded-3xl border border-dashed p-4 transition-colors",
                    dragging
                      ? "border-primary bg-accent"
                      : "border-input bg-background/60",
                    fileError && "border-destructive/60",
                  )}
                >
                  <input
                    ref={inputRef}
                    type="file"
                    accept=".apk,application/vnd.android.package-archive"
                    className="sr-only"
                    aria-label="Choose APK file"
                    onChange={(e) => {
                      accept(e.target.files?.[0]);
                      e.target.value = "";
                    }}
                  />
                  {file ? (
                    <div className="flex items-center gap-3 py-2">
                      <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-accent text-primary">
                        <FileArchive className="size-6" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">
                          {file.name}
                        </p>
                        <p className="font-mono text-xs tabular-nums text-muted-foreground">
                          {formatBytes(file.size)}
                        </p>
                      </div>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label="Remove file"
                        onClick={() => setFile(null)}
                      >
                        <X />
                      </Button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => inputRef.current?.click()}
                      className="flex w-full flex-col items-center gap-2 rounded-2xl py-10 text-center outline-none focus-visible:ring-2 focus-visible:ring-primary"
                    >
                      <span className="grid size-14 place-items-center rounded-full bg-accent text-primary">
                        <UploadCloud className="size-7" />
                      </span>
                      <span className="text-base font-medium">
                        Drop your APK here, or tap to browse
                      </span>
                      <span className="text-sm text-muted-foreground">
                        .apk files up to 200 MB
                      </span>
                    </button>
                  )}
                </div>
                {fileError && (
                  <p role="alert" className="mt-3 px-2 text-sm text-destructive">
                    {fileError}
                  </p>
                )}
              </div>
            )}
          </section>

          <div className="flex flex-col items-center gap-2">
            <button
              type="button"
              disabled={!canContinue}
              onClick={() => setStep(2)}
              className={cn(PRIMARY_CTA, "w-full sm:w-auto")}
            >
              Continue <ArrowRight className="size-5" />
            </button>
            {!canContinue && (
              <p className="text-sm text-muted-foreground">
                {source === "apk"
                  ? "Choose an APK to continue."
                  : source === "repo"
                    ? "Paste a GitHub repository link to continue."
                    : "Switch to Upload APK to continue."}
              </p>
            )}
          </div>

          <section aria-labelledby="next-heading" className="space-y-4">
            <h2
              id="next-heading"
              className="text-center text-sm font-medium text-muted-foreground"
            >
              What happens next
            </h2>
            <ol className="grid gap-3 md:grid-cols-3">
              {NEXT_STEPS.map((t, i) => (
                <li
                  key={t}
                  className={cn(CARD, "flex items-start gap-3 p-4 md:flex-col")}
                >
                  <span className="grid size-8 shrink-0 place-items-center rounded-full bg-accent text-sm font-semibold text-primary">
                    {i + 1}
                  </span>
                  <span className="text-sm text-muted-foreground">{t}</span>
                </li>
              ))}
            </ol>
          </section>
        </>
      ) : (
        <>
          <section className="space-y-4">
            {(source === "repo" || file) && (
              <p className="truncate text-center text-sm text-muted-foreground">
                Testing{" "}
                <span className="font-medium text-foreground">
                  {source === "repo" ? repo.trim() : file?.name}
                </span>
              </p>
            )}
            {profiles.loading ? (
              <div className="grid gap-3 sm:grid-cols-2">
                {[0, 1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-28 w-full rounded-3xl" />
                ))}
              </div>
            ) : profiles.error ? (
              <ErrorState
                title="I couldn't load the test conditions"
                message="My test lab isn't answering right now. Give it a moment and try again."
                onRetry={profiles.reload}
              />
            ) : (
              <>
                <ProfileList
                  profiles={choices}
                  selected={selected}
                  onToggle={toggle}
                  disabled={submitting}
                  showHow={advanced}
                />
                <AdvancedDisclosure
                  open={advanced}
                  onToggle={() => setAdvanced((v) => !v)}
                >
                  {baseline && (
                    <p className="rounded-2xl bg-muted p-3 text-sm text-muted-foreground">
                      <span className="font-medium text-foreground">
                        Baseline
                      </span>{" "}
                      is always included, so you can compare every result with
                      a normal phone. {baseline.description}
                    </p>
                  )}
                  <p className="rounded-2xl bg-muted p-3 text-sm text-muted-foreground">
                    <span className="font-medium text-foreground">
                      Not simulated:
                    </span>{" "}
                    thermal throttling, slow CPU speeds and OEM background
                    killers (aggressive vendor battery managers). Results under
                    those conditions may differ on real hardware.
                  </p>
                </AdvancedDisclosure>
              </>
            )}
          </section>

          <div className="space-y-4">
            {submitting && (
              <div className="mx-auto max-w-md space-y-1.5" aria-live="polite">
                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <span className="flex items-center gap-1.5">
                    <Loader2 className="size-3.5 animate-spin" />
                    {source === "repo"
                      ? "Fetching the APK from GitHub…"
                      : (progress ?? 0) < 100
                        ? "Uploading…"
                        : "Getting started…"}
                  </span>
                  {source !== "repo" && (
                    <span className="font-mono tabular-nums">{progress}%</span>
                  )}
                </div>
                {source !== "repo" && <Progress value={progress ?? 0} />}
              </div>
            )}
            <div className="flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
              <button
                type="button"
                disabled={submitting}
                onClick={() => setStep(1)}
                className="h-12 rounded-full px-6 text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-50"
              >
                Back
              </button>
              <button
                type="button"
                disabled={!canSubmit}
                onClick={submit}
                className={cn(PRIMARY_CTA, "w-full sm:w-auto")}
              >
                Start testing
              </button>
            </div>
            {selected.size === 0 && !profiles.loading && !profiles.error && (
              <p className="text-center text-sm text-muted-foreground">
                Pick at least one condition to start.
              </p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
