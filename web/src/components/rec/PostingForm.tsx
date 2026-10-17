/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";
import useSWR from "swr";
import { Button } from "@/components/ui/Button";
import { ChipInput } from "@/components/ui/ChipInput";
import { GlassCard } from "@/components/ui/GlassCard";
import { Input } from "@/components/ui/Input";
import { Notice } from "@/components/ui/Notice";
import { QueryState } from "@/components/ui/QueryState";
import { Textarea } from "@/components/ui/Textarea";
import { useRouter } from "@/i18n/navigation";
import { ApiError, api, fetcher } from "@/lib/api";
import { fieldErrors } from "@/lib/dev";
import { useMe } from "@/lib/useMe";
import { PageHeading, useApiErrorText, useFocusWhen } from "@/components/dev/shared";
import type { Posting } from "./PostingsScreen";

const num = (v: FormDataEntryValue | null) => (v === null || String(v).trim() === "" ? null : Number(v));
const str = (v: FormDataEntryValue | null) => String(v ?? "").trim() || null;

export function PostingForm({ postingId }: { postingId?: string }) {
  const existing = useSWR<Posting>(postingId ? `/postings/${postingId}` : null, fetcher<Posting>);
  const p = existing.data;
  return (
    <div>
      <PostingFormHeading edit={!!postingId} />
      {postingId && <QueryState loading={existing.isLoading} error={existing.error} onRetry={() => void existing.mutate()} />}
      {(!postingId || p) && <Form key={p?.id ?? "new"} posting={p} />}
    </div>
  );
}

function PostingFormHeading({ edit }: { edit: boolean }) {
  const t = useTranslations("rec.form");
  return <PageHeading>{edit ? t("editTitle") : t("newTitle")}</PageHeading>;
}

function Form({ posting }: { posting?: Posting }) {
  const t = useTranslations("rec.form");
  const errText = useApiErrorText();
  const router = useRouter();
  const { data: me } = useMe();
  const [required, setRequired] = useState(posting?.required_skills ?? []);
  const [optional, setOptional] = useState(posting?.optional_skills ?? []);
  const [busy, setBusy] = useState(false);
  const [fail, setFail] = useState<{ general: string; fields: Record<string, string>; n: number } | null>(null);
  const outcome = useFocusWhen<HTMLDivElement>(fail?.n);
  const closed = posting?.status === "closed";
  const isOpen = posting?.status === "open";

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const intent = (e.nativeEvent as SubmitEvent).submitter?.getAttribute("value") ?? "draft";
    const d = new FormData(e.currentTarget);
    const n = (fail?.n ?? 0) + 1;
    const fields: Record<string, string> = {};
    if (!str(d.get("title"))) fields.title = t("errTitle");
    if (!str(d.get("description"))) fields.description = t("errDescription");
    if (required.length === 0) fields.required_skills = t("errRequired");
    if (Object.keys(fields).length) {
      setFail({ general: t("fixFields"), fields, n });
      return;
    }
    const body = {
      title: str(d.get("title")),
      description: str(d.get("description")),
      required_skills: required,
      optional_skills: optional,
      tier: str(d.get("tier")),
      salary_min: num(d.get("salary_min")),
      salary_max: num(d.get("salary_max")),
      currency: str(d.get("currency"))?.toUpperCase() ?? null,
      location: str(d.get("location")),
      remote: d.get("remote") === "on",
      auto_assessment: me?.sandbox ? false : d.get("auto_assessment") === "on",
      // An open posting keeps its status (it cannot go back to draft); a draft goes where the button says.
      ...(isOpen ? {} : { status: intent === "open" ? "open" : "draft" }),
    };
    setBusy(true);
    setFail(null);
    try {
      const saved = posting
        ? await api<Posting>("PUT", `/postings/${posting.id}`, body)
        : await api<Posting>("POST", "/postings", body);
      router.push(`/rec/postings/${saved.id}`);
    } catch (err) {
      const f = err instanceof ApiError && err.status === 422 ? fieldErrors(err.detail) : {};
      setFail({ general: Object.keys(f).length ? t("fixFields") : errText(err), fields: f, n });
      setBusy(false);
    }
  }

  if (closed) return <Notice tone="info">{t("closedNotice")}</Notice>;
  const f = fail?.fields ?? {};
  return (
    <GlassCard>
      <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
        <Input name="title" label={t("title")} defaultValue={posting?.title ?? ""} maxLength={200} error={f.title} />
        <Textarea name="description" label={t("description")} defaultValue={posting?.description ?? ""} rows={8} error={f.description} />
        <ChipInput label={t("required")} hint={t("chipHint")} value={required} onChange={setRequired} max={20} tone="verified" error={f.required_skills} removeLabel={(s) => t("removeSkill", { skill: s })} />
        <ChipInput label={t("optional")} hint={t("chipHint")} value={optional} onChange={setOptional} max={20} removeLabel={(s) => t("removeSkill", { skill: s })} />
        <div className="flex flex-col gap-1.5">
          <label htmlFor="tier" className="text-sm text-text-muted">{t("tier")}</label>
          <select id="tier" name="tier" defaultValue={posting?.tier ?? ""} className="rounded-lg border border-text-primary/15 bg-bg-base px-3 py-2 text-text-primary">
            <option value="">{t("tierAny")}</option>
            <option value="junior">{t("tierJunior")}</option>
            <option value="mid">{t("tierMid")}</option>
          </select>
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          <Input name="salary_min" type="number" min={0} inputMode="numeric" label={t("salaryMin")} defaultValue={posting?.salary_min ?? ""} error={f.salary_min} />
          <Input name="salary_max" type="number" min={0} inputMode="numeric" label={t("salaryMax")} defaultValue={posting?.salary_max ?? ""} error={f.salary_max} />
          <Input name="currency" label={t("currency")} defaultValue={posting?.currency ?? ""} maxLength={3} placeholder="ILS" autoCapitalize="characters" className="font-mono uppercase" error={f.currency} />
        </div>
        <Input name="location" label={t("location")} defaultValue={posting?.location ?? ""} maxLength={100} error={f.location} />
        <label className="flex items-center gap-2">
          <input type="checkbox" name="remote" defaultChecked={posting?.remote} className="size-4 accent-accent-primary" />
          {t("remote")}
        </label>
        {me && !me.sandbox && (
          <label className="flex items-center gap-2">
            <input type="checkbox" name="auto_assessment" defaultChecked={!!posting?.auto_assessment} className="size-4 accent-accent-primary" />
            {t("autoAssessment")}
          </label>
        )}
        {fail && <Notice ref={outcome} tone="error">{fail.general}</Notice>}
        <div className="flex flex-wrap gap-3">
          {isOpen ? (
            <Button type="submit" value="save" disabled={busy}>{busy ? t("saving") : t("save")}</Button>
          ) : (
            <>
              {/* Draft first: Enter in a text field submits via the first button, and must not publish. */}
              <Button type="submit" value="draft" variant="secondary" disabled={busy}>{busy ? t("saving") : t("saveDraft")}</Button>
              <Button type="submit" value="open" disabled={busy}>{t("publish")}</Button>
            </>
          )}
        </div>
      </form>
    </GlassCard>
  );
}
