/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { useMe } from "@/lib/useMe";

export function formatRemaining(ms: number): string {
  const mins = Math.max(0, Math.floor(ms / 60_000));
  return `${String(Math.floor(mins / 60)).padStart(2, "0")}:${String(mins % 60).padStart(2, "0")}`;
}

export function SandboxBanner({ sandbox, expiresAt }: { sandbox: boolean; expiresAt: string | null }) {
  const t = useTranslations("sandbox");
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!sandbox) return;
    const id = setInterval(() => setNow(Date.now()), 15_000);
    return () => clearInterval(id);
  }, [sandbox]);
  if (!sandbox) return null;
  const left = expiresAt ? new Date(expiresAt).getTime() - now : 0;
  return (
    <div role="status" className="border-b border-accent-verified/40 bg-accent-verified/10 px-4 py-2 text-center font-mono text-sm text-accent-verified">
      {left > 0 ? t("banner", { time: formatRemaining(left) }) : t("expired")}
    </div>
  );
}

/** Reads /me; renders nothing for real users. */
export function MeSandboxBanner() {
  const { data } = useMe();
  return <SandboxBanner sandbox={data?.sandbox ?? false} expiresAt={data?.expires_at ?? null} />;
}
