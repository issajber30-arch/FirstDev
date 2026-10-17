/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { defineRouting } from "next-intl/routing";

export const routing = defineRouting({
  locales: ["en", "he"],
  defaultLocale: "en",
});

export type Locale = (typeof routing.locales)[number];
