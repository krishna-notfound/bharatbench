import type { MetadataRoute } from "next";

const BASE = "https://bharatbench-orpin.vercel.app";

export default function sitemap(): MetadataRoute.Sitemap {
  return ["/", "/new", "/runs", "/chat", "/login"].map((p) => ({
    url: `${BASE}${p === "/" ? "" : p}`,
  }));
}
