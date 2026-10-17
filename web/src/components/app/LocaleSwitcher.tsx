/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import { useLocale, useTranslations } from "next-intl";
import { Link, usePathname } from "@/i18n/navigation";
import { routing } from "@/i18n/routing";

const LABELS: Record<string, string> = { en: "English", he: "עברית" };

export function LocaleSwitcher() {
  const current = useLocale();
  const pathname = usePathname();
  const t = useTranslations("common");
  return (
    <nav aria-label={t("language")} className="flex gap-2 text-sm">
      {routing.locales.map((l) => (
        <Link
          key={l}
          href={pathname}
          locale={l}
          lang={l}
          hrefLang={l}
          aria-current={l === current ? "true" : undefined}
          className={`rounded px-2 py-1 ${l === current ? "text-accent-primary" : "text-text-muted hover:text-text-primary"}`}
        >
          {LABELS[l]}
        </Link>
      ))}
    </nav>
  );
}
