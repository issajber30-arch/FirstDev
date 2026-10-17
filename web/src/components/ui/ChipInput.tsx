/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import { useId, useState, type KeyboardEvent } from "react";
import { Badge } from "./Badge";
import { addChips } from "@/lib/rec";

/** Skill chips: Enter or comma adds, Backspace on an empty field removes the last, each chip has a remove button. */
export function ChipInput({
  label,
  value,
  onChange,
  max,
  removeLabel,
  hint,
  error,
  tone = "match",
  name,
}: {
  label: string;
  value: string[];
  onChange: (v: string[]) => void;
  max: number;
  removeLabel: (chip: string) => string;
  hint?: string;
  error?: string;
  tone?: "match" | "verified";
  name?: string;
}) {
  const id = useId();
  const [draft, setDraft] = useState("");
  const commit = (raw: string) => {
    onChange(addChips(value, raw, max));
    setDraft("");
  };
  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault(); // Enter must not submit the surrounding form
      commit(draft);
    } else if (e.key === "Backspace" && !draft && value.length) {
      onChange(value.slice(0, -1));
    }
  }
  const described = [hint && `${id}-hint`, error && `${id}-err`].filter(Boolean).join(" ") || undefined;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm text-text-muted">
        {label}
      </label>
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-text-primary/15 bg-bg-base/60 px-2 py-2 focus-within:border-accent-primary focus-within:outline-2 focus-within:outline-accent-primary">
        {value.map((c) => (
          <Badge key={c} tone={tone} className="gap-1.5">
            <span className="break-all">{c}</span>
            <button
              type="button"
              aria-label={removeLabel(c)}
              onClick={() => onChange(value.filter((x) => x !== c))}
              className="rounded-full px-1 leading-none hover:bg-text-primary/20"
            >
              <span aria-hidden="true">×</span>
            </button>
          </Badge>
        ))}
        <input
          id={id}
          name={name}
          value={draft}
          disabled={value.length >= max}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKey}
          onBlur={() => draft.trim() && commit(draft)}
          aria-invalid={error ? true : undefined}
          aria-describedby={described}
          autoCapitalize="none"
          spellCheck={false}
          className="min-w-24 flex-1 bg-transparent px-1 py-0.5 text-text-primary outline-none placeholder:text-text-muted/60"
        />
      </div>
      {hint && (
        <p id={`${id}-hint`} className="text-xs text-text-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-err`} role="alert" className="text-sm text-warning">
          {error}
        </p>
      )}
    </div>
  );
}
