/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import { useTranslations } from "next-intl";
import useSWR from "swr";
import { Badge } from "@/components/ui/Badge";
import { buttonClass } from "@/components/ui/Button";
import { GlassCard } from "@/components/ui/GlassCard";
import { Notice } from "@/components/ui/Notice";
import { QueryState } from "@/components/ui/QueryState";
import { Link } from "@/i18n/navigation";
import { fetcher, type Schemas } from "@/lib/api";
import { completeness, groupSkills } from "@/lib/dev";
import type { Level, Overview } from "@/lib/devTypes";
import { useMe } from "@/lib/useMe";
import { PageHeading, SkillChip } from "./shared";

const LEVELS: Level[] = ["repo", "assessment", "cv"];
const LINK_FOR: Record<string, string> = { cv: "/dev/cv", repo: "/dev/repos" };
const QUICK = ["profile", "cv", "repos", "jobs", "applications", "connections"] as const;

export function Dashboard() {
  const t = useTranslations("dev.dashboard");
  const tn = useTranslations("dev.nav");
  const { data: me } = useMe();
  const ov = useSWR<Overview>("/profiles/me/overview", fetcher<Overview>);
  const prof = useSWR<Schemas["ProfileOut"]>("/profiles/me", fetcher<Schemas["ProfileOut"]>);
  const loading = ov.isLoading || prof.isLoading;
  const err = ov.error || prof.error;
  const done = ov.data && prof.data ? completeness(ov.data, prof.data) : null;
  const groups = ov.data ? groupSkills(ov.data.skills) : null;

  return (
    <div>
      <PageHeading sub={me && t("welcome", { name: me.display_name ?? me.email })}>{t("title")}</PageHeading>
      <QueryState loading={loading} error={err} onRetry={() => { void ov.mutate(); void prof.mutate(); }} />
      {ov.data && done && groups && (
        <div className="flex flex-col gap-6">
          {!ov.data.verified && (
            <Notice className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="font-semibold">{t("verifyTitle")}</p>
                <p className="text-text-muted">{t("verifyBody")}</p>
              </div>
              <Link href={ov.data.cv?.status === "parsed" ? "/dev/repos" : "/dev/cv"} className={buttonClass("primary", "shrink-0")}>
                {t("verifyCta")}
              </Link>
            </Notice>
          )}

          <GlassCard>
            <h2 className="mb-1 text-lg font-semibold">{t("completeness")}</h2>
            <p className="mb-3 font-mono text-3xl text-accent-primary">{done.percent}%</p>
            <ul className="grid gap-2 sm:grid-cols-2">
              {done.items.map((i) => (
                <li key={i.key} className="flex items-center gap-2 text-sm">
                  <span aria-hidden="true" className={i.done ? "text-accent-verified" : "text-text-muted"}>{i.done ? "✓" : "○"}</span>
                  <span className="sr-only">{i.done ? t("done") : t("todo")}:</span>
                  {i.done ? (
                    t(`items.${i.key}`)
                  ) : (
                    <Link href={LINK_FOR[i.key] ?? "/dev/profile"} className="text-accent-primary underline">
                      {t(`items.${i.key}`)}
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          </GlassCard>

          <GlassCard>
            <h2 className="mb-3 text-lg font-semibold">{t("skills")}</h2>
            <p className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-text-muted">
              <span className="font-semibold">{t("legend")}</span>
              <span className="flex items-center gap-2"><Badge tone="verified">{t("legendVerified")}</Badge></span>
              <span className="flex items-center gap-2"><Badge tone="cv">{t("legendCv")}</Badge></span>
            </p>
            {ov.data.skills.length === 0 ? (
              <p className="text-text-muted">{t("noSkills")}</p>
            ) : (
              <div className="flex flex-col gap-4">
                {LEVELS.filter((l) => groups[l].length).map((l) => (
                  <section key={l} aria-labelledby={`lvl-${l}`}>
                    <h3 id={`lvl-${l}`} className="mb-2 text-sm font-semibold text-text-muted">{t(`level.${l}`)}</h3>
                    <ul className="flex flex-wrap gap-2">
                      {groups[l].map((s) => (
                        <li key={s.skill}><SkillChip skill={s.skill} level={s.level} years={s.years} /></li>
                      ))}
                    </ul>
                  </section>
                ))}
              </div>
            )}
          </GlassCard>

          <section aria-labelledby="quick">
            <h2 id="quick" className="mb-3 text-lg font-semibold">{t("quick")}</h2>
            <ul className="flex flex-wrap gap-3">
              {QUICK.map((k) => (
                <li key={k}>
                  <Link href={k === "profile" ? "/dev/profile" : `/dev/${k}`} className={buttonClass("secondary")}>{tn(k)}</Link>
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </div>
  );
}
