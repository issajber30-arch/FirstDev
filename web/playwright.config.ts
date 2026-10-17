/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import { defineConfig, devices } from "@playwright/test";

// No webServer: scripts/dev.sh starts the API, worker and Next.js first.
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: { baseURL: "http://localhost:3000", ...devices["Desktop Chrome"] },
});
