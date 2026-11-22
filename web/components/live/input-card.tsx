"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Eye, EyeOff, Hand } from "lucide-react";
import { sendInput, type InputField, type InputRequest } from "@/lib/live";

const DEFAULT_TIMEOUT_S = 180;

function inputProps(f: InputField): React.InputHTMLAttributes<HTMLInputElement> {
  switch (f.kind) {
    case "email":
      return { type: "email", inputMode: "email", autoComplete: "email" };
    case "phone":
      return { type: "tel", inputMode: "tel", autoComplete: "tel" };
    case "otp":
      return { type: "text", inputMode: "numeric", autoComplete: "one-time-code", pattern: "[0-9]*" };
    case "pin":
      return { type: "password", inputMode: "numeric", autoComplete: "off" };
    case "username":
      return { type: "text", autoComplete: "username" };
    default:
      return { type: "text", autoComplete: "off" };
  }
}

function fmt(s: number): string {
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

/** "The agent needs your help": slides in beside the live phone while the agent waits for the user. */
export function InputCard({ runId, request }: { runId: string; request: InputRequest }) {
  const uid = useId();
  const [values, setValues] = useState<Record<string, string>>({});
  const [shown, setShown] = useState<Record<string, boolean>>({});
  const [phase, setPhase] = useState<"idle" | "sending" | "sent">("idle");
  const [error, setError] = useState<string | null>(null);
  const [entered, setEntered] = useState(false);
  const total = request.timeout_s ?? DEFAULT_TIMEOUT_S;
  const [left, setLeft] = useState(total);
  const first = useRef<HTMLInputElement | null>(null);

  // The parent keys this card by request_id, so each question starts with a clean form.
  useEffect(() => {
    const a = requestAnimationFrame(() => setEntered(true));
    first.current?.focus({ preventScroll: true });
    return () => cancelAnimationFrame(a);
  }, []);

  useEffect(() => {
    const started = Date.now();
    const t = setInterval(() => setLeft(Math.max(0, total - Math.floor((Date.now() - started) / 1000))), 1000);
    return () => clearInterval(t);
  }, [total]);

  const busy = phase !== "idle";
  const canSubmit = !busy && request.fields.some((f) => (values[f.key] ?? "").trim().length > 0);

  async function submit(skip: boolean) {
    setPhase("sending");
    setError(null);
    try {
      await sendInput(runId, request.request_id, skip ? {} : values, skip);
      setPhase("sent");
      setValues({});
    } catch {
      setPhase("idle");
      setError("That didn't go through. The question may have closed; try again.");
    }
  }

  return (
    <section
      role="group"
      aria-labelledby={`${uid}-t`}
      aria-live="polite"
      className={`mt-1 w-full max-w-[17rem] rounded-2xl border border-primary/30 bg-card p-3 text-left shadow-[0_10px_30px_-8px_rgba(124,92,255,0.35)] transition-[transform,opacity] duration-500 ease-out motion-reduce:transition-none ${
        entered ? "translate-y-0 opacity-100" : "translate-y-3 opacity-0"
      }`}
    >
      <div className="flex items-center gap-2">
        <span className="flex size-7 items-center justify-center rounded-full bg-primary/10 text-primary">
          <Hand className="size-4" aria-hidden />
        </span>
        <h3 id={`${uid}-t`} className="text-sm font-semibold">
          The agent needs your help
        </h3>
      </div>
      {request.reason && <p className="mt-1.5 text-xs text-muted-foreground">{request.reason}</p>}

      {phase === "sent" ? (
        <p className="mt-3 text-sm font-medium text-primary">Typing it in…</p>
      ) : (
        <form
          className="mt-3 flex flex-col gap-2.5"
          onSubmit={(e) => {
            e.preventDefault();
            if (canSubmit) void submit(false);
          }}
        >
          {request.fields.map((f, i) => {
            const id = `${uid}-${f.key}`;
            const p = inputProps(f);
            const reveal = f.secret && p.type === "password";
            const visible = !!shown[f.key];
            return (
              <div key={f.key} className="flex flex-col gap-1">
                <label htmlFor={id} className="text-xs font-medium">
                  {f.label}
                </label>
                <div className="relative">
                  <input
                    id={id}
                    ref={i === 0 ? first : undefined}
                    {...p}
                    type={reveal && visible ? "text" : p.type}
                    value={values[f.key] ?? ""}
                    disabled={busy}
                    maxLength={200}
                    spellCheck={false}
                    autoCapitalize="none"
                    onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                    className="h-11 w-full rounded-xl border border-input bg-background px-3 pr-10 text-base outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40 disabled:opacity-60"
                  />
                  {reveal && (
                    <button
                      type="button"
                      onClick={() => setShown((s) => ({ ...s, [f.key]: !s[f.key] }))}
                      aria-label={visible ? `Hide ${f.label}` : `Show ${f.label}`}
                      aria-pressed={visible}
                      className="absolute top-1/2 right-1.5 flex size-8 -translate-y-1/2 items-center justify-center rounded-lg text-muted-foreground hover:text-foreground"
                    >
                      {visible ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
          {error && (
            <p role="alert" className="text-xs text-destructive">
              {error}
            </p>
          )}
          <div className="flex items-center gap-2 pt-1">
            <button
              type="submit"
              disabled={!canSubmit}
              className="h-11 flex-1 rounded-xl bg-primary px-3 text-sm font-medium text-primary-foreground transition-opacity disabled:opacity-50"
            >
              {phase === "sending" ? "Sending…" : "Continue"}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => void submit(true)}
              className="h-11 rounded-xl border border-border px-4 text-sm font-medium text-muted-foreground hover:bg-muted disabled:opacity-50"
            >
              Skip
            </button>
          </div>
          <p className="text-center text-[11px] text-muted-foreground tabular-nums">
            {left > 0 ? `Waiting up to ${fmt(left)}` : "Out of time; the agent will move on"}
          </p>
        </form>
      )}
    </section>
  );
}
