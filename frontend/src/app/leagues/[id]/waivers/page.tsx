import Link from "next/link";
import { Card, EmptyState, ErrorPanel, fmt, PlayerName, Trend } from "@/components/ui";
import { ApiError, api, POSITIONS } from "@/lib/api";

export default async function WaiversPage({ params, searchParams }: PageProps<"/leagues/[id]/waivers">) {
  const id = Number((await params).id);
  const sp = await searchParams;
  const position = typeof sp.pos === "string" && (POSITIONS as readonly string[]).includes(sp.pos) ? sp.pos : undefined;

  const league = await api.league(id);
  let waivers;
  try {
    waivers = await api.waivers(id);
  } catch (e) {
    if (e instanceof ApiError && e.status === 400) {
      return <ErrorPanel message="Your team couldn't be detected. Set your ESPN cookies (FGM_ESPN_S2 / FGM_ESPN_SWID) in backend/.env, restart, and sync." />;
    }
    throw e;
  }
  const freeAgents = await api.freeAgents(id, position);
  // Usually every pickup drops the same bench player: say so once instead of per row.
  const dropIds = new Set(waivers.suggestions.map((s) => s.drop?.id ?? null));
  const commonDrop = dropIds.size === 1 ? waivers.suggestions[0]?.drop ?? null : null;

  return (
    <div className="space-y-6">
      <Card
        title="Recommended pickups"
        subtitle={
          <>
            Ranked by how much each player improves your best lineup. Weekly gain is points per week
            over the rest of the season; This wk is the gain for this week&apos;s lineup.
            {commonDrop && (
              <>
                {" "}
                Each pickup would replace <span className="text-ink">{commonDrop.name}</span>, your
                lowest-value bench player.
              </>
            )}
          </>
        }
      >
        {waivers.suggestions.length === 0 ? (
          <EmptyState>No available player improves your lineup right now.</EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-muted">
                <tr className="border-b border-line">
                  <th className="py-2 pr-2 text-left font-normal">Add</th>
                  <th className="px-2 py-2 text-right font-normal">Weekly gain</th>
                  <th className="px-2 py-2 text-right font-normal">This wk</th>
                  <th className="px-2 py-2 text-right font-normal">Trend</th>
                  <th className="px-2 py-2 text-right font-normal">Rostered</th>
                  {!commonDrop && <th className="py-2 pl-4 text-left font-normal">Drop</th>}
                </tr>
              </thead>
              <tbody className="num">
                {waivers.suggestions.map((s) => (
                  <tr key={s.player.id} className="border-b border-line last:border-0">
                    <td className="py-2 pr-2">
                      <PlayerName p={s.player} />
                    </td>
                    <td className="px-2 py-2 text-right font-medium text-good">+{s.ros_gain.toFixed(1)}</td>
                    <td className="px-2 py-2 text-right text-ink-2">
                      {s.week_gain > 0 ? `+${s.week_gain.toFixed(1)}` : "–"}
                    </td>
                    <td className="px-2 py-2 text-right text-xs">
                      <Trend value={s.player.value.trend} />
                    </td>
                    <td className="px-2 py-2 text-right text-ink-2">
                      {fmt(s.player.percent_owned, 0)}%
                      {s.player.percent_owned_change != null && Math.abs(s.player.percent_owned_change) >= 1 && (
                        <span className={`ml-1 text-xs ${s.player.percent_owned_change > 0 ? "text-good" : "text-critical"}`}>
                          {s.player.percent_owned_change > 0 ? "+" : ""}
                          {s.player.percent_owned_change.toFixed(0)}
                        </span>
                      )}
                    </td>
                    {!commonDrop && (
                      <td className="py-2 pl-4 text-ink-2">{s.drop ? <PlayerName p={s.drop} /> : "–"}</td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card
        title="Best available"
        subtitle="Available players sorted by expected points per game"
        action={
          <div className="flex flex-wrap gap-1 text-xs">
            {[undefined, ...POSITIONS].map((p) => (
              <Link
                key={p ?? "all"}
                href={`/leagues/${id}/waivers${p ? `?pos=${encodeURIComponent(p)}` : ""}`}
                className={`rounded-full border px-2 py-0.5 ${
                  p === position ? "border-accent bg-accent text-accent-ink" : "border-line text-ink-2 hover:bg-surface-2"
                }`}
              >
                {p ?? "All"}
              </Link>
            ))}
          </div>
        }
      >
        {freeAgents.length === 0 ? (
          <EmptyState>No available players found{position ? ` at ${position}` : ""}.</EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-muted">
                <tr className="border-b border-line">
                  <th className="py-2 pr-2 text-left font-normal">Player</th>
                  <th className="px-2 py-2 text-right font-normal">Value</th>
                  <th className="px-2 py-2 text-right font-normal">Proj (wk {league.current_week})</th>
                  <th className="px-2 py-2 text-right font-normal">L4</th>
                  <th className="px-2 py-2 text-right font-normal">Trend</th>
                  <th className="py-2 pl-2 text-right font-normal">Rostered</th>
                </tr>
              </thead>
              <tbody className="num">
                {freeAgents.map((p) => (
                  <tr key={p.id} className="border-b border-line last:border-0">
                    <td className="py-1.5 pr-2">
                      <PlayerName p={p} />
                    </td>
                    <td className="px-2 py-1.5 text-right font-medium">{fmt(p.value.per_game)}</td>
                    <td className="px-2 py-1.5 text-right">{fmt(p.value.this_week_projection)}</td>
                    <td className="px-2 py-1.5 text-right text-ink-2">{fmt(p.value.recent_avg)}</td>
                    <td className="px-2 py-1.5 text-right text-xs">
                      <Trend value={p.value.trend} />
                    </td>
                    <td className="py-1.5 pl-2 text-right text-ink-2">{fmt(p.percent_owned, 0)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
