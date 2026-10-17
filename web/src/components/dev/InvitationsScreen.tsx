/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import useSWR from "swr";
import { Badge } from "@/components/ui/Badge";
import { Button, buttonClass } from "@/components/ui/Button";
import { GlassCard } from "@/components/ui/GlassCard";
import { Notice } from "@/components/ui/Notice";
import { QueryState } from "@/components/ui/QueryState";
import { Link } from "@/i18n/navigation";
import { api, fetcher, type Schemas } from "@/lib/api";
import { PageHeading, useApiErrorText } from "./shared";

type Inv = Schemas["InvitationOut"];
const TONE = { sent: "match", accepted: "verified", declined: "cv" } as const;

export function InvitationsScreen() {
  const t = useTranslations("dev.invitations");
  const errText = useApiErrorText();
  const { data, error, isLoading, mutate } = useSWR<Inv[]>("/me/invitations", fetcher<Inv[]>);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [fail, setFail] = useState("");

  async function decline(id: string) {
    setBusyId(id);
    setFail("");
    try {
      await api("POST", `/invitations/${id}/decline`);
      await mutate();
    } catch (err) {
      setFail(errText(err));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div>
      <PageHeading sub={t("sub")}>{t("title")}</PageHeading>
      <QueryState loading={isLoading} error={error} onRetry={() => void mutate()} />
      {fail && <Notice tone="error" className="mb-4">{fail}</Notice>}
      {data && data.length === 0 && <p className="text-text-muted">{t("empty")}</p>}
      <ul className="flex flex-col gap-4">
        {data?.map((i) => (
          <li key={i.id}>
            <GlassCard>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="text-lg font-semibold break-words">{i.title}</h2>
                  <p className="font-mono text-xs text-text-muted" dir="ltr">{new Date(i.created_at).toLocaleDateString()}</p>
                </div>
                <Badge tone={TONE[i.status]}>{t(`status.${i.status}`)}</Badge>
              </div>
              {i.status === "sent" && (
                <div className="mt-3 flex flex-wrap gap-3">
                  <Link href={`/dev/jobs/${i.posting_id}`} className={buttonClass("primary")}>{t("apply")}</Link>
                  <Button variant="ghost" disabled={busyId === i.id} onClick={() => decline(i.id)} aria-label={`${t("decline")}: ${i.title}`}>
                    {busyId === i.id ? t("declining") : t("decline")}
                  </Button>
                </div>
              )}
            </GlassCard>
          </li>
        ))}
      </ul>
    </div>
  );
}
