import Link from "next/link";
import type { OddsResponse, Team } from "@/lib/api";

function Pct({ value, isMine, bar = false }: { value: number | null; isMine: boolean; bar?: boolean }) {
  if (value == null) return <span className="text-muted">–</span>;
  const label = value >= 99.95 ? "100%" : value > 0 && value < 1 ? "<1%" : `${value.toFixed(0)}%`;
  if (!bar) return <span className="num">{label}</span>;
  return (
    <span className="flex items-center justify-end gap-2">
      <span className="hidden h-2 w-24 overflow-hidden rounded-r bg-transparent sm:block">
        <span
          className="block h-full rounded-r"
          style={{ width: `${Math.max(value, 0.8)}%`, background: isMine ? "var(--accent)" : "var(--other)" }}
        />
      </span>
      <span className="num w-10 text-right">{label}</span>
    </span>
  );
}

export function OddsTable({
  odds,
  teams,
  myTeamId,
  leagueId,
}: {
  odds: OddsResponse;
  teams: Team[];
  myTeamId: number | null;
  leagueId: number;
}) {
  const rows = teams
    .map((t) => ({ t, o: odds.teams[String(t.id)] }))
    .filter((r) => r.o)
    .sort((a, b) => b.o.playoff_pct - a.o.playoff_pct || b.o.champion_pct - a.o.champion_pct);
  const hasByes = rows.some((r) => r.o.bye_pct != null);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-xs text-muted">
          <tr className="border-b border-line">
            <th className="py-2 pr-2 text-left font-normal">Team</th>
            <th className="px-2 py-2 text-right font-normal">Proj. wins</th>
            <th className="px-2 py-2 text-right font-normal">Playoffs</th>
            {hasByes && <th className="px-2 py-2 text-right font-normal">Bye</th>}
            <th className="px-2 py-2 text-right font-normal">#1 seed</th>
            <th className="py-2 pl-2 text-right font-normal">Title</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ t, o }) => {
            const mine = t.id === myTeamId;
            return (
              <tr key={t.id} className="border-b border-line last:border-0">
                <td className="max-w-40 truncate py-2 pr-2">
                  <Link
                    href={`/leagues/${leagueId}/teams/${t.id}`}
                    className={mine ? "font-semibold text-ink" : "text-ink-2 hover:text-ink"}
                  >
                    {t.name}
                  </Link>
                </td>
                <td className="num px-2 py-2 text-right text-ink-2">{o.avg_wins.toFixed(1)}</td>
                <td className="px-2 py-2 text-right">
                  <Pct value={o.playoff_pct} isMine={mine} bar />
                </td>
                {hasByes && (
                  <td className="px-2 py-2 text-right text-ink-2">
                    <Pct value={o.bye_pct} isMine={mine} />
                  </td>
                )}
                <td className="px-2 py-2 text-right text-ink-2">
                  <Pct value={o.first_seed_pct} isMine={mine} />
                </td>
                <td className="py-2 pl-2 text-right">
                  <Pct value={o.champion_pct} isMine={mine} bar />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
