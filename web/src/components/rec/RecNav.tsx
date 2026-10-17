/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import { useTranslations } from "next-intl";
import { Link, usePathname } from "@/i18n/navigation";

// Candidates live per posting (tab on the posting page), so the nav has Postings and "new".
const ITEMS = [
  ["postings", "/rec"],
  ["new", "/rec/postings/new"],
] as const;

export function RecNav() {
  const t = useTranslations("rec.nav");
  const pathname = usePathname();
  return (
    <nav aria-label={t("label")} className="mb-8">
      <ul className="flex flex-wrap gap-1">
        {ITEMS.map(([key, href]) => {
          const active = key === "new" ? pathname === href : pathname !== "/rec/postings/new";
          return (
            <li key={key}>
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={`block rounded-lg px-3 py-1.5 text-sm transition-colors ${active ? "bg-accent-primary/15 text-accent-primary" : "text-text-muted hover:bg-text-primary/10 hover:text-text-primary"}`}
              >
                {t(key)}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
