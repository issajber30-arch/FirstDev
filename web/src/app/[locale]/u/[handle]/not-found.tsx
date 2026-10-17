/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { getTranslations } from "next-intl/server";
import { buttonClass } from "@/components/ui/Button";
import { Link } from "@/i18n/navigation";

export default async function NotFound() {
  const t = await getTranslations("pub");
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col items-start gap-4 px-4 py-16 sm:px-8">
      <p className="font-mono text-accent-primary">404</p>
      <h1 className="text-3xl font-semibold">{t("notFoundTitle")}</h1>
      <p className="text-text-muted">{t("notFoundBody")}</p>
      <Link href="/" className={buttonClass("secondary")}>{t("home")}</Link>
    </main>
  );
}
