/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import { useTranslations } from "next-intl";
import { useState, type KeyboardEvent } from "react";
import useSWR from "swr";
import { Badge } from "@/components/ui/Badge";
import { Button, buttonClass } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import { QueryState } from "@/components/ui/QueryState";
import { Link } from "@/i18n/navigation";
import { api, fetcher } from "@/lib/api";
import { flagLabel } from "@/lib/rec";
import { PageHeading, useApiErrorText } from "@/components/dev/shared";
import { Applicants } from "./Applicants";
import { Candidates } from "./Candidates";
import { STATUS_TONE, type Posting } from "./PostingsScreen";

const TABS = ["applicants", "candidates"] as const;
type Tab = (typeof TABS)[number];

export function PostingDetail({ postingId, initialTab }: { postingId: string; initialTab: Tab }) {
  const t = useTranslations("rec");
  const errText = useApiErrorText();
  const { data: p, error, isLoading, mutate } = useSWR<Posting>(`/postings/${postingId}`, fetcher<Posting>);
  const [tab, setTab] = useState<Tab>(initialTab);
  const [fail, setFail] = useState("");
  const [closing, setClosing] = useState(false);

  async function close() {
    setClosing(true);
    setFail("");
    try {
      await api("POST", `/postings/${postingId}/close`);
      await mutate();
    } catch (e) {
      setFail(errText(e));
    } finally {
      setClosing(false);
    }
  }

  function onKey(e: KeyboardEvent<HTMLButtonElement>) {
    const i = TABS.indexOf(tab);
    const next = e.key === "ArrowRight" || e.key === "ArrowLeft" ? TABS[(i + 1) % TABS.length] : e.key === "Home" ? TABS[0] : e.key === "End" ? TABS[TABS.length - 1] : null;
    if (!next) return;
    e.preventDefault();
    setTab(next);
    document.getElementById(`tab-${next}`)?.focus();
  }

  return (
    <div className="flex flex-col gap-6">
      <QueryState loading={isLoading} error={error} onRetry={() => void mutate()} />
      {p && (
        <>
          <div>
            <PageHeading>{p.title}</PageHeading>
            <div className="-mt-4 flex flex-wrap items-center gap-3">
              <Badge tone={STATUS_TONE[p.status]}>{t(`status.${p.status}`)}</Badge>
              {(p.injection_flags?.length ?? 0) > 0 && (
                <Badge tone="warning" title={t("flagHint")}>
                  {t("postingFlag", { kinds: (p.injection_flags as Record<string, unknown>[]).map(flagLabel).join(", ") })}
                </Badge>
              )}
              {p.status !== "closed" && <Link href={`/rec/postings/${p.id}/edit`} className={buttonClass("ghost")}>{t("postings.edit")}</Link>}
              {p.status === "open" && (
                <Button variant="ghost" disabled={closing} onClick={() => void close()}>{t("postings.close")}</Button>
              )}
            </div>
            {fail && <Notice tone="error" className="mt-3">{fail}</Notice>}
          </div>
          <div role="tablist" aria-label={t("tabs.label")} className="flex gap-1 border-b border-text-primary/10">
            {TABS.map((k) => (
              <button
                key={k}
                role="tab"
                id={`tab-${k}`}
                type="button"
                aria-selected={tab === k}
                aria-controls={`panel-${k}`}
                tabIndex={tab === k ? 0 : -1}
                onClick={() => setTab(k)}
                onKeyDown={onKey}
                className={`-mb-px border-b-2 px-4 py-2 text-sm ${tab === k ? "border-accent-primary text-accent-primary" : "border-transparent text-text-muted hover:text-text-primary"}`}
              >
                {t(`tabs.${k}`)}
              </button>
            ))}
          </div>
          <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} tabIndex={0}>
            {tab === "applicants" ? <Applicants postingId={p.id} /> : <Candidates posting={p} />}
          </div>
        </>
      )}
    </div>
  );
}
