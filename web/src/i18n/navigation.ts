/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { createNavigation } from "next-intl/navigation";
import { routing } from "./routing";

export const { Link, redirect, usePathname, useRouter } = createNavigation(routing);
