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

export const metadata: Metadata = {
  title: "BharatBench — The Real Phone Test",
  description:
    "Test your Android app where your users actually are: constrained RAM, flaky networks, low storage.",
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
