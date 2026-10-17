/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState, type FormEvent } from "react";
import useSWR, { useSWRConfig } from "swr";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { GlassCard } from "@/components/ui/GlassCard";
import { Notice } from "@/components/ui/Notice";
import { QueryState } from "@/components/ui/QueryState";
import { Textarea } from "@/components/ui/Textarea";
import { api, fetcher } from "@/lib/api";
import { MAX_PDF_BYTES } from "@/lib/dev";
import type { CvDoc, Overview } from "@/lib/devTypes";
import { PageHeading, SkillChip, StatusLine, useApiErrorText, useFocusWhen, useJob } from "./shared";

const TEXT_MAX = 5_000_000; // backend cap is PDF_MAX bytes; the textarea just stops absurd pastes

export function CvScreen() {
  const t = useTranslations("dev.cv");
  const errText = useApiErrorText();
  const { mutate: globalMutate } = useSWRConfig();
  const ov = useSWR<Overview>("/profiles/me/overview", fetcher<Overview>);
  const cvId = ov.data?.cv?.id;
  const cv = useSWR<CvDoc>(cvId ? `/cv/${cvId}` : null, fetcher<CvDoc>);
  const job = useJob(cv.data?.status === "pending" ? ov.data?.cv?.job_id : null);
  const jobStatus = job.data?.status;

  // When the worker finishes, reload the document and the overview (verified state, skills).
  useEffect(() => {
    if (jobStatus === "done" || jobStatus === "failed") {
      void cv.mutate();
      void ov.mutate();
      void globalMutate("/me/recommended-jobs");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only react to the status change
  }, [jobStatus]);

  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "error" | "success"; text: string; n: number } | null>(null);
  const [fileError, setFileError] = useState("");
  const outcome = useFocusWhen<HTMLDivElement>(msg?.n);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const d = new FormData(form);
    const file = d.get("file") as File | null;
    const pasted = String(d.get("text") ?? "").trim();
    const hasFile = !!file && file.size > 0;
    const n = (msg?.n ?? 0) + 1;
    if (hasFile === !!pasted) {
      setMsg({ tone: "error", text: t(hasFile ? "bothGiven" : "nothingGiven"), n });
      return;
    }
    if (hasFile && file.size > MAX_PDF_BYTES) {
      setFileError(t("fileTooLarge"));
      setMsg({ tone: "error", text: t("fileTooLarge"), n });
      return;
    }
    setFileError("");
    const body = new FormData();
    if (hasFile) body.set("file", file);
    else body.set("text", pasted);
    setBusy(true);
    setMsg(null);
    try {
      await api("POST", "/profiles/me/cv", body);
      form.reset();
      await ov.mutate();
      setMsg({ tone: "success", text: t("queued"), n });
    } catch (err) {
      setMsg({ tone: "error", text: errText(err), n });
    } finally {
      setBusy(false);
    }
  }

  const doc = cv.data;
  const status = doc?.status;
  const jobLine = status === "pending" ? (jobStatus ?? "queued") : status === "failed" ? "failed" : status === "parsed" ? "done" : null;

  return (
    <div>
      <PageHeading sub={t("sub")}>{t("title")}</PageHeading>
      <div className="flex flex-col gap-6">
        <GlassCard>
          <h2 className="mb-4 text-lg font-semibold">{t("uploadTitle")}</h2>
          <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="cv-file" className="text-sm text-text-muted">{t("file")}</label>
              <input id="cv-file" name="file" type="file" accept="application/pdf,.pdf" aria-invalid={fileError ? true : undefined} className="text-sm file:me-3 file:rounded-lg file:border file:border-accent-primary/50 file:bg-transparent file:px-3 file:py-1.5 file:text-accent-primary" />
              <p className="text-xs text-text-muted">{t("fileHint")}</p>
            </div>
            <p className="text-center text-sm text-text-muted" aria-hidden="true">{t("or")}</p>
            <Textarea name="text" label={t("paste")} rows={8} maxLength={TEXT_MAX} className="font-mono text-sm" />
            {msg && <Notice ref={outcome} tone={msg.tone}>{msg.text}</Notice>}
            <div><Button type="submit" disabled={busy}>{busy ? t("uploading") : t("submit")}</Button></div>
          </form>
        </GlassCard>

        <QueryState loading={ov.isLoading || cv.isLoading} error={ov.error || cv.error} onRetry={() => { void ov.mutate(); void cv.mutate(); }} />
        {ov.data && !ov.data.cv && <p className="text-text-muted">{t("empty")}</p>}

        {doc && (
          <GlassCard>
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold">{t("resultTitle")}</h2>
              <StatusLine status={jobLine} error={job.data?.last_error} />
            </div>
            {status === "needs_text" && <Notice tone="error">{t("needsText")}</Notice>}
            {doc.injection_flags && doc.injection_flags.length > 0 && (
              <Notice tone="error" className="mb-4">
                <p className="mb-2 font-semibold">{t("flagsTitle")}</p>
                <ul className="flex flex-wrap gap-2">
                  {doc.injection_flags.map((f, i) => (
                    <li key={i}><Badge tone="warning">{String(f.kind ?? f.pattern ?? t("flag"))}</Badge></li>
                  ))}
                </ul>
              </Notice>
            )}
            {doc.parse && (
              <div className="flex flex-col gap-6">
                {doc.parse.summary && <p className="break-words text-text-muted">{doc.parse.summary}</p>}
                <section aria-labelledby="cv-skills">
                  <h3 id="cv-skills" className="mb-2 font-semibold">{t("skills")}</h3>
                  <ul className="flex flex-wrap gap-2">
                    {doc.parse.skills.map((s, i) => (
                      <li key={i} className="flex items-center gap-1">
                        <SkillChip skill={s.name} level="cv" years={s.years} />
                        <Badge tone="cv" className="opacity-70">{s.category}</Badge>
                      </li>
                    ))}
                  </ul>
                </section>
                <section aria-labelledby="cv-exp">
                  <h3 id="cv-exp" className="mb-3 font-semibold">{t("experience")}</h3>
                  <ol className="border-s border-accent-primary/30 ps-5">
                    {doc.parse.experience.map((x, i) => (
                      <li key={i} className="relative mb-4">
                        <span className="absolute -start-[1.65rem] top-1.5 size-2 rounded-full bg-accent-primary" aria-hidden="true" />
                        <p className="font-semibold break-words">{x.title} · {x.company}</p>
                        <p className="font-mono text-xs text-text-muted">{x.start ?? "?"} – {x.end ?? "?"}</p>
                        {x.description && <p className="mt-1 text-sm break-words text-text-muted">{x.description}</p>}
                      </li>
                    ))}
                  </ol>
                  {doc.parse.gaps?.map((g, i) => (
                    <p key={i} className="text-sm text-warning">{t("gap", { months: g.months, start: g.start, end: g.end })}</p>
                  ))}
                </section>
                <section aria-labelledby="cv-edu">
                  <h3 id="cv-edu" className="mb-2 font-semibold">{t("education")}</h3>
                  {doc.parse.education.length === 0 ? (
                    <p className="text-sm text-text-muted">{t("noEducation")}</p>
                  ) : (
                    <ul className="flex flex-col gap-2">
                      {doc.parse.education.map((x, i) => (
                        <li key={i} className="text-sm break-words">
                          <span className="font-semibold">{x.institution}</span>
                          {[x.degree, x.field].filter(Boolean).length > 0 && <> · {[x.degree, x.field].filter(Boolean).join(", ")}</>}
                          <span className="ms-2 font-mono text-xs text-text-muted">{x.start ?? ""}{x.end ? ` – ${x.end}` : ""}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              </div>
            )}
          </GlassCard>
        )}
      </div>
    </div>
  );
}
