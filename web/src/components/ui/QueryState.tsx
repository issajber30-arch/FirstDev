/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import { useTranslations } from "next-intl";
import { Button } from "./Button";
import { Notice } from "./Notice";

/** Loading and error states for an SWR read; renders nothing once there is data. */
export function QueryState({
  loading,
  error,
  onRetry,
}: {
  loading: boolean;
  error: unknown;
  onRetry: () => void;
}) {
  const t = useTranslations("common");
  if (error)
    return (
      <Notice tone="error" className="flex flex-wrap items-center justify-between gap-3">
        <span>{t("genericError")}</span>
        <Button variant="secondary" onClick={onRetry}>
          {t("retry")}
        </Button>
      </Notice>
    );
  if (loading)
    return (
      <p role="status" className="animate-pulse text-text-muted">
        {t("loading")}
      </p>
    );
  return null;
}
