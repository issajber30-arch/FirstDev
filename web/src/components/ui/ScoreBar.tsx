/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */

/** Horizontal meter, 0-100. The value is mono text beside the bar; `label` names it for screen readers. */
export function ScoreBar({
  value,
  label,
  tone = "primary",
}: {
  value: number;
  label: string;
  tone?: "primary" | "warning";
}) {
  const v = Math.max(0, Math.min(100, Math.round(value)));
  return (
    <div className="flex items-center gap-3">
      <div
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={v}
        className="h-2 flex-1 overflow-hidden rounded-full bg-text-primary/10"
      >
        <div
          className={`h-full rounded-full transition-[inline-size] duration-200 ${tone === "warning" ? "bg-warning" : "bg-accent-primary"}`}
          style={{ inlineSize: `${v}%` }}
        />
      </div>
      <span className="w-10 text-end font-mono text-sm" aria-hidden="true">
        {v}
      </span>
    </div>
  );
}
