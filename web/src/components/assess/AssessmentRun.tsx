/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Button, buttonClass } from "@/components/ui/Button";
import { GlassCard } from "@/components/ui/GlassCard";
import { Notice } from "@/components/ui/Notice";
import { QueryState } from "@/components/ui/QueryState";
import { Textarea } from "@/components/ui/Textarea";
import { Link, useRouter } from "@/i18n/navigation";
import { api, type Schemas } from "@/lib/api";
import { PageHeading, useApiErrorText, useFocusWhen } from "@/components/dev/shared";
import { Countdown } from "./Countdown";
import { useMyAssessments } from "./AssessmentsScreen";

type Current = Schemas["CurrentOut"];
type Cur = Current | Schemas["DoneOut"];
const MAX_CHARS = 2000;

function Question({ id, onDone }: { id: string; onDone: () => Promise<unknown> }) {
  const t = useTranslations("dev.assess");
  const errText = useApiErrorText();
  const [cur, setCur] = useState<Cur | null>(null);
  const [rev, setRev] = useState(0); // new value on every response: re-mounts the Countdown to re-sync it
  const [choice, setChoice] = useState<number | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [confirm, setConfirm] = useState(false);
  const question = cur && "question_id" in cur ? cur : null;
  const heading = useFocusWhen<HTMLHeadingElement>(question?.question_id);

  const load = useCallback(async () => {
    try {
      const d = await api<Cur>("GET", `/assessments/${id}/current`);
      setCur(d);
      setRev((r) => r + 1);
      setChoice(null);
      setText("");
      setConfirm(false);
      if ("done" in d) await onDone();
    } catch (e) {
      setErr(errText(e));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- errText/onDone are stable enough; reload only per id
  }, [id]);
  useEffect(() => {
    void load(); // eslint-disable-line react-hooks/set-state-in-effect -- fetch on mount; state is set after the await
  }, [load]);

  async function submitAnswer(e: FormEvent) {
    e.preventDefault();
    if (!question || busy) return;
    setBusy(true);
    setErr("");
    try {
      const body =
        question.kind === "mcq" ? { question_id: question.question_id, choice_index: choice } : { question_id: question.question_id, text };
      await api("POST", `/assessments/${id}/answers`, body);
    } catch (e2) {
      setErr(errText(e2)); // e.g. "time is up": the reload below shows the finalized state
    }
    await load();
    setBusy(false);
  }

  async function finish() {
    setBusy(true);
    try {
      await api("POST", `/assessments/${id}/submit`);
      await onDone();
    } catch (e) {
      setErr(errText(e));
      setBusy(false);
    }
  }

  if (!question) return err ? <Notice tone="error">{err}</Notice> : <QueryState loading error={null} onRetry={() => {}} />;
  const isMcq = question.kind === "mcq";
  const canSubmit = isMcq ? choice !== null : text.trim().length > 0;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 ref={heading} tabIndex={-1} className="text-xl font-semibold">
          {t("questionOf", { n: question.index + 1, total: question.total })}
          <span className="ms-3 font-mono text-sm text-text-muted">{question.skill}</span>
        </h2>
        <Countdown key={rev} seconds={question.seconds_left} onExpire={() => void load()} />
      </div>
      <GlassCard>
        <form onSubmit={submitAnswer} className="flex flex-col gap-4">
          {isMcq ? (
            <fieldset className="flex flex-col gap-3">
              <legend dir="auto" className="mb-3 text-lg break-words whitespace-pre-wrap">{question.prompt}</legend>
              {question.options?.map((o, i) => (
                <label key={i} className="flex cursor-pointer items-start gap-3 rounded-lg border border-text-primary/10 p-3 has-[:checked]:border-accent-primary has-[:checked]:bg-accent-primary/10">
                  <input
                    type="radio"
                    name={`q-${question.question_id}`}
                    value={i}
                    checked={choice === i}
                    onChange={() => setChoice(i)}
                    className="mt-1 size-4 accent-accent-primary"
                  />
                  <span dir="auto" className="break-words">{o}</span>
                </label>
              ))}
            </fieldset>
          ) : (
            <>
              <p dir="auto" className="text-lg break-words whitespace-pre-wrap" id="short-prompt">
                {question.prompt}
              </p>
              <Textarea
                label={t("shortLabel")}
                value={text}
                onChange={(e) => setText(e.target.value)}
                maxLength={MAX_CHARS}
                rows={7}
                hint={t("counter", { n: text.length, max: MAX_CHARS })}
                aria-describedby="short-prompt"
              />
            </>
          )}
          {err && <Notice tone="error">{err}</Notice>}
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" disabled={busy || !canSubmit}>
              {t("submitAnswer")}
            </Button>
            {!confirm && (
              <Button variant="ghost" disabled={busy} onClick={() => setConfirm(true)}>
                {t("finish")}
              </Button>
            )}
          </div>
        </form>
        {confirm && (
          <Notice tone="info" className="mt-4 flex flex-wrap items-center gap-3">
            <span>{t("finishConfirm")}</span>
            <Button variant="secondary" disabled={busy} onClick={() => void finish()}>
              {t("finishYes")}
            </Button>
            <Button variant="ghost" onClick={() => setConfirm(false)}>
              {t("finishNo")}
            </Button>
          </Notice>
        )}
      </GlassCard>
    </div>
  );
}

export function AssessmentRun({ id }: { id: string }) {
  const t = useTranslations("dev.assess");
  const errText = useApiErrorText();
  const router = useRouter();
  const { data, error, isLoading, mutate } = useMyAssessments();
  const a = data?.find((x) => x.id === id);
  const [starting, setStarting] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (a?.status === "graded") router.replace(`/dev/assessments/${id}/report`);
  }, [a?.status, id, router]);

  async function begin() {
    setStarting(true);
    setErr("");
    try {
      await api("POST", `/assessments/${id}/start`);
      await mutate();
    } catch (e) {
      setErr(errText(e));
    } finally {
      setStarting(false);
    }
  }

  return (
    <div>
      <PageHeading sub={a?.skills.join(", ")}>{t("runTitle")}</PageHeading>
      <QueryState loading={isLoading} error={error} onRetry={() => void mutate()} />
      {data && !a && <Notice tone="error">{t("notFound")}</Notice>}
      {err && <Notice tone="error" className="mb-4">{err}</Notice>}
      {a?.status === "generating" && (
        <p role="status" className="animate-pulse text-text-muted">{t("generating")}</p>
      )}
      {a?.status === "ready" && (
        <GlassCard className="flex flex-col items-start gap-4">
          <p>{t("readyBody")}</p>
          <Button onClick={() => void begin()} disabled={starting}>{t("begin")}</Button>
        </GlassCard>
      )}
      {a?.status === "in_progress" && <Question id={id} onDone={() => mutate()} />}
      {a?.status === "submitted" && (
        <p role="status" className="animate-pulse text-text-muted">{t("grading")}</p>
      )}
      {a?.status === "graded" && (
        <Link href={`/dev/assessments/${id}/report`} className={buttonClass("primary")}>{t("viewReport")}</Link>
      )}
      {(a?.status === "failed" || a?.status === "expired") && <Notice tone="error">{t(`${a.status}Body`)}</Notice>}
    </div>
  );
}
