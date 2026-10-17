/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  test: { environment: "jsdom", setupFiles: ["./vitest.setup.ts"], globals: false },
});
