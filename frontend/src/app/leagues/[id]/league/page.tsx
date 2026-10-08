import Link from "next/link";
import { WeeklyScores } from "@/components/charts";
import { PositionHeatmap } from "@/components/position-heatmap";
import { Card, record } from "@/components/ui";
import { api, type Team } from "@/lib/api";

export default async function LeaguePage({ params }: PageProps<"/leagues/[id]/league">) {
  const id = Number((await params).id);
  const [league, power, positions] = await Promise.all([api.league(id), api.power(id), api.positions(id)]);
  const teams = new Map<number, Team>(league.teams.map((t) => [t.id, t]));
  const mine = league.my_team_id;
  const teamHref = (tid: number) => `/leagues/${id}/teams/${tid}`;

  return (
    <div className="space-y-8">
      <Card title="Standings" subtitle="Expected wins = average all-play win rate × games played">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs text-muted">
              <tr className="border-b border-line">
                <th className="py-2 pr-2 text-left font-normal">Seed</th>
                <th className="py-2 pr-2 text-left font-normal">Team</th>
                <th className="px-2 py-2 text-right font-normal">Record</th>
                <th className="px-2 py-2 text-right font-normal">PF</th>
                <th className="px-2 py-2 text-right font-normal">PA</th>
                <th className="px-2 py-2 text-right font-normal">All-play</th>
                <th className="px-2 py-2 text-right font-normal">xW</th>
                <th className="py-2 pl-2 text-right font-normal">Luck</th>
              </tr>
            </thead>
            <tbody className="num">
              {league.teams.map((t) => {
                const p = power.find((x) => x.team_id === t.id);
                return (
                  <tr key={t.id} className="border-b border-line last:border-0">
                    <td className="py-2 pr-2 text-muted">{t.playoff_seed ?? "–"}</td>
                    <td className="py-2 pr-2">
                      <Link
                        href={teamHref(t.id)}
                        className={t.id === mine ? "font-semibold text-ink" : "text-ink-2 hover:text-ink"}
                      >
                        {t.id === mine && <span className="mr-1.5 inline-block h-2.5 w-1 bg-accent" aria-hidden />}
                        {t.name}
                      </Link>
                      <div className="text-xs text-muted">{t.owner_name}</div>
                    </td>
                    <td className="px-2 py-2 text-right">{record(t)}</td>
                    <td className="px-2 py-2 text-right">{t.points_for.toFixed(1)}</td>
                    <td className="px-2 py-2 text-right text-ink-2">{t.points_against.toFixed(1)}</td>
                    <td className="px-2 py-2 text-right">{p ? `${p.all_play.wins}-${p.all_play.losses}` : "–"}</td>
                    <td className="px-2 py-2 text-right">{p ? p.expected_wins.toFixed(1) : "–"}</td>
                    <td className="py-2 pl-2 text-right">
                      {p && Math.abs(p.luck) >= 0.05 ? (
                        <span className={p.luck > 0 ? "text-good" : "text-critical"}>
                          {p.luck > 0 ? "▲ +" : "▼ "}
                          {p.luck.toFixed(1)}
                        </span>
                      ) : (
                        <span className="text-muted">0.0</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Points per week" subtitle="Completed regular-season weeks">
        <WeeklyScores
          series={power.map((p) => ({
            teamId: p.team_id,
            name: teams.get(p.team_id)?.name ?? "?",
            isMine: p.team_id === mine,
            points: p.weekly_points,
          }))}
        />
      </Card>

      <Card
        title="Positional strength"
        subtitle="League rank of each team's starters (+ best backup) by position. Needs and depth drive waiver and trade ideas."
      >
        <PositionHeatmap
          rows={power.map((p) => ({
            teamId: p.team_id,
            name: teams.get(p.team_id)?.name ?? "?",
            href: teamHref(p.team_id),
            isMine: p.team_id === mine,
            positions: positions.teams[String(p.team_id)] ?? {},
          }))}
        />
      </Card>
    </div>
  );
}
