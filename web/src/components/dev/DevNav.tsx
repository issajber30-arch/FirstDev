/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import { useTranslations } from "next-intl";
import { Link, usePathname } from "@/i18n/navigation";

const ITEMS = [
  ["dashboard", "/dev"],
  ["profile", "/dev/profile"],
  ["cv", "/dev/cv"],
  ["repos", "/dev/repos"],
  ["jobs", "/dev/jobs"],
  ["applications", "/dev/applications"],
  ["invitations", "/dev/invitations"],
  ["assessments", "/dev/assessments"],
  ["connections", "/dev/connections"],
] as const;

export function DevNav() {
  const t = useTranslations("dev.nav");
  const pathname = usePathname();
  return (
    <nav aria-label={t("label")} className="mb-8">
      <ul className="flex flex-wrap gap-1">
        {ITEMS.map(([key, href]) => {
          const active = href === "/dev" ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);
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
