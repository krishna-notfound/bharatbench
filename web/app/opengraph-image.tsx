import { ImageResponse } from "next/og";

export const alt = "BharatBench — The Real Phone Test";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#efe9ff",
          color: "#1e1b2e",
          fontSize: 72,
          fontWeight: 700,
        }}
      >
        BharatBench — The Real Phone Test
      </div>
    ),
    size,
  );
}
