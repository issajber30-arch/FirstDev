/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { Badge } from "@/components/ui/Badge";
import { Button, buttonClass } from "@/components/ui/Button";
import { GlassCard } from "@/components/ui/GlassCard";
import { Notice } from "@/components/ui/Notice";
import { QueryState } from "@/components/ui/QueryState";
import { ScoreBar } from "@/components/ui/ScoreBar";
import { Link } from "@/i18n/navigation";
import { ApiError, api, fetcher } from "@/lib/api";
import { breakdown } from "@/lib/dev";
import type { Detail, MyMatch } from "@/lib/devTypes";
import type { Recommended } from "./JobsScreen";
import { PageHeading, StatusLine, VerifyRequired, useApiErrorText, useFocusWhen, useJob } from "./shared";

type Match = MyMatch | { job_id: string };
const isQueued = (m: Match): m is { job_id: string } => "job_id" in m;

function SkillRows({ rows }: { rows: Detail[] }) {
  const t = useTranslations("dev.match");
  return (
    <ul className="flex flex-col gap-1">
      {rows.map((d) => (
        <li key={d.skill} className="flex flex-wrap items-center gap-2 text-sm">
          <span className="font-mono break-all">{d.skill}</span>
          {d.level ? <Badge tone={d.level === "cv" ? "cv" : "verified"}>{t(`level.${d.level}`)}</Badge> : <Badge tone="warning">{t("level.none")}</Badge>}
          <span className="ms-auto font-mono text-text-muted" dir="ltr">×{d.credit}</span>
        </li>
      ))}
    </ul>
  );
}

function Bullets({ title, items }: { title: string; items?: string[] }) {
  if (!items?.length) return null;
  return (
    <section>
      <h3 className="mb-1 text-sm font-semibold text-text-muted">{title}</h3>
      <ul className="list-disc ps-5 text-sm">
        {items.map((s, i) => <li key={i} className="break-words">{s}</li>)}
      </ul>
    </section>
  );
}

