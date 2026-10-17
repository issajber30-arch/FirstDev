/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import { useTranslations } from "next-intl";
import useSWR from "swr";
import { Badge } from "@/components/ui/Badge";
import { GlassCard } from "@/components/ui/GlassCard";
import { Notice } from "@/components/ui/Notice";
import { QueryState } from "@/components/ui/QueryState";
import { ScoreBar } from "@/components/ui/ScoreBar";
import { Link } from "@/i18n/navigation";
import { ApiError, fetcher, type Schemas } from "@/lib/api";
import { PageHeading } from "@/components/dev/shared";

type Report = Schemas["DeveloperReport"];
type Q = Schemas["QuestionReport"];

function List({ title, items, tone }: { title: string; items: string[]; tone: "match" | "warning" }) {
  if (!items.length) return null;
  return (
    <section>
      <h4 className={`mb-1 text-sm font-semibold ${tone === "warning" ? "text-warning" : "text-accent-primary"}`}>{title}</h4>
      <ul className="list-disc ps-5 text-sm">
        {items.map((c, i) => (
          <li key={i} dir="auto" className="break-words">{c}</li>
        ))}
      </ul>
    </section>
  );
}

function Review({ q }: { q: Q }) {
  const t = useTranslations("dev.assess.report");
  return (
    <GlassCard className="flex flex-col gap-3 !p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-semibold">{t("question", { n: q.position + 1 })}</h3>
        <Badge tone="match">{q.skill}</Badge>
        <Badge tone={q.correct ? "verified" : "warning"}>{q.correct ? t("correct") : t("incorrect")}</Badge>
        <span className="ms-auto font-mono text-xs text-text-muted" dir="ltr">
          {t("points", { p: q.points, max: q.possible })}
        </span>
      </div>
      <p dir="auto" className="break-words whitespace-pre-wrap">{q.prompt}</p>
      {q.kind === "mcq" ? (
        <>
          <ol className="flex flex-col gap-2" type="A">
            {q.options?.map((o, i) => (
              <li key={i} className={`flex flex-wrap items-center gap-2 rounded-lg border p-2 text-sm ${i === q.correct_index ? "border-accent-verified/50" : "border-text-primary/10"}`}>
                <span dir="auto" className="break-words">{o}</span>
                {i === q.your_choice && <Badge tone={i === q.correct_index ? "verified" : "warning"}>{t("yourChoice")}</Badge>}
                {i === q.correct_index && <Badge tone="verified">{t("correctAnswer")}</Badge>}
              </li>
            ))}
          </ol>
          {q.your_choice == null && <p className="text-sm text-warning">{t("unanswered")}</p>}
          {q.explanation && (
            <p className="text-sm">
              <span className="font-semibold text-text-muted">{t("explanation")}: </span>
              <span dir="auto">{q.explanation}</span>
            </p>
          )}
        </>
      ) : (
        <>
          <section>
            <h4 className="mb-1 text-sm font-semibold text-text-muted">{t("yourAnswer")}</h4>
            {q.your_text ? <p dir="auto" className="text-sm break-words whitespace-pre-wrap">{q.your_text}</p> : <p className="text-sm text-warning">{t("unanswered")}</p>}
          </section>
          <List title={t("criteriaMet")} items={q.criteria_met ?? []} tone="match" />
          <List title={t("criteriaMissed")} items={q.criteria_missed ?? []} tone="warning" />
          {q.feedback && (
            <p className="text-sm">
              <span className="font-semibold text-text-muted">{t("feedback")}: </span>
              <span dir="auto">{q.feedback}</span>
            </p>
          )}
          {q.model_answer && (
            <section>
              <h4 className="mb-1 text-sm font-semibold text-text-muted">{t("modelAnswer")}</h4>
              <p dir="auto" className="text-sm break-words whitespace-pre-wrap">{q.model_answer}</p>
            </section>
          )}
        </>
      )}
    </GlassCard>
  );
}

export function AssessmentReport({ id }: { id: string }) {
  const t = useTranslations("dev.assess.report");
  const { data, error, isLoading, mutate } = useSWR<Report>(`/assessments/${id}/report`, fetcher<Report>, { shouldRetryOnError: false });
  const notReady = error instanceof ApiError && error.status === 409;
  return (
    <div className="flex flex-col gap-6">
      <PageHeading>{t("title")}</PageHeading>
      <Link href="/dev/assessments" className="-mt-4 text-sm text-accent-primary underline">{t("back")}</Link>
      {notReady ? (
        <Notice tone="info">
          {t("notReady")} <Link href={`/dev/assessments/${id}`} className="underline">{t("goToAssessment")}</Link>
        </Notice>
      ) : (
        <QueryState loading={isLoading} error={error} onRetry={() => void mutate()} />
      )}
      {data && (
        <>
          <GlassCard className="flex flex-col gap-4">
            <p className="text-sm text-text-muted">{t("overall")}</p>
            <ScoreBar value={data.overall_pct} unit="%" label={t("overall")} />
            <h2 className="text-lg font-semibold">{t("perSkill")}</h2>
            <ul className="flex flex-col gap-3">
              {Object.entries(data.skill_pcts).map(([s, p]) => (
                <li key={s} className="flex flex-col gap-1">
                  <span className="font-mono text-sm break-all">{s}</span>
                  <ScoreBar value={p} unit="%" label={s} tone={p >= 70 ? "primary" : "warning"} />
                </li>
              ))}
            </ul>
          </GlassCard>
          <section aria-labelledby="strengths">
            <h2 id="strengths" className="mb-2 text-lg font-semibold">{t("strengths")}</h2>
            {data.strengths.length ? (
              <ul className="flex flex-wrap gap-2">
                {data.strengths.map((s) => <li key={s}><Badge tone="verified">{s}</Badge></li>)}
              </ul>
            ) : (
              <p className="text-text-muted">{t("noStrengths")}</p>
            )}
          </section>
          {data.study_suggestions.length > 0 && (
            <section aria-labelledby="study">
              <h2 id="study" className="mb-2 text-lg font-semibold">{t("study")}</h2>
              <ul className="flex flex-col gap-3">
                {data.study_suggestions.map((s) => (
                  <li key={s.skill}>
                    <GlassCard className="!p-4">
                      <p className="mb-1 flex items-center gap-3 font-semibold">
                        <span className="font-mono">{s.skill}</span>
                        <span className="font-mono text-sm text-warning" dir="ltr">{Math.round(s.pct)}%</span>
                      </p>
                      {s.missed_prompts.length > 0 && (
                        <>
                          <p className="text-sm text-text-muted">{t("revisit")}</p>
                          <ul className="list-disc ps-5 text-sm">
                            {s.missed_prompts.map((p, i) => <li key={i} dir="auto" className="break-words">{p}</li>)}
                          </ul>
                        </>
                      )}
                    </GlassCard>
                  </li>
                ))}
              </ul>
            </section>
          )}
          <section aria-labelledby="review">
            <h2 id="review" className="mb-3 text-lg font-semibold">{t("review")}</h2>
            <ol className="flex flex-col gap-4" data-testid="review">
              {data.questions.map((q) => <li key={q.position}><Review q={q} /></li>)}
            </ol>
          </section>
        </>
      )}
    </div>
  );
}
