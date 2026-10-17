/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import useSWR from "swr";
import { Button } from "@/components/ui/Button";
import { GlassCard } from "@/components/ui/GlassCard";
import { Notice } from "@/components/ui/Notice";
import { QueryState } from "@/components/ui/QueryState";
import { api, fetcher, type Schemas } from "@/lib/api";
import { PageHeading, useApiErrorText } from "./shared";

type Person = Schemas["PersonOut"];
type Requests = Schemas["RequestsOut"];

export function ConnectionsScreen() {
  const t = useTranslations("dev.connections");
  const errText = useApiErrorText();
  const reqs = useSWR<Requests>("/me/connection-requests", fetcher<Requests>);
  const conns = useSWR<Person[]>("/me/connections", fetcher<Person[]>);
  const [busy, setBusy] = useState<string | null>(null);
  const [fail, setFail] = useState("");

  async function act(method: "POST" | "DELETE", path: string, id: string) {
    setBusy(id);
    setFail("");
    try {
      await api(method, path);
      await Promise.all([reqs.mutate(), conns.mutate()]);
    } catch (err) {
      setFail(errText(err));
    } finally {
      setBusy(null);
    }
  }

  const Who = ({ p }: { p: Person }) => (
    <div className="min-w-0">
      <p className="font-semibold break-words">{p.display_name ?? t("anonymous")}{p.handle && <span className="ms-2 font-mono text-xs text-text-muted" dir="ltr">@{p.handle}</span>}</p>
      {p.headline && <p className="text-sm break-words text-text-muted">{p.headline}</p>}
    </div>
  );
  const name = (p: Person) => p.display_name ?? t("anonymous");
  const Row = ({ p, children }: { p: Person; children: React.ReactNode }) => (
    <li className="flex flex-wrap items-center justify-between gap-3 border-t border-text-primary/10 py-3 first:border-t-0"><Who p={p} /><div className="flex gap-2">{children}</div></li>
  );

  const loading = reqs.isLoading || conns.isLoading;
  return (
    <div>
      <PageHeading sub={t("sub")}>{t("title")}</PageHeading>
      <QueryState loading={loading} error={reqs.error || conns.error} onRetry={() => { void reqs.mutate(); void conns.mutate(); }} />
      {fail && <Notice tone="error" className="mb-4">{fail}</Notice>}
      {reqs.data && conns.data && (
        <div className="flex flex-col gap-6">
          <GlassCard>
            <h2 className="mb-2 text-lg font-semibold">{t("incoming")}</h2>
            {reqs.data.incoming.length === 0 ? <p className="text-sm text-text-muted">{t("noIncoming")}</p> : (
              <ul>{reqs.data.incoming.map((p) => (
                <Row key={p.connection_id} p={p}>
                  <Button disabled={busy === p.connection_id} onClick={() => act("POST", `/connections/${p.connection_id}/accept`, p.connection_id)} aria-label={`${t("accept")}: ${name(p)}`}>{t("accept")}</Button>
                  <Button variant="ghost" disabled={busy === p.connection_id} onClick={() => act("POST", `/connections/${p.connection_id}/decline`, p.connection_id)} aria-label={`${t("decline")}: ${name(p)}`}>{t("decline")}</Button>
                </Row>
              ))}</ul>
            )}
          </GlassCard>
          <GlassCard>
            <h2 className="mb-2 text-lg font-semibold">{t("outgoing")}</h2>
            {reqs.data.outgoing.length === 0 ? <p className="text-sm text-text-muted">{t("noOutgoing")}</p> : (
              <ul>{reqs.data.outgoing.map((p) => (
                <Row key={p.connection_id} p={p}>
                  <Button variant="ghost" disabled={busy === p.connection_id} onClick={() => act("DELETE", `/connections/${p.connection_id}`, p.connection_id)} aria-label={`${t("cancel")}: ${name(p)}`}>{t("cancel")}</Button>
                </Row>
              ))}</ul>
            )}
          </GlassCard>
          <GlassCard>
            <h2 className="mb-2 text-lg font-semibold">{t("connections")}</h2>
            {conns.data.length === 0 ? <p className="text-sm text-text-muted">{t("noConnections")}</p> : (
              <ul>{conns.data.map((p) => (
                <Row key={p.connection_id} p={p}>
                  <Button variant="ghost" disabled={busy === p.connection_id} onClick={() => act("DELETE", `/connections/${p.connection_id}`, p.connection_id)} aria-label={`${t("remove")}: ${name(p)}`}>{t("remove")}</Button>
                </Row>
              ))}</ul>
            )}
          </GlassCard>
        </div>
      )}
    </div>
  );
}
