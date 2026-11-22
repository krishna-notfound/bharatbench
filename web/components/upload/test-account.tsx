"use client";

import { useState } from "react";
import { ChevronDown, Eye, EyeOff } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import type { TestAccount } from "@/lib/account";
import { cn } from "@/lib/utils";

export const EMPTY_ACCOUNT: TestAccount = { login: "", password: "", note: "", offline_after_login: false };

/** Collapsed, optional test account so the agent can log in. Values live in component state only. */
export function TestAccountSection({
  value,
  onChange,
  disabled,
}: {
  value: TestAccount;
  onChange: (v: TestAccount) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [show, setShow] = useState(false);
  const set = (patch: Partial<TestAccount>) => onChange({ ...value, ...patch });
  return (
    <div className="w-full space-y-3 text-left">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 rounded-full px-1 text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-primary"
      >
        Test account (optional)
        <ChevronDown className={cn("size-4 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="space-y-3 rounded-2xl border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground">
            Used only for this test, never stored after it finishes.
          </p>
          <Input
            aria-label="Login (email, phone or username)"
            placeholder="Login: email, phone or username"
            autoComplete="off"
            maxLength={200}
            disabled={disabled}
            value={value.login}
            onChange={(e) => set({ login: e.target.value })}
          />
          <div className="relative">
            <Input
              aria-label="Password"
              type={show ? "text" : "password"}
              placeholder="Password"
              autoComplete="new-password"
              maxLength={200}
              disabled={disabled}
              value={value.password}
              onChange={(e) => set({ password: e.target.value })}
              className="pr-10"
            />
            <button
              type="button"
              aria-label={show ? "Hide password" : "Show password"}
              onClick={() => setShow((v) => !v)}
              className="absolute inset-y-0 right-3 text-muted-foreground hover:text-foreground"
            >
              {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
            </button>
          </div>
          <Input
            aria-label="OTP or extra note"
            placeholder='OTP or note, e.g. "OTP is 123456 in test mode"'
            autoComplete="off"
            maxLength={300}
            disabled={disabled}
            value={value.note}
            onChange={(e) => set({ note: e.target.value })}
          />
          <label className="flex cursor-pointer items-center gap-2 text-sm">
            <Checkbox
              checked={value.offline_after_login}
              disabled={disabled}
              onCheckedChange={(v) => set({ offline_after_login: v === true })}
            />
            Also test while offline after logging in
          </label>
        </div>
      )}
    </div>
  );
}

/** JSON for the API, or undefined when nothing was entered. */
export function accountPayload(a: TestAccount): TestAccount | undefined {
  return a.login.trim() || a.password ? a : undefined;
}
