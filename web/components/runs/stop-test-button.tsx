"use client";

import { useState } from "react";
import { Square } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cancelRun } from "@/lib/api";

/** Deliberate, graceful stop: outline button, confirm dialog, then a "finishing up" note until the status changes. */
export function StopTestButton({ runId, onStopped }: { runId: string; onStopped?: () => void }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [stopping, setStopping] = useState(false);

  if (stopping) {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        Finishing up with the results so far…
      </p>
    );
  }

  const confirm = async () => {
    setBusy(true);
    try {
      await cancelRun(runId);
      setStopping(true);
      setOpen(false);
      onStopped?.();
    } catch {
      toast.error("I couldn't stop the test just now. Try again in a moment.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Button variant="outline" className="h-9 rounded-full px-4" onClick={() => setOpen(true)}>
        <Square /> Stop test
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Stop this test now?</DialogTitle>
            <DialogDescription>
              Stop this test now? Everything tested so far is kept and you&apos;ll get a report for it.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={busy}>
              Keep testing
            </Button>
            <Button onClick={confirm} disabled={busy}>
              Stop test
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
