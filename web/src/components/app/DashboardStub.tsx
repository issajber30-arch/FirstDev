/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import { useTranslations } from "next-intl";
import { GlassCard } from "@/components/ui/GlassCard";
import { useMe } from "@/lib/useMe";

export function DashboardStub() {
  const t = useTranslations("dashboard");
  const { data } = useMe();
  return (
    <GlassCard>
      <h1 className="text-2xl font-semibold">{t("title")}</h1>
      {data && <p className="mt-2 text-text-muted">{t("welcome", { name: data.display_name ?? data.email })}</p>}
    </GlassCard>
  );
}
