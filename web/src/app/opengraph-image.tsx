/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { ImageResponse } from "next/og";
import { LOGO_PATHS } from "@/components/brand/Logo";

export const alt = "FirstDev";
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
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          background: "#0B0F19",
          color: "#F8FAFC",
          fontSize: 56,
        }}
      >
        <svg width="660" height="360" viewBox="0 0 132 72" fill="none">
          {LOGO_PATHS.map((d) => (
            <path
              key={d}
              d={d}
              stroke="#00F2FE"
              strokeWidth="3.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          ))}
        </svg>
        <div style={{ marginTop: 16 }}>FirstDev</div>
      </div>
    ),
    size,
  );
}
