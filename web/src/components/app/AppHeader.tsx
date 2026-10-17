/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import { useTranslations } from "next-intl";
import { Logo } from "@/components/brand/Logo";
import { Button } from "@/components/ui/Button";
import { Link, useRouter } from "@/i18n/navigation";
import { api } from "@/lib/api";
import { LocaleSwitcher } from "./LocaleSwitcher";

export function AppHeader() {
  const t = useTranslations("common");
  const router = useRouter();
  async function signOut() {
    try {
      await api("POST", "/auth/logout");
    } finally {
      router.push("/");
    }
  }
  return (
    <header className="flex items-center justify-between gap-4 px-4 py-3 sm:px-8">
      <Link href="/" aria-label="FirstDev">
        <Logo className="h-9 w-auto" />
      </Link>
      <div className="flex items-center gap-3">
        <LocaleSwitcher />
        <Button variant="ghost" onClick={signOut}>
          {t("signOut")}
        </Button>
      </div>
    </header>
  );
}
