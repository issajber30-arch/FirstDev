/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { useId, type InputHTMLAttributes } from "react";

export function Input({
  label,
  error,
  className = "",
  id,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string }) {
  const auto = useId();
  const inputId = id ?? auto;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={inputId} className="text-sm text-text-muted">
        {label}
      </label>
      <input
        id={inputId}
        aria-invalid={error ? true : undefined}
        className={`rounded-lg border border-text-primary/15 bg-bg-base/60 px-3 py-2 text-text-primary placeholder:text-text-muted/60 focus-visible:border-accent-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-primary ${className}`}
        {...props}
      />
      {error && (
        <p role="alert" className="text-sm text-warning">
          {error}
        </p>
      )}
    </div>
  );
}
