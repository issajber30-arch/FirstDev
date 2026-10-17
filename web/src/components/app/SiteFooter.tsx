/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { getTranslations } from "next-intl/server";
import { Logo } from "@/components/brand/Logo";

/** Ownership notice shown at the bottom of every page, in both locales. */
export async function SiteFooter() {
  const t = await getTranslations("footer");
  return (
    <footer className="mt-16 border-t border-white/10">
      <div className="mx-auto flex max-w-5xl flex-col items-center gap-2 px-4 py-6 text-center text-sm text-slate-400 sm:flex-row sm:justify-between sm:text-start">
        <div className="flex items-center gap-2">
          <Logo className="h-5 w-auto" title="FirstDev" />
          <span>{t("tagline")}</span>
        </div>
        <p>
          {t("copyright", { year: 2026 })}{" "}
          <span className="text-slate-300">{t("creator")}</span>
        </p>
      </div>
    </footer>
  );
}
