import { UploadForm } from "@/components/upload/upload-form";

export default function Home() {
  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <p className="font-mono text-xs uppercase tracking-wider text-primary">
          BharatBench
        </p>
        <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">
          The Cheap Phone Test
        </h1>
        <p className="max-w-2xl text-base text-muted-foreground">
          Test your app where your users actually are. Upload an APK and we run
          it under a 2 GB RAM budget, a flaky network and more, then rank what
          breaks by real-world user impact.
        </p>
      </section>
      <UploadForm />
    </div>
  );
}
