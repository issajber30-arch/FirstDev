/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { useId } from "react";

/**
 * Geometry shared with app/icon.svg and the Open Graph image: an FD monogram whose verticals rise
 * into stepped towers (F lowest, D, then the `<` and `/>` brackets as the two tallest).
 */
export const LOGO_PATHS = [
  "M10 64 V38 H24 M10 51 H21", // F tower (shortest)
  "M33 64 V24 H43 Q55 24 55 44 Q55 64 43 64 Z", // D tower
  "M80 14 L62 38 L80 62", // < tower
  "M90 64 L102 4", // / tower (tallest)
  "M110 14 L128 38 L110 62", // > tower
];
/** Amber lit window inside the D counter. */
export const LOGO_WINDOW = { cx: 44, cy: 44, r: 4 };

export const LOGO_CYAN = "#00F2FE";
export const LOGO_AMBER = "#FFB703";

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
      viewBox="-4 0 140 72"
      className={className}
      fill="none"
    >
      <title id={`logo-${uid}`}>{title}</title>
      <defs>
        <filter id={`glow-${uid}`} x="-30%" y="-30%" width="160%" height="160%">
          <feGaussianBlur stdDeviation="2.2" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <g
        stroke={LOGO_CYAN}
        strokeWidth="5.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        filter={`url(#glow-${uid})`}
      >
        {LOGO_PATHS.map((d) => (
          <path key={d} d={d} />
        ))}
      </g>
      <circle {...LOGO_WINDOW} fill={LOGO_AMBER} />
    </svg>
  );
}
