"use client";

import { useEffect, useState, useTransition } from "react";
import { analyzeTradeAction, teamRosterAction } from "@/app/actions";
import { AcceptanceMeter, Gain } from "@/components/trade-card";
import { InjuryBadge } from "@/components/ui";
import type { PlayerRow, TradeAnalysis } from "@/lib/api";

function PlayerPicker({
  title,
  players,
  selected,
  onToggle,
}: {
  title: string;
  players: PlayerRow[];
  selected: Set<number>;
  onToggle: (id: number) => void;
}) {
  return (
    <fieldset>
      <legend className="mb-1.5 text-xs text-muted">{title}</legend>
      <div className="max-h-72 space-y-0.5 overflow-y-auto pr-1">
        {players.map((p) => (
          <label
            key={p.id}
            className={`flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-sm hover:bg-surface-2 ${
              selected.has(p.id) ? "bg-surface-2" : ""
            }`}
          >
            <input type="checkbox" checked={selected.has(p.id)} onChange={() => onToggle(p.id)} className="accent-[var(--accent)]" />
            <span className="flex-1 truncate">
              <span className="text-ink">{p.name}</span>
              <span className="ml-1.5 text-xs text-muted">{p.position}</span>
              <InjuryBadge status={p.injury_status} />
            </span>
            <span className="num text-xs text-ink-2">{p.value.per_game.toFixed(1)}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function OddsDelta({ label, before, after }: { label: string; before: number; after: number }) {
  const d = after - before;
  return (
    <div className="flex justify-between gap-3 text-xs">
      <span className="text-ink-2">{label}</span>
      <span className="num">
        <span className="text-muted">{before.toFixed(0)}% →</span> <span className="text-ink">{after.toFixed(0)}%</span>{" "}
        <span className={Math.abs(d) < 0.5 ? "text-muted" : d > 0 ? "text-good" : "text-critical"}>
          ({d > 0 ? "+" : ""}
          {d.toFixed(1)})
        </span>
      </span>
    </div>
  );
}

export function TradeAnalyzer({
  leagueId,
  myTeamId,
  myRoster,
  teams,
  initialPartnerId,
}: {
  leagueId: number;
  myTeamId: number;
  myRoster: PlayerRow[];
  teams: { id: number; name: string }[];
  initialPartnerId?: number;
}) {
  const [partnerId, setPartnerId] = useState<number>(initialPartnerId ?? teams[0]?.id);
  const [partnerRoster, setPartnerRoster] = useState<PlayerRow[]>([]);
  const [give, setGive] = useState<Set<number>>(new Set());
  const [get, setGet] = useState<Set<number>>(new Set());
  const [result, setResult] = useState<TradeAnalysis>();
  const [error, setError] = useState<string>();
  const [pending, start] = useTransition();
  const [loadingRoster, startRoster] = useTransition();

  useEffect(() => {
    if (!partnerId) return;
    startRoster(async () => {
      setPartnerRoster(await teamRosterAction(leagueId, partnerId));
      setGet(new Set());
      setResult(undefined);
    });
  }, [leagueId, partnerId]);

  const toggle = (set: Set<number>, update: (s: Set<number>) => void) => (id: number) => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    update(next);
    setResult(undefined);
  };

  const sortByValue = (rows: PlayerRow[]) => [...rows].sort((a, b) => b.value.per_game - a.value.per_game);
  const partnerName = teams.find((t) => t.id === partnerId)?.name ?? "";
  const canAnalyze = give.size > 0 && get.size > 0 && !pending;

  return (
    <div className="space-y-4">
      <label className="flex items-center gap-2 text-sm text-ink-2">
        Trade with
        <select
          value={partnerId}
          onChange={(e) => setPartnerId(Number(e.target.value))}
          className="rounded-md border border-line bg-page px-2 py-1 text-sm text-ink"
        >
          {teams.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      </label>

      <div className="grid gap-4 md:grid-cols-2">
        <PlayerPicker title="You send" players={sortByValue(myRoster)} selected={give} onToggle={toggle(give, setGive)} />
        {loadingRoster ? (
          <p className="text-sm text-muted">Loading roster…</p>
        ) : (
          <PlayerPicker
            title={`You get from ${partnerName}`}
            players={sortByValue(partnerRoster)}
            selected={get}
            onToggle={toggle(get, setGet)}
          />
        )}
      </div>

      <div className="flex items-center gap-3">
        <button
          disabled={!canAnalyze}
          onClick={() =>
            start(async () => {
              const res = await analyzeTradeAction(leagueId, {
                partner_team_id: partnerId,
                give: [...give],
                get: [...get],
              });
              setResult(res.result);
              setError(res.error);
            })
          }
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-accent-ink disabled:opacity-50"
        >
          {pending ? "Analyzing…" : "Analyze trade"}
        </button>
        {!canAnalyze && !pending && <span className="text-xs text-muted">Pick at least one player on each side.</span>}
        {error && <span className="text-sm text-critical">{error}</span>}
      </div>

      {result && (
        <div className="grid gap-4 rounded-lg border border-line p-4 md:grid-cols-3">
          <div className="space-y-1.5 text-sm">
            <div className="text-xs text-muted">Lineup impact</div>
            <div>
              You <Gain value={result.my_gain} />
            </div>
            <div>
              {partnerName} <Gain value={result.their_gain} />
            </div>
            <AcceptanceMeter value={result.acceptance} />
            {result.my_drops.length > 0 && (
              <div className="text-xs text-muted">You&apos;d have to drop {result.my_drops.map((p) => p.name).join(", ")}</div>
            )}
          </div>
          {[myTeamId, partnerId].map((tid) => {
            const o = result.odds[String(tid)];
            if (!o) return null;
            return (
              <div key={tid} className="space-y-1">
                <div className="text-xs text-muted">{tid === myTeamId ? "Your" : `${partnerName}'s`} odds</div>
                <OddsDelta label="Playoffs" before={o.before.playoff_pct} after={o.after.playoff_pct} />
                <OddsDelta label="Title" before={o.before.champion_pct} after={o.after.champion_pct} />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
