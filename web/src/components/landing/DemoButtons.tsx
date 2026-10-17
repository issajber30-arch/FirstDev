/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import { useTranslations } from "next-intl";
import { useCallback, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Turnstile } from "@/components/ui/Turnstile";
import { useRouter } from "@/i18n/navigation";
import { ApiError, api } from "@/lib/api";

const SITE_KEY = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY;

export function DemoButtons() {
  const t = useTranslations("landing");
  const router = useRouter();
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const onToken = useCallback((v: string) => setToken(v), []);

  async function start(role: "developer" | "recruiter") {
    setBusy(true);
    setError("");
    try {
      await api("POST", "/demo/sandbox", { role, turnstile_token: token });
      router.push(role === "developer" ? "/dev" : "/rec");
    } catch (e) {
      setError(e instanceof ApiError && e.status === 429 ? t("demoLimit") : t("demoError"));
      setBusy(false);
    }
  }

  const blocked = busy || (!!SITE_KEY && !token);
  return (
    <div className="flex flex-col items-center gap-4">
      <div className="flex flex-wrap justify-center gap-3">
        <Button disabled={blocked} onClick={() => start("developer")}>
          {t("tryDeveloper")}
        </Button>
        <Button variant="secondary" disabled={blocked} onClick={() => start("recruiter")}>
          {t("tryRecruiter")}
        </Button>
      </div>
      {SITE_KEY && <Turnstile siteKey={SITE_KEY} onToken={onToken} />}
      <p className="max-w-md text-center text-sm text-text-muted">{busy ? t("demoCreating") : t("demoNote")}</p>
      {error && (
        <p role="alert" className="text-sm text-warning">
          {error}
        </p>
      )}
    </div>
  );
}
