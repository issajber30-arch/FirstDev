/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { clientIp } from "@/lib/clientIp";
import { getLocale, getTranslations } from "next-intl/server";
import { headers } from "next/headers";
import { notFound } from "next/navigation";
import { LocaleSwitcher } from "@/components/app/LocaleSwitcher";
import { Logo } from "@/components/brand/Logo";
import { Badge } from "@/components/ui/Badge";
import { GlassCard } from "@/components/ui/GlassCard";
import { Notice } from "@/components/ui/Notice";
import { Link } from "@/i18n/navigation";
import type { Schemas } from "@/lib/api";

type Profile = Schemas["PublicProfileOut"];

/** Server-side fetch, no cookies. The proxy secret lets the API trust the visitor IP we forward,
 *  so its per-IP rate limit counts the visitor and not this server. `no-store`: a profile made
 *  private must disappear at once. */
async function load(handle: string): Promise<Profile | "missing" | "limited" | "error"> {
  const base = (process.env.FIRSTDEV_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");
  const h: Record<string, string> = { accept: "application/json" };
  const secret = process.env.FIRSTDEV_PROXY_SECRET;
  if (secret) h["x-firstdev-proxy-secret"] = secret;
  const ip = clientIp((await headers()).get("x-forwarded-for"));
  if (ip) h["x-firstdev-client-ip"] = ip;
  try {
    const res = await fetch(`${base}/u/${encodeURIComponent(handle)}`, {
      cache: "no-store",
      headers: h,
      signal: AbortSignal.timeout(10_000),
    });
    if (res.status === 404) return "missing";
    if (res.status === 429) return "limited";
    return res.ok ? ((await res.json()) as Profile) : "error";
  } catch {
    return "error";
  }
}

export default async function Page({ params }: PageProps<"/[locale]/u/[handle]">) {
  const { handle } = await params;
  const [t, c, locale] = await Promise.all([getTranslations("pub"), getTranslations("common"), getLocale()]);
  const p = await load(handle);
  if (p === "missing") notFound();
  const date = new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeZone: "UTC" });
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-8 px-4 py-6 sm:px-8">
      <header className="flex items-center justify-between gap-4">
        <Link href="/" aria-label="FirstDev"><Logo className="h-9 w-auto" /></Link>
        <LocaleSwitcher />
      </header>
      {typeof p === "string" ? (
        <Notice tone="error">{p === "limited" ? t("limited") : c("genericError")}</Notice>
      ) : (
        <>
          <GlassCard className="flex flex-col gap-2">
            <h1 className="text-3xl font-semibold break-words">{p.display_name ?? p.handle}</h1>
            <p className="font-mono text-sm text-text-muted" dir="ltr">@{p.handle}</p>
            {p.headline && <p className="text-lg break-words">{p.headline}</p>}
            {p.tier && <div><Badge tone="match">{t(`tier.${p.tier}` as "tier.junior")}</Badge></div>}
          </GlassCard>
          <section aria-labelledby="badges">
            <h2 id="badges" className="mb-3 text-lg font-semibold">{t("badges")}</h2>
            {p.verified_badges.length === 0 ? (
              <p className="text-text-muted">{t("noBadges")}</p>
            ) : (
              <ul className="grid gap-3 sm:grid-cols-2">
                {p.verified_badges.map((b) => (
                  <li key={`${b.skill}-${b.source}`}>
                    <GlassCard className="flex flex-col gap-2 !p-4">
                      <div><Badge tone="verified">{b.skill}</Badge></div>
                      <p className="text-sm text-text-muted">
                        {t(`source.${b.source}`)} · <time dateTime={b.verified_at}>{date.format(new Date(b.verified_at))}</time>
                      </p>
                    </GlassCard>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </main>
  );
}
