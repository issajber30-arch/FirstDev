/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";
import useSWR from "swr";
import { Button } from "@/components/ui/Button";
import { GlassCard } from "@/components/ui/GlassCard";
import { Input } from "@/components/ui/Input";
import { Notice } from "@/components/ui/Notice";
import { QueryState } from "@/components/ui/QueryState";
import { Textarea } from "@/components/ui/Textarea";
import { ApiError, api, fetcher, type Schemas } from "@/lib/api";
import { fieldErrors } from "@/lib/dev";
import { useMe } from "@/lib/useMe";
import { PageHeading, useApiErrorText, useFocusWhen } from "./shared";

type Profile = Schemas["ProfileOut"];
const text = (d: FormData, k: string) => String(d.get(k) ?? "").trim() || null;

export function ProfileForm() {
  const t = useTranslations("dev.profile");
  const { data: me } = useMe();
  const { data: p, error, isLoading, mutate } = useSWR<Profile>("/profiles/me", fetcher<Profile>);
  const errText = useApiErrorText();
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0); // bumps on every outcome so focus moves to the message each time
  const [saved, setSaved] = useState(false);
  const [fail, setFail] = useState<{ general: string; fields: Record<string, string> } | null>(null);
  const outcome = useFocusWhen<HTMLDivElement>(tick);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    const body: Record<string, unknown> = {
      headline: text(d, "headline"),
      bio: text(d, "bio"),
      location: text(d, "location"),
      experience_tier: text(d, "experience_tier"),
      github_username: text(d, "github_username"),
      open_to_opportunities: d.get("open_to_opportunities") === "on",
    };
    // PUT replaces the profile; sandboxes must not send a handle or a public flag.
    if (!me?.sandbox) {
      body.handle = text(d, "handle");
      body.public_profile = d.get("public_profile") === "on";
    }
    setBusy(true);
    setFail(null);
    setSaved(false);
    try {
      await mutate(await api<Profile>("PUT", "/profiles/me", body), { revalidate: false });
      setSaved(true);
    } catch (err) {
      const fields = err instanceof ApiError ? fieldErrors(err.detail) : {};
      setFail({ general: Object.keys(fields).length ? t("fixFields") : errText(err), fields });
    } finally {
      setBusy(false);
      setTick((n) => n + 1);
    }
  }

  const f = fail?.fields ?? {};
  return (
    <div>
      <PageHeading>{t("title")}</PageHeading>
      <QueryState loading={isLoading} error={error} onRetry={() => void mutate()} />
      {p && (
        <GlassCard>
          {/* key remounts the uncontrolled form with the saved values */}
          <form key={JSON.stringify(p)} onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
            <Input name="headline" label={t("headline")} defaultValue={p.headline ?? ""} maxLength={120} error={f.headline} />
            <Textarea name="bio" label={t("bio")} defaultValue={p.bio ?? ""} maxLength={2000} rows={5} error={f.bio} />
            <Input name="location" label={t("location")} defaultValue={p.location ?? ""} maxLength={100} error={f.location} />
            <div className="flex flex-col gap-1.5">
              <label htmlFor="tier" className="text-sm text-text-muted">{t("tier")}</label>
              <select id="tier" name="experience_tier" defaultValue={p.experience_tier ?? ""} aria-invalid={f.experience_tier ? true : undefined} className="rounded-lg border border-text-primary/15 bg-bg-base px-3 py-2 text-text-primary">
                <option value="">{t("tierAuto")}</option>
                <option value="junior">{t("tierJunior")}</option>
                <option value="mid">{t("tierMid")}</option>
              </select>
              {f.experience_tier && <p role="alert" className="text-sm text-warning">{f.experience_tier}</p>}
            </div>
            <Input name="github_username" label={t("github")} defaultValue={p.github_username ?? ""} maxLength={39} autoCapitalize="none" spellCheck={false} className="font-mono" error={f.github_username} />
            <label className="flex items-center gap-2">
              <input type="checkbox" name="open_to_opportunities" defaultChecked={p.open_to_opportunities} className="size-4 accent-accent-primary" />
              {t("open")}
            </label>
            {me && !me.sandbox && (
              <fieldset className="flex flex-col gap-4 rounded-lg border border-text-primary/10 p-4">
                <legend className="px-2 text-sm text-text-muted">{t("publicSection")}</legend>
                <Input name="handle" label={t("handle")} defaultValue={p.handle ?? ""} maxLength={30} autoCapitalize="none" spellCheck={false} className="font-mono" error={f.handle} />
                <label className="flex items-center gap-2">
                  <input type="checkbox" name="public_profile" defaultChecked={p.public_profile} className="size-4 accent-accent-primary" />
                  {t("public")}
                </label>
              </fieldset>
            )}
            {fail && <Notice ref={outcome} tone="error">{fail.general}</Notice>}
            {!fail && saved && <Notice ref={outcome} tone="success">{t("saved")}</Notice>}
            <div>
              <Button type="submit" disabled={busy}>{busy ? t("saving") : t("save")}</Button>
            </div>
          </form>
        </GlassCard>
      )}
    </div>
  );
}
