/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import useSWR from "swr";
import { fetcher, type Me } from "./api";

/** The signed-in user (401 -> api() redirects to sign-in). Never retries on error. */
export const useMe = () => useSWR<Me>("/me", fetcher<Me>, { shouldRetryOnError: false });
