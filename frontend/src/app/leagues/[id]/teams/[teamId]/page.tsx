import Link from "next/link";
import { Card, fmt, GameStatus, PlayerName, record, teamLabeler, Trend, WeekPoints } from "@/components/ui";
import { api, POSITIONS, type PlayerRow } from "@/lib/api";

export default async function TeamPage({ params }: PageProps<"/leagues/[id]/teams/[teamId]">) {
  const { id: rawId, teamId: rawTeam } = await params;
  const id = Number(rawId);
  const teamId = Number(rawTeam);
  const [league, detail] = await Promise.all([api.league(id), api.team(id, teamId)]);
  const { team, roster, lineup_changes: changes, positions } = detail;
  const isMine = league.my_team_id === teamId;
  const byId = new Map(roster.map((p) => [p.id, p]));
  const starters = roster.filter((p) => p.slot !== "BE" && p.slot !== "IR");
  const bench = roster.filter((p) => p.slot === "BE" || p.slot === "IR");
  const startIds = new Set(changes.start);
  const sitIds = new Set(changes.sit);
  const weekTotal = starters.reduce((sum, p) => sum + (p.value.this_week_actual ?? 0), 0);
  const count = (state: string) => starters.filter((p) => p.game?.state === state).length;
  const [playing, yetToPlay] = [count("in"), count("pre")];
  const label = teamLabeler(league.teams);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-1.5">
        {league.teams.map((t) => (
          <Link
            key={t.id}
            href={`/leagues/${id}/teams/${t.id}`}
            className={`rounded-full border px-2.5 py-1 text-xs ${
              t.id === teamId
                ? "border-accent bg-accent text-accent-ink"
                : "border-line text-ink-2 hover:bg-surface-2"
            }`}
          >
            {label(t)}
            {t.id === league.my_team_id && " (you)"}
          </Link>
        ))}
      </div>

      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="font-display text-3xl font-extrabold tracking-wide">{team.name}</h2>
          <p className="text-xs text-muted">
            {team.owner_name} · {record(team)} · {team.points_for.toFixed(1)} PF
            {team.waiver_rank ? ` · waiver #${team.waiver_rank}` : ""}
            {league.settings.uses_faab && team.faab_spent != null
              ? ` · $${(league.settings.faab_budget ?? 100) - team.faab_spent} FAAB left`
              : ""}
          </p>
        </div>
      </div>

      {(changes.start.length > 0 || changes.sit.length > 0) && (
        <Card
          title={isMine ? "Lineup suggestion for this week" : "This team's lineup isn't optimal"}
          subtitle="Based on this week's projections; players ruled out are never started."
        >
          <div className="grid gap-3 text-sm sm:grid-cols-2">
            <div>
              <div className="mb-1 text-xs font-semibold text-good">▲ Start</div>
              {changes.start.map((pid) => (
                <div key={pid}>
                  <PlayerName p={byId.get(pid)!} />{" "}
                  <span className="num text-xs text-ink-2">
                    {fmt(byId.get(pid)!.value.this_week_projection)} proj
                  </span>
                </div>
              ))}
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold text-critical">▼ Sit</div>
              {changes.sit.map((pid) => (
                <div key={pid}>
                  <PlayerName p={byId.get(pid)!} />{" "}
                  <span className="num text-xs text-ink-2">
                    {fmt(byId.get(pid)!.value.this_week_projection)} proj
                  </span>
                </div>
              ))}
            </div>
          </div>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card
          title="Roster"
          subtitle={
            <>
              Week {league.current_week}: <span className="num font-medium text-ink">{weekTotal.toFixed(1)}</span>{" "}
              pts from starters
              {playing > 0 && ` · ${playing} playing now`}
              {yetToPlay > 0 && ` · ${yetToPlay} yet to play`}
            </>
          }
          className="min-w-0 lg:col-span-2"
        >
          <RosterTable title="Starters" players={starters} startIds={startIds} sitIds={sitIds} />
          <div className="h-4" />
          <RosterTable title="Bench" players={bench} startIds={startIds} sitIds={sitIds} />
        </Card>

        <Card
          title="Positional strength"
          subtitle="Rank among league starters (+ best backup)"
          className="min-w-0"
        >
          <ul className="space-y-2 text-sm">
            {POSITIONS.map((pos) => {
              const c = positions[pos];
              if (!c) return null;
              return (
                <li key={pos} className="flex items-center justify-between">
                  <span className="w-12 font-medium">{pos}</span>
                  <span className="num flex-1 text-xs text-ink-2">
                    {c.starters.toFixed(1)} pts/g
                    {c.depth > 0 && <span className="text-muted"> · backup {c.depth.toFixed(1)}</span>}
                  </span>
                  <span className="num w-10 text-right">#{c.rank}</span>
                  <span
                    className={`ml-2 w-16 text-right text-xs font-semibold ${
                      c.label === "need" ? "text-critical" : c.label === "surplus" ? "text-good" : "text-muted"
                    }`}
                  >
                    {c.label === "need" ? "● Need" : c.label === "surplus" ? "● Deep" : "OK"}
                  </span>
                </li>
              );
            })}
          </ul>
        </Card>
      </div>
    </div>
  );
}

function RosterTable({
  title,
  players,
  startIds,
  sitIds,
}: {
  title: string;
  players: PlayerRow[];
  startIds: Set<number>;
  sitIds: Set<number>;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-xs text-muted">
          <tr className="border-b border-line">
            <th className="w-14 py-1.5 pr-2 text-left font-normal">{title}</th>
            <th className="py-1.5 pr-2 text-left font-normal" />
            <th className="px-2 py-1.5 text-right font-normal" title="This week's fantasy points (live)">Pts</th>
            <th className="px-2 py-1.5 text-left font-normal">Game</th>
            <th className="px-2 py-1.5 text-right font-normal" title="This week's projection">Proj</th>
            <th className="px-2 py-1.5 text-right font-normal" title="Blended expected points per game">Value</th>
            <th className="px-2 py-1.5 text-right font-normal" title="Average of last 4 games played">L4</th>
            <th className="py-1.5 pl-2 text-right font-normal" title="Recent vs. earlier average">Trend</th>
          </tr>
        </thead>
        <tbody className="num">
          {players.map((p) => (
            <tr key={p.id} className="border-b border-line last:border-0">
              <td className="py-1.5 pr-2 text-xs text-muted">
                {p.slot}
                {startIds.has(p.id) && <span className="ml-1 text-good" title="Should start">▲</span>}
                {sitIds.has(p.id) && <span className="ml-1 text-critical" title="Should sit">▼</span>}
              </td>
              <td className="py-1.5 pr-2">
                <PlayerName p={p} />
              </td>
              <td className="px-2 py-1.5 text-right">
                <WeekPoints p={p} />
              </td>
              <td className="whitespace-nowrap px-2 py-1.5 text-xs">
                <GameStatus game={p.game} />
              </td>
              <td className="px-2 py-1.5 text-right text-ink-2">{fmt(p.value.this_week_projection)}</td>
              <td className="px-2 py-1.5 text-right font-medium">{fmt(p.value.per_game)}</td>
              <td className="px-2 py-1.5 text-right text-ink-2">{fmt(p.value.recent_avg)}</td>
              <td className="py-1.5 pl-2 text-right text-xs">
                <Trend value={p.value.trend} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
