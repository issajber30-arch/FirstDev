/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import type { HTMLAttributes } from "react";

const tones = {
  verified: "border-accent-verified/50 bg-accent-verified/10 text-accent-verified",
  cv: "border-text-muted/40 bg-text-muted/10 text-text-muted",
  match: "border-accent-primary/50 bg-accent-primary/10 text-accent-primary",
  warning: "border-warning/50 bg-warning/10 text-warning",
} as const;

export function Badge({
  tone,
  className = "",
  ...props
}: HTMLAttributes<HTMLSpanElement> & { tone: keyof typeof tones }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 font-mono text-xs ${tones[tone]} ${className}`}
      {...props}
    />
  );
}
