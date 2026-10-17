/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import { useLocale, useTranslations } from "next-intl";
import { useEffect, useRef } from "react";
import { Badge } from "@/components/ui/Badge";
import { Notice } from "@/components/ui/Notice";
import { buttonClass } from "@/components/ui/Button";
import { Link } from "@/i18n/navigation";
import { ApiError, fetcher } from "@/lib/api";
import { POLL_MS, isActive, reasonKey } from "@/lib/dev";
import type { JobStatus, Level } from "@/lib/devTypes";
import useSWR from "swr";

/** API error -> a translated sentence. Known backend reasons are translated; for unknown ones the
 *  English detail is appended only in the English UI (never mixed into Hebrew). */
export function useApiErrorText() {
  const t = useTranslations("dev.errors");
  const locale = useLocale();
  return (e: unknown): string => {
    if (!(e instanceof ApiError)) return t("generic");
    const known = reasonKey(e.detail);
    if (known) return t(`reasons.${known.key}` as "reasons.demoLimit", { skill: known.skill ?? "" });
    const plain = locale === "en" && !e.detail.startsWith("[") ? ` (${e.detail})` : "";
    switch (e.status) {
      case 413:
        return t("tooLarge") + plain;
      case 422:
        return t("invalid") + plain;
      case 429:
        return /demo/i.test(e.detail) ? t("demoLimit") : t("rateLimit");
      case 403:
        return t("verifyRequired");
      case 409:
        return t("conflict");
      case 404:
        return t("notFound");
      default:
        return t("generic");
    }
  };
}

/** Ref that takes focus whenever `when` becomes truthy (focus management after a submit). */
export function useFocusWhen<T extends HTMLElement>(when: unknown) {
  const ref = useRef<T>(null);
  useEffect(() => {
    if (when) ref.current?.focus();
  }, [when]);
  return ref;
}

type Job = { id: string; status: JobStatus; last_error: string | null };
/** Polls GET /jobs/{id} every POLL_MS while queued or running. */
export function useJob(jobId: string | null | undefined) {
  return useSWR<Job>(jobId ? `/jobs/${jobId}` : null, fetcher<Job>, {
    refreshInterval: (d) => (d && isActive(d.status) ? POLL_MS : 0),
    shouldRetryOnError: false,
  });
}

/** Job status line. The wrapper is an aria-live region so changes are announced. */
export function StatusLine({ status, error }: { status?: JobStatus | null; error?: string | null }) {
  const t = useTranslations("dev.jobStatus");
  return (
    <div aria-live="polite" className="flex flex-wrap items-center gap-2 text-sm">
      {status && (
        <Badge tone={status === "failed" ? "warning" : status === "done" ? "verified" : "match"}>
          {isActive(status) && <span className="me-1.5 inline-block size-2 animate-pulse rounded-full bg-current" aria-hidden="true" />}
          {t(status)}
        </Badge>
      )}
      {status === "failed" && <span className="text-warning">{error ? error : t("failedGeneric")}</span>}
    </div>
  );
}

/** 403 "verify your profile first" with links to the two things that verify it. */
export function VerifyRequired({ tone = "info" }: { tone?: "info" | "error" }) {
  const t = useTranslations("dev.verify");
  return (
    <Notice tone={tone} className="flex flex-col gap-3">
      <p>{t("body")}</p>
      <div className="flex flex-wrap gap-3">
        <Link href="/dev/cv" className={buttonClass("secondary")}>
          {t("cv")}
        </Link>
        <Link href="/dev/repos" className={buttonClass("secondary")}>
          {t("repos")}
        </Link>
      </div>
    </Notice>
  );
}

/** Skill chip: amber for repo/assessment-verified, grey for CV claims. */
export function SkillChip({ skill, level, years }: { skill: string; level: Level; years?: number | null }) {
  const t = useTranslations("dev");
  return (
    <Badge tone={level === "cv" ? "cv" : "verified"}>
      {skill}
      {years ? <span className="ms-1.5 opacity-70">{t("years", { n: years })}</span> : null}
    </Badge>
  );
}

export function PageHeading({ children, sub }: { children: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="mb-6">
      <h1 className="text-2xl font-semibold break-words">{children}</h1>
      {sub && <p className="mt-1 text-text-muted">{sub}</p>}
    </div>
  );
}
