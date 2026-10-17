/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";
import useSWR from "swr";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ChipInput } from "@/components/ui/ChipInput";
import { GlassCard } from "@/components/ui/GlassCard";
import { Notice } from "@/components/ui/Notice";
import { QueryState } from "@/components/ui/QueryState";
import { Link, useRouter } from "@/i18n/navigation";
import { ApiError, api, fetcher, type Schemas } from "@/lib/api";
import { POLL_MS } from "@/lib/dev";
import { PageHeading, VerifyRequired, useApiErrorText, useFocusWhen } from "@/components/dev/shared";

export type MyAssessment = Schemas["MyAssessmentOut"];
const PENDING = new Set(["generating", "submitted"]);
const TONE = { graded: "verified", failed: "warning", expired: "warning" } as const;

/** The developer's assessments, polled while any is generating or being graded. */
export const useMyAssessments = () =>
  useSWR<MyAssessment[]>("/me/assessments", fetcher<MyAssessment[]>, {
    refreshInterval: (d) => (d?.some((a) => PENDING.has(a.status)) ? POLL_MS : 0),
  });

export function AssessmentsScreen() {
  const t = useTranslations("dev.assess");
  const errText = useApiErrorText();
  const router = useRouter();
  const { data, error, isLoading, mutate } = useMyAssessments();
  const [skills, setSkills] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [fail, setFail] = useState<{ text: string; verify: boolean; n: number } | null>(null);
  const outcome = useFocusWhen<HTMLDivElement>(fail?.n);

  async function onStart(e: FormEvent) {
    e.preventDefault();
    const n = (fail?.n ?? 0) + 1;
    if (skills.length === 0) {
      setFail({ text: t("needSkill"), verify: false, n });
      return;
    }
    setBusy(true);
    setFail(null);
    try {
      const q = await api<{ assessment_id: string }>("POST", "/me/assessments", { skills });
      await mutate();
      router.push(`/dev/assessments/${q.assessment_id}`);
    } catch (err) {
      setFail({ text: errText(err), verify: err instanceof ApiError && err.status === 403, n });
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-8">
      <PageHeading sub={t("sub")}>{t("title")}</PageHeading>
      <GlassCard>
        <form onSubmit={onStart} className="flex flex-col gap-4" noValidate>
          <h2 className="text-lg font-semibold">{t("startTitle")}</h2>
          <ChipInput
            label={t("skillsLabel")}
            hint={t("skillsHint")}
            value={skills}
            onChange={setSkills}
            max={3}
            removeLabel={(s) => t("removeSkill", { skill: s })}
          />
          {fail && (
            <Notice ref={outcome} tone="error">
              {fail.text}
            </Notice>
          )}
          {fail?.verify && <VerifyRequired />}
          <div>
            <Button type="submit" disabled={busy}>
              {busy ? t("starting") : t("start")}
            </Button>
          </div>
        </form>
      </GlassCard>
      <section aria-labelledby="mine">
        <h2 id="mine" className="mb-3 text-lg font-semibold">
          {t("listTitle")}
        </h2>
        <QueryState loading={isLoading} error={error} onRetry={() => void mutate()} />
        {data && data.length === 0 && <p className="text-text-muted">{t("empty")}</p>}
        <ul className="flex flex-col gap-3">
          {data?.map((a) => (
            <li key={a.id}>
              <GlassCard className="flex flex-wrap items-center justify-between gap-3 !p-4">
                <div className="flex min-w-0 flex-col gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone="cv">{t(`kind.${a.kind}`)}</Badge>
                    <Badge tone={TONE[a.status as keyof typeof TONE] ?? "match"}>{t(`status.${a.status}`)}</Badge>
                    <time className="font-mono text-xs text-text-muted" dir="ltr" dateTime={a.created_at}>
                      {new Date(a.created_at).toLocaleDateString()}
                    </time>
                  </div>
                  <ul className="flex flex-wrap gap-2" aria-label={t("skills")}>
                    {a.skills.map((s) => (
                      <li key={s}>
                        <Badge tone="match">{s}</Badge>
                      </li>
                    ))}
                  </ul>
                </div>
                <div className="flex items-center gap-4">
                  {a.overall_pct != null && (
                    <span className="font-mono text-lg text-accent-primary" dir="ltr" aria-label={t("overall")}>
                      {Math.round(a.overall_pct)}%
                    </span>
                  )}
                  <Link
                    href={a.status === "graded" ? `/dev/assessments/${a.id}/report` : `/dev/assessments/${a.id}`}
                    className="text-sm text-accent-primary underline"
                  >
                    {a.status === "graded" ? t("viewReport") : t("open")}
                  </Link>
                </div>
              </GlassCard>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
