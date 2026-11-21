import { RunsList } from "@/components/runs/runs-list";

export default function RunsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Runs</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Every Cheap Phone Test you have started, newest first.
        </p>
      </div>
      <RunsList />
    </div>
  );
}