export function MatchDetail({ postingId }: { postingId: string }) {
  const t = useTranslations("dev.match");
  const errText = useApiErrorText();
  // Each fetch may queue an LLM job on the server, so no revalidation on focus or reconnect.
  const match = useSWR<Match>(`/me/matches/${postingId}`, fetcher<Match>, {
    revalidateOnFocus: false,
    revalidateOnReconnect: false,
    shouldRetryOnError: false,
  });
  const list = useSWR<Recommended>("/me/recommended-jobs", fetcher<Recommended>);
  const title = list.data?.jobs.find((j) => j.posting_id === postingId)?.title;

  const queuedJob = match.data && isQueued(match.data) ? match.data.job_id : null;
  const job = useJob(queuedJob);
  const jobStatus = job.data?.status;
  useEffect(() => {
    if (jobStatus === "done") void match.mutate(); // 202 -> job finished -> refetch the real result
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only react to the status change
  }, [jobStatus]);

  const [applying, setApplying] = useState(false);
  const [res, setRes] = useState<{ tone: "error" | "success"; text: string; verify?: boolean; n: number } | null>(null);
  const outcome = useFocusWhen<HTMLDivElement>(res?.n);
  async function apply() {
    const n = (res?.n ?? 0) + 1;
    setApplying(true);
    setRes(null);
    try {
      await api("POST", `/postings/${postingId}/apply`);
      setRes({ tone: "success", text: t("applied"), n });
    } catch (err) {
      const s = err instanceof ApiError ? err.status : 0;
      setRes({ tone: "error", text: s === 409 ? t("alreadyApplied") : errText(err), verify: s === 403, n });
    } finally {
      setApplying(false);
    }
  }

  const verifyNeeded = match.error instanceof ApiError && match.error.status === 403;
  const m = match.data && !isQueued(match.data) ? match.data : null;
  const rows = m ? breakdown(m.components) : [];

  return (
    <div>
      <PageHeading sub={title}>{t("title")}</PageHeading>
      <p className="mb-4"><Link href="/dev/jobs" className="text-sm text-accent-primary underline">{t("back")}</Link></p>
      {verifyNeeded ? <VerifyRequired /> : <QueryState loading={match.isLoading} error={match.error} onRetry={() => void match.mutate()} />}
      {queuedJob && (
        <Notice tone="info" className="flex flex-wrap items-center gap-3">
          <span>{jobStatus === "failed" ? t("scoreFailed") : t("scoring")}</span>
          <StatusLine status={jobStatus ?? "queued"} error={job.data?.last_error} />
          {jobStatus === "failed" && <Button variant="secondary" onClick={() => void match.mutate()}>{t("retry")}</Button>}
        </Notice>
      )}
      {m && (
        <div className="flex flex-col gap-6">
          <GlassCard>
            <div className="flex items-baseline gap-3">
              <p className="font-mono text-5xl text-accent-primary" aria-label={t("scoreLabel", { score: m.score })}>{m.score}</p>
              <p className="text-text-muted">/ 100</p>
            </div>
            <div className="mt-3"><ScoreBar value={m.score} label={t("scoreBar")} /></div>
          </GlassCard>

          <GlassCard>
            <h2 className="mb-1 text-lg font-semibold">{t("breakdown")}</h2>
            <p className="mb-4 text-sm text-text-muted">{t("breakdownHint")}</p>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-start text-text-muted">
                  <th scope="col" className="pb-2 text-start font-normal">{t("term")}</th>
                  <th scope="col" className="pb-2 text-end font-normal">{t("coverage")}</th>
                  <th scope="col" className="pb-2 text-end font-normal">{t("points")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.key} className="border-t border-text-primary/10">
                    <th scope="row" className="py-2 text-start font-normal">{t(`terms.${r.key}`)} <span className="font-mono text-xs text-text-muted" dir="ltr">×{r.weight}</span></th>
                    <td className="py-2 text-end font-mono" dir="ltr">{Math.round(r.coverage * 100)}%</td>
                    <td className="py-2 text-end font-mono text-accent-primary" dir="ltr">{r.points}/{r.weight}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="mt-5 grid gap-5 sm:grid-cols-2">
              <section>
                <h3 className="mb-2 text-sm font-semibold text-text-muted">{t("required")}</h3>
                {m.components.required.length ? <SkillRows rows={m.components.required} /> : <p className="text-sm text-text-muted">{t("none")}</p>}
              </section>
              <section>
                <h3 className="mb-2 text-sm font-semibold text-text-muted">{t("optional")}</h3>
                {m.components.optional.length ? <SkillRows rows={m.components.optional} /> : <p className="text-sm text-text-muted">{t("none")}</p>}
              </section>
            </div>
          </GlassCard>

          <GlassCard className="flex flex-col gap-4">
            <h2 className="text-lg font-semibold">{t("feedback")}</h2>
            <Bullets title={t("strengths")} items={m.feedback.strengths} />
            <Bullets title={t("missingSkills")} items={m.feedback.missing_skills} />
            <Bullets title={t("suggestions")} items={m.feedback.suggestions} />
            {!m.feedback.strengths?.length && !m.feedback.missing_skills?.length && !m.feedback.suggestions?.length && (
              <p className="text-sm text-text-muted">{t("noFeedback")}</p>
            )}
            {m.gaps.length > 0 && <Bullets title={t("gaps")} items={m.gaps} />}
          </GlassCard>

          <GlassCard className="flex flex-col gap-3">
            {res?.verify ? <VerifyRequired tone="error" /> : res && <Notice ref={outcome} tone={res.tone}>{res.text}</Notice>}
            <div className="flex flex-wrap gap-3">
              <Button onClick={apply} disabled={applying || res?.tone === "success"}>{applying ? t("applying") : t("apply")}</Button>
              {res?.tone === "success" && <Link href="/dev/applications" className={buttonClass("secondary")}>{t("viewApplications")}</Link>}
            </div>
          </GlassCard>
        </div>
      )}
    </div>
  );
}
