/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import type { HTMLAttributes, Ref } from "react";

const tones = {
  error: "border-warning/50 bg-warning/10 text-warning",
  info: "border-accent-primary/40 bg-accent-primary/5 text-text-primary",
  success: "border-accent-verified/50 bg-accent-verified/10 text-accent-verified",
} as const;

/** Inline message. Errors are announced at once (alert), the rest politely (status). Focusable
 *  via `ref` so a form can move focus to its outcome after submit. */
export function Notice({
  tone = "info",
  className = "",
  ref,
  ...props
}: HTMLAttributes<HTMLDivElement> & { tone?: keyof typeof tones; ref?: Ref<HTMLDivElement> }) {
  return (
    <div
      ref={ref}
      tabIndex={-1}
      role={tone === "error" ? "alert" : "status"}
      className={`rounded-lg border px-4 py-3 text-sm break-words ${tones[tone]} ${className}`}
      {...props}
    />
  );
}
