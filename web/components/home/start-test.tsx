"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  FileArchive,
  Loader2,
  UploadCloud,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { CARD, PRIMARY_CTA } from "@/components/shell/surface";
import { createRun } from "@/lib/api";
import { TestAccountSection, EMPTY_ACCOUNT, accountPayload } from "@/components/upload/test-account";
import { formatBytes } from "@/lib/format";
import { importRun, looksLikeGithubRepo } from "@/lib/import";
import type { ProfileId } from "@/lib/types";
import type { TestAccount } from "@/lib/account";
import { cn } from "@/lib/utils";

const MAX_BYTES = 200 * 1024 * 1024;
const DEFAULT_PROFILES: ProfileId[] = ["baseline", "budget_2gb", "flaky_network"];

/** Upload-first start: drop an APK or paste a GitHub link, then one "Start test". */
export function StartTest() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [account, setAccount] = useState<TestAccount>(EMPTY_ACCOUNT);
  const [fileError, setFileError] = useState<string | null>(null);
  const [repo, setRepo] = useState("");
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  const repoOk = looksLikeGithubRepo(repo);
  const repoTouched = repo.trim().length > 0;
  const canStart = !busy && (!!file || repoOk);

  function accept(f: File | undefined) {
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".apk")) {
      setFile(null);
      setFileError(`I need a file ending in .apk, and "${f.name}" isn't one.`);
      return;
    }
    if (f.size > MAX_BYTES) {
      setFile(null);
      setFileError(
        `That file is ${formatBytes(f.size)}, over my 200 MB limit. Try a smaller build.`,
      );
      return;
    }
    setFileError(null);
    setFile(f);
    setRepo("");
  }

  async function start() {
    if (!canStart) return;
    setBusy(true);
    setProgress(file ? 0 : null);
    try {
      const run = file
        ? await createRun(file, DEFAULT_PROFILES, setProgress, accountPayload(account))
        : await importRun(repo.trim(), DEFAULT_PROFILES, accountPayload(account));
      router.push(`/runs/${run.id}`);
    } catch (e) {
      toast.error(
        e instanceof Error
          ? e.message
          : "That didn't go through. Please try again.",
      );
      setBusy(false);
      setProgress(null);
    }
  }

  return (
    <div className="mx-auto w-full max-w-3xl space-y-5">
      <div className="grid gap-4 md:grid-cols-[1.4fr_1fr]">
        <div
          onDragOver={(e) => {
            e.preventDefault();
            if (!busy) setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            if (!busy) accept(e.dataTransfer.files[0]);
          }}
          className={cn(
            CARD,
            "border-dashed p-3 transition-colors",
            dragging && "border-primary bg-accent",
            fileError && "border-destructive/60",
          )}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".apk,application/vnd.android.package-archive"
            className="sr-only"
            aria-label="Choose APK file"
            disabled={busy}
            onChange={(e) => {
              accept(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
          {file ? (
            <div className="flex min-h-40 items-center gap-3 px-2">
              <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-accent text-primary">
                <FileArchive className="size-6" />
              </span>
              <div className="min-w-0 flex-1 text-left">
                <p className="truncate text-sm font-medium">{file.name}</p>
                <p className="font-mono text-xs tabular-nums text-muted-foreground">
                  {formatBytes(file.size)}
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                aria-label="Remove file"
                disabled={busy}
                onClick={() => setFile(null)}
              >
                <X />
              </Button>
            </div>
          ) : (
            <button
              type="button"
              disabled={busy}
              onClick={() => inputRef.current?.click()}
              className="flex min-h-40 w-full flex-col items-center justify-center gap-2 rounded-2xl px-3 py-6 text-center outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              <span className="grid size-12 place-items-center rounded-full bg-accent text-primary">
                <UploadCloud className="size-6" />
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

        <div className={cn(CARD, "flex flex-col justify-center gap-2 p-4")}>
          <label
            htmlFor="github-link"
            className="text-left text-sm font-medium"
          >
            Or paste a GitHub link
          </label>
          <Input
            id="github-link"
            value={repo}
            disabled={busy}
            inputMode="url"
            autoComplete="off"
            placeholder="github.com/you/your-app"
            onChange={(e) => {
              setRepo(e.target.value);
              if (e.target.value.trim()) {
                setFile(null);
                setFileError(null);
              }
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") void start();
            }}
            aria-invalid={repoTouched && !repoOk}
            className="h-12 rounded-full px-5"
          />
          <p
            className={cn(
              "text-left text-xs",
              repoTouched && !repoOk
                ? "text-destructive"
                : "text-muted-foreground",
            )}
          >
            {repoTouched && !repoOk
              ? "Use a link like github.com/owner/repo."
              : "I use the APK from the repo's latest release. Building from source is coming soon."}
          </p>
        </div>
      </div>

      {fileError && (
        <p role="alert" className="text-center text-sm text-destructive">
          {fileError}
        </p>
      )}

      {busy && (
        <div className="mx-auto max-w-md space-y-1.5" aria-live="polite">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <Loader2 className="size-3.5 animate-spin" />
              {file
                ? progress !== null && progress < 100
                  ? "Uploading…"
                  : "Getting started…"
                : "Fetching the APK from GitHub…"}
            </span>
            {file && progress !== null && (
              <span className="font-mono tabular-nums">{progress}%</span>
            )}
          </div>
          {file && <Progress value={progress ?? 0} />}
        </div>
      )}

      <TestAccountSection value={account} onChange={setAccount} disabled={busy} />

      <div className="flex flex-col items-center gap-2">
        <button
          type="button"
          disabled={!canStart}
          onClick={start}
          className={cn(PRIMARY_CTA, "w-full sm:w-auto sm:min-w-52")}
        >
          Start test <ArrowRight className="size-5" />
        </button>
        <p className="text-xs text-muted-foreground">
          Runs on a 2 GB phone and a flaky network, next to a normal-phone
          baseline.
        </p>
      </div>
    </div>
  );
}
