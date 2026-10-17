/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { AppHeader } from "@/components/app/AppHeader";
import { MeSandboxBanner } from "@/components/app/SandboxBanner";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <MeSandboxBanner />
      <AppHeader />
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8 sm:px-8">{children}</main>
    </>
  );
}
