/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { useId, type TextareaHTMLAttributes } from "react";

export function Textarea({
  label,
  error,
  hint,
  className = "",
  id,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string; error?: string; hint?: string }) {
  const auto = useId();
  const tid = id ?? auto;
  const describedBy = [hint && `${tid}-hint`, error && `${tid}-err`].filter(Boolean).join(" ") || undefined;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={tid} className="text-sm text-text-muted">
        {label}
      </label>
      <textarea
        id={tid}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={`rounded-lg border border-text-primary/15 bg-bg-base/60 px-3 py-2 text-text-primary placeholder:text-text-muted/60 focus-visible:border-accent-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-primary ${className}`}
        {...props}
      />
      {hint && (
        <p id={`${tid}-hint`} className="text-xs text-text-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${tid}-err`} role="alert" className="text-sm text-warning">
          {error}
        </p>
      )}
    </div>
  );
}
