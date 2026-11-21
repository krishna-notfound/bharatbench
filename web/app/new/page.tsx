import type { Metadata } from "next";
import { UploadForm } from "@/components/upload/upload-form";

export const metadata: Metadata = { title: "New test — BharatBench" };

export default function NewTestPage() {
  return (
    <div className="mx-auto max-w-3xl py-8 md:py-12">
      <UploadForm />
    </div>
  );
}
