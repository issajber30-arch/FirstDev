/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import { useTranslations } from "next-intl";
import useSWR from "swr";
import { Badge } from "@/components/ui/Badge";
import { buttonClass } from "@/components/ui/Button";
import { GlassCard } from "@/components/ui/GlassCard";
import { QueryState } from "@/components/ui/QueryState";
import { Link } from "@/i18n/navigation";
import { fetcher, type Schemas } from "@/lib/api";
import { PageHeading } from "@/components/dev/shared";

export type Posting = Schemas["PostingOut"];
export const STATUS_TONE = { open: "verified", draft: "cv", closed: "warning" } as const;

export function PostingsScreen() {
  const t = useTranslations("rec");
  const { data, error, isLoading, mutate } = useSWR<Posting[]>("/postings/mine", fetcher<Posting[]>);
  return (
    <div>
      <PageHeading sub={t("postings.sub")}>{t("postings.title")}</PageHeading>
      <QueryState loading={isLoading} error={error} onRetry={() => void mutate()} />
      {data && data.length === 0 && (
        <p className="text-text-muted">
          {t("postings.empty")}{" "}
          <Link href="/rec/postings/new" className="text-accent-primary underline">{t("postings.create")}</Link>
        </p>
      )}
      <ul className="flex flex-col gap-4">
        {data?.map((p) => (
          <li key={p.id}>
            <GlassCard>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="text-lg font-semibold break-words">
                    <Link href={`/rec/postings/${p.id}`} className="hover:text-accent-primary hover:underline">{p.title}</Link>
                  </h2>
                  <p className="text-sm text-text-muted">
                    {[p.location, p.remote ? t("form.remote") : null, p.tier ? t(`tier.${p.tier}` as "tier.junior") : null].filter(Boolean).join(" · ")}
                  </p>
                </div>
                <Badge tone={STATUS_TONE[p.status]}>{t(`status.${p.status}`)}</Badge>
              </div>
              <ul className="mt-3 flex flex-wrap gap-2" aria-label={t("form.required")}>
                {p.required_skills.map((s) => <li key={s}><Badge tone="match">{s}</Badge></li>)}
                {p.optional_skills.map((s) => <li key={s}><Badge tone="cv">{s}</Badge></li>)}
              </ul>
              <div className="mt-4 flex flex-wrap gap-3">
                <Link href={`/rec/postings/${p.id}`} className={buttonClass("secondary")}>{t("postings.applicants")}</Link>
                <Link href={`/rec/postings/${p.id}?tab=candidates`} className={buttonClass("secondary")}>{t("postings.candidates")}</Link>
                {p.status !== "closed" && <Link href={`/rec/postings/${p.id}/edit`} className={buttonClass("ghost")}>{t("postings.edit")}</Link>}
              </div>
            </GlassCard>
          </li>
        ))}
      </ul>
    </div>
  );
}
