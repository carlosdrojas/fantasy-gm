"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

/** Re-renders the page's server data on an interval while games are on and the tab is visible. */
export function LiveRefresher({ active, intervalMs = 30_000 }: { active: boolean; intervalMs?: number }) {
  const router = useRouter();
  useEffect(() => {
    if (!active) return;
    const tick = () => {
      if (document.visibilityState === "visible") router.refresh();
    };
    const id = setInterval(tick, intervalMs);
    // Coming back to a stale tab: catch up immediately instead of waiting a full interval.
    document.addEventListener("visibilitychange", tick);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [active, intervalMs, router]);
  return null;
}

function secondsAgo(iso: string, now: number) {
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  return `${Math.round(s / 3600)}h ago`;
}

/** "● Live · updated 20s ago" pill, ticking every few seconds. */
export function LiveBadge({ active, updatedAt }: { active: boolean; updatedAt: string | null }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 5_000);
    return () => clearInterval(id);
  }, []);
  if (!active) return null;
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-2 py-0.5 text-xs text-ink-2">
      <span className="relative flex h-2 w-2" aria-hidden>
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-critical opacity-60" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-critical" />
      </span>
      <span className="font-medium text-ink">Live</span>
      {updatedAt && <span suppressHydrationWarning>· scores {secondsAgo(updatedAt, now)}</span>}
    </span>
  );
}
