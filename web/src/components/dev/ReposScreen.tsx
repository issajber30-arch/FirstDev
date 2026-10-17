/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef, useState, type FormEvent } from "react";
import useSWR, { useSWRConfig } from "swr";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { GlassCard } from "@/components/ui/GlassCard";
import { Input } from "@/components/ui/Input";
import { Notice } from "@/components/ui/Notice";
import { QueryState } from "@/components/ui/QueryState";
import { ScoreBar } from "@/components/ui/ScoreBar";
import { api, fetcher } from "@/lib/api";
import { POLL_MS, isActive, languageShares } from "@/lib/dev";
import type { Overview, RepoAnalysis } from "@/lib/devTypes";
import { PageHeading, StatusLine, useApiErrorText, useFocusWhen } from "./shared";

// Fixed palette for the languages bar: distinct hues, readable on the dark surface.
const LANG_COLORS = ["#00f2fe", "#ffb703", "#a78bfa", "#34d399", "#f472b6", "#60a5fa", "#fb923c"];

function Metric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col">
      <dt className="text-xs text-text-muted">{label}</dt>
      <dd className="font-mono text-lg text-accent-verified">{value}</dd>
    </div>
  );
}

function RepoCard({ id, owner, name }: { id: string; owner: string; name: string }) {
  const t = useTranslations("dev.repos");
  const { mutate: globalMutate } = useSWRConfig();
  const { data, error, mutate } = useSWR<RepoAnalysis>(`/repos/${id}/analysis`, fetcher<RepoAnalysis>, {
    refreshInterval: (d) => (!d || isActive(d.status) ? POLL_MS : 0),
    shouldRetryOnError: false,
  });
  const status = data?.status ?? null;
  const prev = useRef(status);
  useEffect(() => {
    if (isActive(prev.current) && !isActive(status)) {
      void globalMutate("/profiles/me/overview");
      void globalMutate("/me/recommended-jobs");
    }
    prev.current = status;
  }, [status, globalMutate]);

  const a = data?.analysis;
  const m = a?.metrics;
  const shares = languageShares(m?.languages);
  const flags: [string, boolean | undefined][] = [
    ["tests", m?.has_tests], ["ci", m?.has_ci], ["lint", m?.has_lint_config], ["readme", m?.has_readme], ["license", m?.has_license],
  ];
  return (
    <GlassCard>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-mono text-lg break-all">
          <a href={`https://github.com/${owner}/${name}`} target="_blank" rel="noopener noreferrer" className="text-accent-primary underline">{owner}/{name}</a>
        </h2>
        <StatusLine status={status} error={data?.last_error} />
      </div>
      {error && <Notice tone="error">{t("loadError")} <Button variant="ghost" onClick={() => void mutate()}>{t("retry")}</Button></Notice>}
      {isActive(status) && <p className="text-sm text-text-muted">{t("analyzing")}</p>}
      {a && m && (
        <div className="flex flex-col gap-5">
          {shares.length > 0 && (
            <section aria-label={t("languages")}>
              <h3 className="mb-2 text-sm font-semibold text-text-muted">{t("languages")}</h3>
              <div className="flex h-3 overflow-hidden rounded-full bg-text-primary/10" role="img" aria-label={shares.map((s) => `${s.name} ${s.pct}%`).join(", ")}>
                {shares.map((s, i) => (
                  <div key={s.name} style={{ inlineSize: `${s.pct}%`, backgroundColor: LANG_COLORS[i % LANG_COLORS.length] }} />
                ))}
              </div>
              <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                {shares.map((s, i) => (
                  <li key={s.name} className="flex items-center gap-1.5">
                    <span className="size-2.5 rounded-full" style={{ backgroundColor: LANG_COLORS[i % LANG_COLORS.length] }} aria-hidden="true" />
                    {s.name} <span className="font-mono text-text-muted">{s.pct}%</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
          <ul className="flex flex-wrap gap-2" aria-label={t("indicators")}>
            {flags.map(([k, on]) => (
              <li key={k}><Badge tone={on ? "verified" : "cv"}><span aria-hidden="true" className="me-1">{on ? "✓" : "✗"}</span>{t(`flag.${k}`)}<span className="sr-only"> {on ? t("yes") : t("no")}</span></Badge></li>
            ))}
          </ul>
          <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Metric label={t("commits")} value={m.commit_count ?? "–"} />
            <Metric label={t("authors")} value={m.author_count ?? "–"} />
            <Metric label={t("span")} value={t("days", { n: m.span_days ?? 0 })} />
            <Metric label={t("files")} value={m.total_files ?? "–"} />
          </dl>
          {a.assessment.architecture_summary && (
            <section>
              <h3 className="mb-1 text-sm font-semibold text-text-muted">{t("architecture")}</h3>
              <p className="break-words">{a.assessment.architecture_summary}</p>
              {a.assessment.complexity != null && <p className="mt-1 text-sm text-text-muted">{t("complexity")}: <span className="font-mono text-accent-verified">{a.assessment.complexity}/5</span></p>}
            </section>
          )}
          {a.assessment.best_practices && a.assessment.best_practices.length > 0 && (
            <section>
              <h3 className="mb-2 text-sm font-semibold text-text-muted">{t("practices")}</h3>
              <ul className="flex flex-col gap-1.5 text-sm">
                {a.assessment.best_practices.map((p, i) => (
                  <li key={i} className="break-words">
                    <span aria-hidden="true" className={p.observed ? "text-accent-verified" : "text-text-muted"}>{p.observed ? "✓" : "✗"}</span>
                    <span className="sr-only">{p.observed ? t("observed") : t("notObserved")}: </span>{" "}
                    {p.practice} {p.evidence_path && <code className="ms-1 font-mono text-xs text-text-muted" dir="ltr">{p.evidence_path}</code>}
                  </li>
                ))}
              </ul>
            </section>
          )}
          <section>
            <h3 className="mb-1 text-sm font-semibold text-text-muted">{t("tutorial")}</h3>
            <ScoreBar value={a.tutorial_likelihood * 100} unit="%" label={t("tutorial")} tone={a.tutorial_likelihood >= 0.7 ? "warning" : "primary"} />
            {a.tutorial_likelihood >= 0.7 && <p className="mt-1 text-sm text-warning">{t("tutorialWarn")}</p>}
          </section>
        </div>
      )}
    </GlassCard>
  );
}

export function ReposScreen() {
  const t = useTranslations("dev.repos");
  const errText = useApiErrorText();
  const ov = useSWR<Overview>("/profiles/me/overview", fetcher<Overview>);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "error" | "success"; text: string; n: number } | null>(null);
  const [url, setUrl] = useState("");
  const outcome = useFocusWhen<HTMLDivElement>(msg?.n);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const n = (msg?.n ?? 0) + 1;
    setBusy(true);
    setMsg(null);
    try {
      await api("POST", "/profiles/me/repos", { url: url.trim() });
      setUrl("");
      await ov.mutate();
      setMsg({ tone: "success", text: t("queued"), n });
    } catch (err) {
      setMsg({ tone: "error", text: errText(err), n });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeading sub={t("sub")}>{t("title")}</PageHeading>
      <div className="flex flex-col gap-6">
        <GlassCard>
          <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
            <Input label={t("url")} name="url" type="url" inputMode="url" required maxLength={300} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://github.com/owner/repo" className="font-mono" dir="ltr" />
            {msg && <Notice ref={outcome} tone={msg.tone}>{msg.text}</Notice>}
            <div><Button type="submit" disabled={busy || !url.trim()}>{busy ? t("adding") : t("add")}</Button></div>
          </form>
        </GlassCard>
        <QueryState loading={ov.isLoading} error={ov.error} onRetry={() => void ov.mutate()} />
        {ov.data && ov.data.repos.length === 0 && <p className="text-text-muted">{t("empty")}</p>}
        {ov.data?.repos.map((r) => <RepoCard key={r.id} id={r.id} owner={r.owner} name={r.name} />)}
      </div>
    </div>
  );
}
