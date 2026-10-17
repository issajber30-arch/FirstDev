/* Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform. */
"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { crossed, deadlineFrom, formatClock, isUrgent, pulseClass, secondsLeft } from "@/lib/countdown";

const MQ = "(prefers-reduced-motion: reduce)";
function useReducedMotion() {
  return useSyncExternalStore(
    (cb) => {
      const m = window.matchMedia(MQ);
      m.addEventListener("change", cb);
      return () => m.removeEventListener("change", cb);
    },
    () => window.matchMedia(MQ).matches,
    () => false,
  );
}

/** Timer driven by the server's `seconds_left`. Mount it with a new `key` on every API response
 *  to re-sync; between responses it only reads the clock once per second. */
export function Countdown({ seconds, onExpire }: { seconds: number; onExpire: () => void }) {
  const t = useTranslations("dev.assess.timer");
  const reduced = useReducedMotion();
  const [left, setLeft] = useState(seconds);
  const [announcement, setAnnouncement] = useState("");
  const expire = useRef(onExpire);
  useEffect(() => {
    expire.current = onExpire;
  });
  useEffect(() => {
    const deadline = deadlineFrom(seconds, Date.now());
    let prev = seconds;
    const id = setInterval(() => {
      const next = secondsLeft(deadline, Date.now());
      const at = crossed(prev, next);
      if (at) setAnnouncement(t(`announce.${at}` as "announce.30"));
      prev = next;
      setLeft(next);
      if (next === 0) {
        clearInterval(id);
        expire.current(); // the refetch of /current finalizes the assessment server-side
      }
    }, 1000);
    return () => clearInterval(id);
  }, [seconds, t]);
  const urgent = isUrgent(left);
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div
        role="timer"
        aria-label={t("label")}
        className={`rounded-lg border px-3 py-1.5 font-mono text-lg ${urgent ? "border-warning bg-warning/15 text-warning" : "border-accent-primary/40 text-accent-primary"} ${pulseClass(left, reduced)}`}
      >
        <span dir="ltr">{formatClock(left)}</span>
      </div>
      {urgent && <span className="text-sm text-warning">{t("urgent")}</span>}
      <p className="sr-only" aria-live="polite">
        {announcement}
      </p>
    </div>
  );
}
