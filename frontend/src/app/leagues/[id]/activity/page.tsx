import { Card, EmptyState } from "@/components/ui";
import { api, type Team } from "@/lib/api";

const TYPE_LABELS: Record<string, string> = {
  WAIVER: "Waiver claim",
  FREEAGENT: "Free agent",
  TRADE_ACCEPT: "Trade",
  TRADE_PROPOSAL: "Trade proposal",
  ROSTER: "Roster move",
};

export default async function ActivityPage({ params }: PageProps<"/leagues/[id]/activity">) {
  const id = Number((await params).id);
  const [league, txns] = await Promise.all([api.league(id), api.transactions(id)]);
  const teams = new Map<number, Team>(league.teams.map((t) => [t.id, t]));
  const teamName = (tid: number | null) => (tid ? (teams.get(tid)?.name ?? "?") : "Free agency");

  // Activity per team: adds and trades, for spotting active (trade-friendly) managers.
  const counts = new Map<number, { adds: number; trades: number; faab: number }>();
  for (const t of txns) {
    if (t.status !== "EXECUTED" || t.team_id == null) continue;
    const c = counts.get(t.team_id) ?? { adds: 0, trades: 0, faab: 0 };
    if (t.type.startsWith("TRADE")) c.trades += 1;
    else if (t.items.some((i) => i.type === "ADD")) c.adds += 1;
    c.faab += t.bid_amount ?? 0;
    counts.set(t.team_id, c);
  }

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <Card title="Transactions" subtitle="Adds, drops, waiver claims and trades" className="lg:col-span-2">
        {txns.length === 0 ? (
          <EmptyState>No transactions yet.</EmptyState>
        ) : (
          <ul className="divide-y divide-line text-sm">
            {txns.map((t) => (
              <li key={t.id} className="py-2.5">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="font-medium text-ink">
                    {TYPE_LABELS[t.type] ?? t.type}
                    {t.team_id && <span className="font-normal text-ink-2"> · {teamName(t.team_id)}</span>}
                  </span>
                  <span className="text-xs text-muted">
                    {t.status !== "EXECUTED" && (
                      <span className={`mr-2 ${t.status === "PENDING" ? "font-semibold text-link" : ""}`}>
                        {t.status.charAt(0) + t.status.slice(1).toLowerCase()}
                      </span>
                    )}
                    {t.bid_amount ? `$${t.bid_amount} · ` : ""}
                    Wk {t.week ?? "–"}
                    {t.proposed_at && ` · ${new Date(t.proposed_at).toLocaleDateString()}`}
                  </span>
                </div>
                <ul className="mt-1 space-y-0.5 text-xs text-ink-2">
                  {t.items.map((i, idx) => (
                    <li key={idx}>
                      <span
                        className={`mr-1.5 inline-block w-11 font-semibold ${
                          i.type === "ADD" ? "text-good" : i.type === "DROP" ? "text-critical" : "text-ink"
                        }`}
                      >
                        {i.type === "ADD" ? "+ Add" : i.type === "DROP" ? "− Drop" : "⇄"}
                      </span>
                      {i.player ? `${i.player.name} (${i.player.position})` : "Unknown player"}
                      {i.type === "TRADE" && (
                        <span className="text-muted">
                          {" "}
                          {teamName(i.from_team_id)} → {teamName(i.to_team_id)}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Manager activity" subtitle="Executed moves this season (synced so far)">
        <table className="w-full text-sm">
          <thead className="text-xs text-muted">
            <tr className="border-b border-line">
              <th className="py-1.5 text-left font-normal">Team</th>
              <th className="py-1.5 text-right font-normal">Adds</th>
              <th className="py-1.5 text-right font-normal">Trades</th>
              {league.settings.uses_faab && <th className="py-1.5 text-right font-normal">FAAB</th>}
            </tr>
          </thead>
          <tbody className="num">
            {league.teams.map((tm) => {
              const c = counts.get(tm.id) ?? { adds: 0, trades: 0, faab: 0 };
              return (
                <tr key={tm.id} className="border-b border-line last:border-0">
                  <td className={`max-w-36 truncate py-1.5 ${tm.id === league.my_team_id ? "font-semibold" : "text-ink-2"}`}>
                    {tm.name}
                  </td>
                  <td className="py-1.5 text-right">{c.adds}</td>
                  <td className="py-1.5 text-right">{c.trades}</td>
                  {league.settings.uses_faab && <td className="py-1.5 text-right">${tm.faab_spent ?? c.faab}</td>}
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
