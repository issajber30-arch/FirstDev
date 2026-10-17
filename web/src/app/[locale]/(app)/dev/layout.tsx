/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { DevNav } from "@/components/dev/DevNav";

export default function DevLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <DevNav />
      {children}
    </>
  );
}
