/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { GlassCard } from "@/components/ui/GlassCard";
import { Notice } from "@/components/ui/Notice";
import { QueryState } from "@/components/ui/QueryState";
import { ScoreBar } from "@/components/ui/ScoreBar";
import { ApiError, api, fetcher, type Schemas } from "@/lib/api";
import { StatusLine, useApiErrorText, useJob } from "@/components/dev/shared";
import type { Posting } from "./PostingsScreen";

type Card = Schemas["CandidateCard"];

function CandidateCardView({ c, postingId }: { c: Card; postingId: string }) {
  const t = useTranslations("rec.candidates");
  const errText = useApiErrorText();
  const [state, setState] = useState<"idle" | "busy" | "invited">("idle");
  const [fail, setFail] = useState("");
  async function invite() {
    setState("busy");
    setFail("");
    try {
      await api("POST", `/postings/${postingId}/invite`, { profile_id: c.profile_id });
      setState("invited");
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setState("invited"); // already invited
      else {
        setFail(errText(e));
        setState("idle");
      }
    }
  }
  return (
    <GlassCard>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 dir="auto" className="text-lg font-semibold break-words">{c.headline ?? t("anonymous")}</h3>
          {c.tier && <p className="text-sm text-text-muted">{t(`tier.${c.tier}` as "tier.junior")}</p>}
        </div>
        {c.stale && <Badge tone="warning" title={t("staleHint")}>{t("stale")}</Badge>}
      </div>
      <div className="mt-3"><ScoreBar value={c.score} label={t("score")} /></div>
      {c.verified_skills.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-2" aria-label={t("verifiedSkills")}>
          {c.verified_skills.map((s) => <li key={s}><Badge tone="verified">{s}</Badge></li>)}
        </ul>
      )}
      {c.cv_skills.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-2" aria-label={t("cvSkills")}>
          {c.cv_skills.map((s) => <li key={s}><Badge tone="cv">{s}</Badge></li>)}
        </ul>
      )}
      {c.repos.length > 0 && (
        <section className="mt-3">
          <h4 className="mb-1 text-sm font-semibold text-text-muted">{t("repos")}</h4>
          <ul className="flex flex-col gap-1 text-sm">
            {c.repos.map((r) => (
              <li key={r.name} className="break-words">
                <span dir="ltr" className="font-mono text-accent-verified">{r.name}</span>
                {r.complexity != null && <span className="ms-2 font-mono text-xs text-text-muted" dir="ltr">{t("complexity", { n: r.complexity })}</span>}
                <span dir="auto" className="block text-text-muted">{r.summary}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {c.reasons.length > 0 && (
        <ul className="mt-3 list-disc ps-5 text-sm">{c.reasons.map((r, i) => <li key={i} dir="auto" className="break-words">{r}</li>)}</ul>
      )}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Button variant="secondary" disabled={state !== "idle"} onClick={() => void invite()}>
          {state === "invited" ? t("invited") : t("invite")}
        </Button>
        {state === "invited" && <span role="status" className="sr-only">{t("invited")}</span>}
      </div>
      {fail && <Notice tone="error" className="mt-3">{fail}</Notice>}
    </GlassCard>
  );
}

export function Candidates({ posting }: { posting: Posting }) {
  const t = useTranslations("rec.candidates");
  const errText = useApiErrorText();
  const { data, error, isLoading, mutate } = useSWR<Card[]>(`/postings/${posting.id}/candidates`, fetcher<Card[]>);
  const [jobId, setJobId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [fail, setFail] = useState("");
  const job = useJob(jobId);
  const status = job.data?.status;
  useEffect(() => {
    if (status === "done") void mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only react to the status change
  }, [status]);

  async function rank() {
    setBusy(true);
    setFail("");
    try {
      const r = await api<{ job_id: string }>("POST", `/postings/${posting.id}/rank`);
      setJobId(r.job_id);
    } catch (e) {
      setFail(errText(e));
    } finally {
      setBusy(false);
    }
  }
  const running = status === "queued" || status === "running" || (!!jobId && !status);
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button disabled={busy || running || posting.status !== "open"} onClick={() => void rank()}>{t("rank")}</Button>
        <StatusLine status={status} error={job.data?.last_error} />
      </div>
      {posting.status !== "open" && <p className="text-sm text-text-muted">{t("needOpen")}</p>}
      {fail && <Notice tone="error">{fail}</Notice>}
      <QueryState loading={isLoading} error={error} onRetry={() => void mutate()} />
      {data && data.length === 0 && <p className="text-text-muted">{t("empty")}</p>}
      {data?.map((c) => <CandidateCardView key={c.profile_id} c={c} postingId={posting.id} />)}
    </div>
  );
}
