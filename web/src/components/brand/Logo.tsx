/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { useId } from "react";

/** Paths shared with app/icon.svg: FD monogram rising into a stepped skyline of < and /> towers. */
export const LOGO_PATHS = [
  "M12 62 V14 H34 M12 38 H28", // F
  "M44 62 V26 H52 Q68 26 68 44 Q68 62 52 62 Z", // D
  "M68 62 H72 V46 H80 V38 H88", // stepped skyline
  "M100 8 L89 22 L100 36", // < tower
  "M104 36 L112 8", // / tower
  "M116 8 L127 22 L116 36", // > tower
];

export function Logo({
  title = "FirstDev",
  className = "h-12 w-auto",
}: {
  title?: string;
  className?: string;
}) {
  const uid = useId().replace(/\W/g, "");
  return (
    <svg
      role="img"
      aria-labelledby={`logo-${uid}`}
      viewBox="0 0 132 72"
      className={className}
      fill="none"
    >
      <title id={`logo-${uid}`}>{title}</title>
      <defs>
        <filter id={`glow-${uid}`} x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="2.5" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <g
        stroke="#00F2FE"
        strokeWidth="3.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        filter={`url(#glow-${uid})`}
      >
        {LOGO_PATHS.map((d) => (
          <path key={d} d={d} />
        ))}
      </g>
    </svg>
  );
}
