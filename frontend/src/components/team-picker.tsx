"use client";

import { useState, useTransition } from "react";
import { pickTeamAction } from "@/app/actions";

/** Asks which team is yours: needed when we couldn't match your ESPN account to one. */
export function TeamPicker({ leagueId, teams }: { leagueId: number; teams: { id: number; name: string }[] }) {
  const [teamId, setTeamId] = useState<number>();
  const [pending, start] = useTransition();
  const [error, setError] = useState<string>();
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-surface-2 px-4 py-3 text-sm">
      <span className="text-ink">Which team is yours?</span>
      <select
        value={teamId ?? ""}
        onChange={(e) => setTeamId(Number(e.target.value))}
        className="rounded-md border border-line bg-page px-2 py-1 text-sm text-ink"
      >
        <option value="" disabled>
          Pick a team
        </option>
        {teams.map((t) => (
          <option key={t.id} value={t.id}>
            {t.name}
          </option>
        ))}
      </select>
      <button
        disabled={!teamId || pending}
        onClick={() =>
          start(async () => {
            const res = await pickTeamAction(leagueId, teamId ?? null);
            setError(res.error);
          })
        }
        className="rounded-md bg-accent px-3 py-1 text-sm font-semibold text-accent-ink disabled:opacity-60"
      >
        {pending ? "Saving…" : "Save"}
      </button>
      <span className="text-xs text-muted">
        Lineup fixes, waivers, trades and the assistant work from your team. Adding your ESPN cookies in Settings picks
        it automatically.
      </span>
      {error && <p className="basis-full text-xs text-critical">{error}</p>}
    </div>
  );
}
