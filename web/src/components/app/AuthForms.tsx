/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/Button";
import { GlassCard } from "@/components/ui/GlassCard";
import { Input } from "@/components/ui/Input";
import { Link, useRouter } from "@/i18n/navigation";
import { ApiError, api, type Me } from "@/lib/api";

function useAuthSubmit(run: (data: FormData) => Promise<void>) {
  const t = useTranslations("auth");
  const router = useRouter();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await run(new FormData(e.currentTarget));
      const me = await api<Me>("GET", "/me");
      router.push(me.role === "recruiter" ? "/rec" : "/dev");
    } catch (err) {
      const s = err instanceof ApiError ? err.status : 0;
      setError(
        s === 429 ? t("tooMany") : s === 401 ? t("invalidCredentials") : s === 403 ? t("invalidInvite") : s === 409 ? t("registrationFailed") : s === 422 ? t("invalidInput") : t("registrationFailed"),
      );
      setBusy(false);
    }
  }
  return { onSubmit, error, busy };
}

const field = (d: FormData, k: string) => String(d.get(k) ?? "");

async function login(d: FormData) {
  await api("POST", "/auth/login", { email: field(d, "email").trim(), password: field(d, "password") });
}

export function SignInForm() {
  const t = useTranslations("auth");
  const { onSubmit, error, busy } = useAuthSubmit(login);
  return (
    <GlassCard className="w-full max-w-md">
      <h1 className="mb-6 text-2xl font-semibold">{t("signInTitle")}</h1>
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <Input name="email" type="email" autoComplete="email" required maxLength={254} label={t("email")} />
        <Input name="password" type="password" autoComplete="current-password" required maxLength={128} label={t("password")} />
        {error && <p role="alert" className="text-sm text-warning">{error}</p>}
        <Button type="submit" disabled={busy}>{busy ? t("submitting") : t("submitSignIn")}</Button>
      </form>
      <p className="mt-4 text-sm text-text-muted">
        <Link href="/join" className="text-accent-primary underline">{t("noAccount")}</Link>
      </p>
    </GlassCard>
  );
}

export function JoinForm() {
  const t = useTranslations("auth");
  const { onSubmit, error, busy } = useAuthSubmit(async (d) => {
    const email = field(d, "email").trim();
    const password = field(d, "password");
    await api("POST", "/auth/register", {
      email,
      password,
      role: field(d, "role"),
      display_name: field(d, "display_name").trim(),
      invite_code: field(d, "invite_code").trim(),
    });
    await api("POST", "/auth/login", { email, password });
  });
  return (
    <GlassCard className="w-full max-w-md">
      <h1 className="mb-6 text-2xl font-semibold">{t("joinTitle")}</h1>
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <Input name="invite_code" required maxLength={64} autoComplete="off" label={t("inviteCode")} className="font-mono" />
        <Input name="display_name" required maxLength={60} autoComplete="name" label={t("displayName")} />
        <Input name="email" type="email" autoComplete="email" required maxLength={254} label={t("email")} />
        <Input name="password" type="password" autoComplete="new-password" required minLength={12} maxLength={128} label={t("password")} placeholder={t("passwordHint")} />
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1 text-sm text-text-muted">{t("role")}</legend>
          {(["developer", "recruiter"] as const).map((r, i) => (
            <label key={r} className="flex items-center gap-2">
              <input type="radio" name="role" value={r} defaultChecked={i === 0} className="accent-accent-primary" />
              {t(r === "developer" ? "roleDeveloper" : "roleRecruiter")}
            </label>
          ))}
        </fieldset>
        {error && <p role="alert" className="text-sm text-warning">{error}</p>}
        <Button type="submit" disabled={busy}>{busy ? t("submitting") : t("submitJoin")}</Button>
      </form>
      <p className="mt-4 text-sm text-text-muted">
        <Link href="/sign-in" className="text-accent-primary underline">{t("haveAccount")}</Link>
      </p>
    </GlassCard>
  );
}
