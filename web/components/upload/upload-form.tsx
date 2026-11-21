"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ChevronDown,
  FileArchive,
  Loader2,
  Rocket,
  UploadCloud,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState, SectionTitle } from "@/components/shell/states";
import { useFetch } from "@/components/shell/use-fetch";
import { ProfileList } from "@/components/upload/profile-list";
import { createRun, getProfiles } from "@/lib/api";
import { formatBytes } from "@/lib/format";
import type { ProfileId } from "@/lib/types";
import { cn } from "@/lib/utils";

const MAX_BYTES = 200 * 1024 * 1024;
const DEFAULTS: ProfileId[] = ["baseline", "budget_2gb", "flaky_network"];

export function UploadForm() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [picked, setPicked] = useState<Set<ProfileId> | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const profiles = useFetch(getProfiles);

  const available = (profiles.data ?? []).filter(
    (p) => p.fidelity !== "unsupported",
  );
  const selected: Set<ProfileId> =
    picked ??
    new Set(DEFAULTS.filter((d) => available.some((p) => p.id === d)));

  function accept(f: File | undefined) {
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".apk")) {
      setFile(null);
      setFileError(`"${f.name}" is not an .apk file.`);
      return;
    }
    if (f.size > MAX_BYTES) {
      setFile(null);
      setFileError(`${f.name} is ${formatBytes(f.size)}; the limit is 200 MB.`);
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
    if (!file || selected.size === 0) return;
    setSubmitting(true);
    setProgress(0);
    try {
      const order = available.map((p) => p.id).filter((id) => selected.has(id));
      const run = await createRun(file, order, setProgress);
      toast.success("Upload complete. Test started.");
      router.push(`/runs/${run.id}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Upload failed");
      setSubmitting(false);
      setProgress(null);
    }
  }

  const canSubmit = !!file && selected.size > 0 && !submitting;

  return (
    <div className="grid gap-8 lg:grid-cols-[1fr_1.1fr]">
      <section className="space-y-3">
        <SectionTitle>1 · Your APK</SectionTitle>
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
            "rounded-xl border border-dashed bg-card p-6 transition-colors",
            dragging ? "border-primary bg-primary/5" : "border-border",
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
            <div className="flex items-center gap-3">
              <FileArchive className="size-8 shrink-0 text-primary" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{file.name}</p>
                <p className="font-mono text-xs tabular-nums text-muted-foreground">
                  {formatBytes(file.size)}
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                aria-label="Remove file"
                disabled={submitting}
                onClick={() => setFile(null)}
              >
                <X />
              </Button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              className="flex w-full flex-col items-center gap-2 rounded-lg py-8 text-center outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              <UploadCloud className="size-8 text-muted-foreground" />
              <span className="text-sm font-medium">
                Drop an APK here, or click to browse
              </span>
              <span className="text-xs text-muted-foreground">
                .apk only, up to 200 MB
              </span>
            </button>
          )}
        </div>
        {fileError && (
          <p role="alert" className="text-sm text-destructive">
            {fileError}
          </p>
        )}

        <div className="space-y-3 pt-2">
          {submitting && progress !== null && (
            <div className="space-y-1.5" aria-live="polite">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span className="flex items-center gap-1.5">
                  <Loader2 className="size-3.5 animate-spin" />
                  {progress < 100 ? "Uploading…" : "Starting analysis…"}
                </span>
                <span className="font-mono tabular-nums">{progress}%</span>
              </div>
              <Progress value={progress} />
            </div>
          )}
          <Button
            size="lg"
            className="h-11 w-full text-base"
            disabled={!canSubmit}
            onClick={submit}
          >
            <Rocket /> Run the Cheap Phone Test
          </Button>
          {!file && (
            <p className="text-center text-xs text-muted-foreground">
              Choose an APK to enable the test.
            </p>
          )}
          {file && selected.size === 0 && (
            <p className="text-center text-xs text-muted-foreground">
              Select at least one profile.
            </p>
          )}
        </div>
      </section>

      <section className="space-y-3">
        <SectionTitle>2 · Device profiles</SectionTitle>
        {profiles.loading ? (
          <div className="space-y-2">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-16 w-full rounded-xl" />
            ))}
          </div>
        ) : profiles.error ? (
          <ErrorState
            title="Could not load profiles"
            message={profiles.error}
            onRetry={profiles.reload}
          />
        ) : (
          <ProfileList
            profiles={available}
            selected={selected}
            onToggle={toggle}
            disabled={submitting}
          />
        )}
        <details className="group rounded-xl border border-border bg-card px-4 py-3 text-sm">
          <summary className="flex cursor-pointer list-none items-center justify-between font-medium">
            Not simulated
            <ChevronDown className="size-4 text-muted-foreground transition-transform group-open:rotate-180" />
          </summary>
          <p className="mt-2 text-muted-foreground">
            We do not fake what an emulator cannot reproduce: thermal
            throttling, slow CPU speeds and OEM background-process killers
            (aggressive vendor battery managers) are not simulated. Results
            under those conditions may differ on real hardware.
          </p>
        </details>
      </section>
    </div>
  );
}
