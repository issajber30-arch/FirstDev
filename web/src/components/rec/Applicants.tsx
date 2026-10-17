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
import { ApiError, api, fetcher, type Schemas } from "@/lib/api";
import { breakdown } from "@/lib/dev";
import type { Components } from "@/lib/devTypes";
import { flagLabel, nextStates, type AppStatus } from "@/lib/rec";
import { useApiErrorText } from "@/components/dev/shared";

type App = Schemas["RecruiterApplicationOut"];
type View = Schemas["RecruiterView"];
const TONE = { accepted: "verified", interview: "match", rejected: "warning", withdrawn: "cv", submitted: "cv", reviewing: "cv" } as const;
const LIVE = new Set(["generating", "ready", "in_progress", "submitted"]);

function AssessmentResult({ appId }: { appId: string }) {
  const t = useTranslations("rec.applicants");
  const { data, error, isLoading } = useSWR<View>(`/applications/${appId}/assessment`, fetcher<View>, {
    refreshInterval: (d) => (d && LIVE.has(d.status) ? 2000 : 0),
    shouldRetryOnError: false,
  });
  if (error instanceof ApiError && error.status === 404) return <p className="text-sm text-text-muted">{t("noAssessment")}</p>;
  if (isLoading) return <p role="status" className="text-sm text-text-muted">…</p>;
  if (error || !data) return <Notice tone="error">{t("assessmentError")}</Notice>;
  const taken = data.time_taken_seconds;
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-text-primary/10 p-4" aria-live="polite">
      <div className="flex flex-wrap items-center gap-3">
        <h4 className="font-semibold">{t("assessment")}</h4>
        <Badge tone={data.status === "graded" ? "verified" : data.status === "failed" || data.status === "expired" ? "warning" : "match"}>
          {t(`assessStatus.${data.status}`)}
        </Badge>
        {taken != null && (
          <span className="font-mono text-sm text-text-muted">{t("timeTaken", { m: Math.floor(taken / 60), s: taken % 60 })}</span>
        )}
      </div>
      {data.overall_pct != null && <ScoreBar value={data.overall_pct} unit="%" label={t("overall")} />}
      {data.skill_pcts && (
        <ul className="flex flex-col gap-2">
          {Object.entries(data.skill_pcts).map(([s, p]) => (
            <li key={s}>
              <span className="font-mono text-xs break-all">{s}</span>
              <ScoreBar value={p} unit="%" label={s} tone={p >= 70 ? "primary" : "warning"} />
            </li>
          ))}
        </ul>
      )}
      {data.short_answers.map((a, i) => (
        <section key={i} className="flex flex-col gap-1 border-t border-text-primary/10 pt-3">
          <p className="text-sm font-semibold break-words">
            <span className="font-mono text-text-muted">{a.skill}</span> · {a.prompt}
          </p>
          <p dir="auto" className="text-sm break-words whitespace-pre-wrap">{a.text}</p>
          {a.criteria_met.length > 0 && (
            <>
              <p className="text-xs text-accent-primary">{t("criteriaMet")}</p>
              <ul className="list-disc ps-5 text-sm">{a.criteria_met.map((c, j) => <li key={j} className="break-words">{c}</li>)}</ul>
            </>
          )}
          {a.injection_flags.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {a.injection_flags.map((f, j) => <Badge key={j} tone="warning">{t("answerFlag", { kind: flagLabel(f) })}</Badge>)}
            </div>
          )}
        </section>
      ))}
    </div>
  );
}

function Card({ a, onChanged }: { a: App; onChanged: () => Promise<unknown> }) {
  const t = useTranslations("rec.applicants");
  const errText = useApiErrorText();
  const [busy, setBusy] = useState(false);
  const [fail, setFail] = useState("");
  const [showAssess, setShowAssess] = useState(false);
  const [sent, setSent] = useState(false);
  const status = a.status as AppStatus;
  const rows = a.components ? breakdown(a.components as unknown as Components) : [];
  const canSend = status !== "withdrawn" && status !== "rejected";

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setFail("");
    try {
      await fn();
    } catch (e) {
      setFail(errText(e));
    } finally {
      setBusy(false);
    }
  }
  const move = (to: AppStatus) => run(async () => {
    await api("POST", `/applications/${a.application_id}/status`, { status: to });
    await onChanged();
  });
  const send = () => run(async () => {
    await api("POST", `/applications/${a.application_id}/assessment`);
    setSent(true);
    setShowAssess(true);
  });

  return (
    <GlassCard>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 dir="auto" className="text-lg font-semibold break-words">{a.headline ?? t("anonymous")}</h3>
          <p className="font-mono text-xs text-text-muted" dir="ltr">{new Date(a.created_at).toLocaleDateString()}</p>
        </div>
        <Badge tone={TONE[status]}>{t(`status.${status}`)}</Badge>
      </div>
      {a.injection_flags.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2" role="note">
          {(a.injection_flags as Record<string, unknown>[]).map((f, i) => <Badge key={i} tone="warning">{t("flag", { kind: flagLabel(f) })}</Badge>)}
        </div>
      )}
      {a.score != null && <div className="mt-3"><ScoreBar value={a.score} label={t("score")} /></div>}
      {rows.length > 0 && (
        <table className="mt-3 w-full text-sm">
          <caption className="sr-only">{t("breakdown")}</caption>
          <thead>
            <tr className="text-start text-text-muted">
              <th scope="col" className="py-1 text-start font-normal">{t("breakdown")}</th>
              <th scope="col" className="py-1 text-end font-normal">{t("points")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key}>
                <th scope="row" className="py-1 text-start font-normal">{t(`part.${r.key}`)}</th>
                <td className="py-1 text-end font-mono" dir="ltr">{r.points} / {r.weight}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {a.reasons && a.reasons.length > 0 && (
        <ul className="mt-3 list-disc ps-5 text-sm">{(a.reasons as string[]).map((r, i) => <li key={i} dir="auto" className="break-words">{String(r)}</li>)}</ul>
      )}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        {nextStates(status).map((s) => (
          <Button key={s} variant={s === "rejected" ? "ghost" : "secondary"} disabled={busy} onClick={() => void move(s)}>
            {t("moveTo", { status: t(`status.${s}`) })}
          </Button>
        ))}
        {canSend && !sent && (
          <Button variant="secondary" disabled={busy} onClick={() => void send()}>{t("sendAssessment")}</Button>
        )}
        <Button variant="ghost" aria-expanded={showAssess} onClick={() => setShowAssess((v) => !v)}>
          {showAssess ? t("hideAssessment") : t("viewAssessment")}
        </Button>
      </div>
      {fail && <Notice tone="error" className="mt-3">{fail}</Notice>}
      {sent && <Notice tone="success" className="mt-3">{t("sent")}</Notice>}
      {showAssess && <div className="mt-3"><AssessmentResult appId={a.application_id} /></div>}
    </GlassCard>
  );
}

export function Applicants({ postingId }: { postingId: string }) {
  const t = useTranslations("rec.applicants");
  const { data, error, isLoading, mutate } = useSWR<App[]>(`/postings/${postingId}/applications`, fetcher<App[]>);
  return (
    <div className="flex flex-col gap-4">
      <QueryState loading={isLoading} error={error} onRetry={() => void mutate()} />
      {data && data.length === 0 && <p className="text-text-muted">{t("empty")}</p>}
      {data?.map((a) => <Card key={a.application_id} a={a} onChanged={() => mutate()} />)}
    </div>
  );
}
