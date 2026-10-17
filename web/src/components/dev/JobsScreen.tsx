/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import { useTranslations } from "next-intl";
import useSWR from "swr";
import { Badge } from "@/components/ui/Badge";
import { GlassCard } from "@/components/ui/GlassCard";
import { QueryState } from "@/components/ui/QueryState";
import { ScoreBar } from "@/components/ui/ScoreBar";
import { Link } from "@/i18n/navigation";
import { fetcher, type Schemas } from "@/lib/api";
import { PageHeading, VerifyRequired } from "./shared";

export type Recommended = Schemas["RecommendedOut"];

export function JobsScreen() {
  const t = useTranslations("dev.jobs");
  const { data, error, isLoading, mutate } = useSWR<Recommended>("/me/recommended-jobs", fetcher<Recommended>);
  return (
    <div>
      <PageHeading sub={t("sub")}>{t("title")}</PageHeading>
      <QueryState loading={isLoading} error={error} onRetry={() => void mutate()} />
      {data && data.jobs.length === 0 && (
        data.reason ? (
          <div className="flex flex-col gap-3">
            <p className="font-semibold">{t("notVerified")}</p>
            <VerifyRequired />
          </div>
        ) : (
          <p className="text-text-muted">{t("empty")}</p>
        )
      )}
      {data && data.jobs.length > 0 && (
        <ul className="flex flex-col gap-4">
          {data.jobs.map((j) => (
            <li key={j.posting_id}>
              <GlassCard>
                <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <h2 className="text-lg font-semibold break-words">
                      <Link href={`/dev/jobs/${j.posting_id}`} className="hover:text-accent-primary hover:underline">{j.title}</Link>
                    </h2>
                    <p className="text-sm text-text-muted">
                      {[j.location, j.remote ? t("remote") : null, j.tier ? t(`tier.${j.tier}` as "tier.junior") : null].filter(Boolean).join(" · ")}
                    </p>
                  </div>
                </div>
                <ScoreBar value={j.score} label={t("score")} />
                <div className="mt-3 flex flex-col gap-2">
                  {j.matched.length > 0 && (
                    <ul className="flex flex-wrap items-center gap-2" aria-label={t("matched")}>
                      {j.matched.map((s) => <li key={s}><Badge tone="match">{s}</Badge></li>)}
                    </ul>
                  )}
                  {j.missing.length > 0 && (
                    <ul className="flex flex-wrap items-center gap-2" aria-label={t("missing")}>
                      {j.missing.map((s) => <li key={s}><Badge tone="warning">{s}</Badge></li>)}
                    </ul>
                  )}
                </div>
                <Link href={`/dev/jobs/${j.posting_id}`} className="mt-3 inline-block text-sm text-accent-primary underline">{t("details")}</Link>
              </GlassCard>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
