/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
import type { ButtonHTMLAttributes } from "react";

const base =
  "inline-flex items-center justify-center gap-2 rounded-lg px-5 py-2.5 text-sm font-semibold transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-primary disabled:cursor-not-allowed disabled:opacity-50";
const variants = {
  primary: "bg-accent-primary text-bg-base hover:bg-accent-primary/85",
  secondary: "border border-accent-primary/50 text-accent-primary hover:bg-accent-primary/10",
  ghost: "text-text-primary hover:bg-text-primary/10",
} as const;

export type ButtonVariant = keyof typeof variants;

/** Class string so links (next-intl Link) can look like buttons without nesting <a> in <button>. */
export const buttonClass = (variant: ButtonVariant = "primary", extra = "") =>
  `${base} ${variants[variant]} ${extra}`;

export function Button({
  variant = "primary",
  className = "",
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return <button type={type} className={buttonClass(variant, className)} {...props} />;
}
