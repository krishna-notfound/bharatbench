import { Suspense } from "react";
import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { AppShell } from "@/components/shell/app-shell";
import { Toaster } from "@/components/ui/sonner";
import { RealtimeProvider } from "@/components/voice/realtime-provider";
import { VoicePanel } from "@/components/voice/voice-panel";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

const SITE_URL = "https://bharatbench-orpin.vercel.app";
const SITE_TITLE = "BharatBench — The Real Phone Test";
const SITE_DESC =
  "Test your Android app where your users actually are: constrained RAM, flaky networks, low storage.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: SITE_TITLE,
  description: SITE_DESC,
  alternates: { canonical: "/" },
  openGraph: {
    title: SITE_TITLE,
    description: SITE_DESC,
    url: SITE_URL,
    siteName: "BharatBench",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: SITE_TITLE,
    description: SITE_DESC,
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full">
        <RealtimeProvider>
          <AppShell>{children}</AppShell>
          <Suspense fallback={null}>
            <VoicePanel />
          </Suspense>
        </RealtimeProvider>
        <Toaster theme="light" />
      </body>
    </html>
  );
}
