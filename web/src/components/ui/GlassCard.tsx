/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import type { HTMLAttributes } from "react";

export function GlassCard({ className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={`glass p-6 ${className}`} {...props} />;
}
