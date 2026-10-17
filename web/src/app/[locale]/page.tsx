/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { getTranslations } from "next-intl/server";
import { LocaleSwitcher } from "@/components/app/LocaleSwitcher";
import { Logo } from "@/components/brand/Logo";
import { DemoButtons } from "@/components/landing/DemoButtons";
import { buttonClass } from "@/components/ui/Button";
import { GlassCard } from "@/components/ui/GlassCard";
import { Link } from "@/i18n/navigation";

export default async function Landing() {
  const t = await getTranslations("landing");
  const c = await getTranslations("common");
  const steps = ["1", "2", "3"] as const;
  return (
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-16 px-4 py-6 sm:px-8">
      <header className="flex items-center justify-between">
        <span className="font-mono text-sm text-text-muted">FirstDev</span>
        <div className="flex items-center gap-3">
          <LocaleSwitcher />
          <Link href="/sign-in" className={buttonClass("ghost")}>
            {c("signIn")}
          </Link>
        </div>
      </header>
      <section className="flex flex-col items-center gap-6 text-center">
        <Logo className="h-24 w-auto sm:h-32" title="FirstDev" />
        <h1 className="max-w-2xl text-4xl font-bold tracking-tight sm:text-5xl">{t("tagline")}</h1>
        <p className="max-w-2xl text-lg text-text-muted">{t("subtitle")}</p>
        <DemoButtons />
      </section>
      <section aria-labelledby="how">
        <h2 id="how" className="mb-6 text-center text-2xl font-semibold">
          {t("how.title")}
        </h2>
        <ol className="grid gap-4 sm:grid-cols-3">
          {steps.map((n) => (
            <li key={n}>
              <GlassCard className="h-full">
                <h3 className="font-mono text-accent-primary">{t(`how.step${n}Title`)}</h3>
                <p className="mt-2 text-text-muted">{t(`how.step${n}Body`)}</p>
              </GlassCard>
            </li>
          ))}
        </ol>
      </section>
    </main>
  );
}
