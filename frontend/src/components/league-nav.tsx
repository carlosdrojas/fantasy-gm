"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useTransition } from "react";
import { syncLeagueAction } from "@/app/actions";

export function LeagueTabs({ leagueId, myTeamId }: { leagueId: number; myTeamId: number | null }) {
  const pathname = usePathname();
  const base = `/leagues/${leagueId}`;
  const tabs = [
    { href: base, label: "Dashboard" },
    ...(myTeamId ? [{ href: `${base}/teams/${myTeamId}`, label: "My team" }] : []),
    { href: `${base}/league`, label: "League" },
    { href: `${base}/waivers`, label: "Waivers" },
    { href: `${base}/trades`, label: "Trades" },
    { href: `${base}/assistant`, label: "Assistant" },
    { href: `${base}/activity`, label: "Activity" },
  ];
  return (
    <nav className="-mb-px flex gap-5 overflow-x-auto text-sm">
      {tabs.map((t) => {
        const active = t.href === base ? pathname === base : pathname.startsWith(t.href);
        return (
          <Link
            key={t.href}
            href={t.href}
            className={`whitespace-nowrap border-b-2 pb-2 ${
              active ? "border-accent font-medium text-ink" : "border-transparent text-ink-2 hover:text-ink"
            }`}
          >
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function SyncButton({ leagueId }: { leagueId: number }) {
  const [pending, start] = useTransition();
  const [error, setError] = useState<string>();
  return (
    <div className="flex flex-col items-end gap-1">
      <button
        onClick={() =>
          start(async () => {
            const res = await syncLeagueAction(leagueId);
            setError(res.error);
          })
        }
        disabled={pending}
        className="rounded-md border border-line px-3 py-1.5 text-sm text-ink hover:bg-surface-2 disabled:opacity-60"
      >
        {pending ? "Syncing…" : "Sync now"}
      </button>
      {error && <p className="max-w-xs text-right text-xs text-critical">{error}</p>}
    </div>
  );
}
