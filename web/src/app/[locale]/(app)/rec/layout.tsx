/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { RecNav } from "@/components/rec/RecNav";

export default function RecLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <RecNav />
      {children}
    </>
  );
}
