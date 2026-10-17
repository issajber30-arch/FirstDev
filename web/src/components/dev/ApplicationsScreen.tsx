/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import useSWR from "swr";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { GlassCard } from "@/components/ui/GlassCard";
import { Notice } from "@/components/ui/Notice";
import { QueryState } from "@/components/ui/QueryState";
import { ScoreBar } from "@/components/ui/ScoreBar";
import { Link } from "@/i18n/navigation";
import { api, fetcher, type Schemas } from "@/lib/api";
import { PageHeading, useApiErrorText } from "./shared";

type App = Schemas["MyApplicationOut"];
const WITHDRAWABLE = new Set(["submitted", "reviewing", "interview"]);
const TONE = { accepted: "verified", interview: "match", rejected: "warning", withdrawn: "cv", submitted: "cv", reviewing: "cv" } as const;

export function ApplicationsScreen() {
  const t = useTranslations("dev.applications");
  const errText = useApiErrorText();
  const { data, error, isLoading, mutate } = useSWR<App[]>("/me/applications", fetcher<App[]>);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [fail, setFail] = useState("");

  async function withdraw(id: string) {
    setBusyId(id);
    setFail("");
    try {
      await api("POST", `/applications/${id}/withdraw`);
      await mutate();
    } catch (err) {
      setFail(errText(err));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div>
      <PageHeading>{t("title")}</PageHeading>
      <QueryState loading={isLoading} error={error} onRetry={() => void mutate()} />
      {fail && <Notice tone="error" className="mb-4">{fail}</Notice>}
      {data && data.length === 0 && (
        <p className="text-text-muted">{t("empty")} <Link href="/dev/jobs" className="text-accent-primary underline">{t("browse")}</Link></p>
      )}
      <ul className="flex flex-col gap-4">
        {data?.map((a) => (
          <li key={a.application_id}>
            <GlassCard>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="text-lg font-semibold break-words">{a.title}</h2>
                  <p className="font-mono text-xs text-text-muted" dir="ltr">{new Date(a.created_at).toLocaleDateString()}</p>
                </div>
                <Badge tone={TONE[a.status]}>{t(`status.${a.status}`)}</Badge>
              </div>
              {a.score != null && <div className="mt-3"><ScoreBar value={a.score} label={t("score")} /></div>}
              <div className="mt-3 flex flex-wrap items-center gap-4">
                <Link href={`/dev/jobs/${a.posting_id}`} className="text-sm text-accent-primary underline">{t("viewMatch")}</Link>
                {WITHDRAWABLE.has(a.status) && (
                  <Button variant="ghost" disabled={busyId === a.application_id} onClick={() => withdraw(a.application_id)} aria-label={`${t("withdraw")}: ${a.title}`}>
                    {busyId === a.application_id ? t("withdrawing") : t("withdraw")}
                  </Button>
                )}
              </div>
            </GlassCard>
          </li>
        ))}
      </ul>
    </div>
  );
}
