import Link from "next/link";
import { TradeAnalyzer } from "@/components/trade-analyzer";
import { TradeCard } from "@/components/trade-card";
import { Card, EmptyState, ErrorPanel, teamLabeler } from "@/components/ui";
import { ApiError, api, type TradeSort } from "@/lib/api";

const SORTS: { key: TradeSort; label: string; hint: string }[] = [
  { key: "balanced", label: "Balanced", hint: "Your gain weighted by the chance they accept" },
  { key: "gain", label: "Best for me", hint: "Biggest improvement to your lineup" },
  { key: "likely", label: "Most likely", hint: "Highest chance the other manager accepts" },
];

export default async function TradesPage({ params, searchParams }: PageProps<"/leagues/[id]/trades">) {
  const id = Number((await params).id);
  const sp = await searchParams;
  const sort = (SORTS.find((s) => s.key === sp.sort)?.key ?? "balanced") as TradeSort;
  const partnerId = typeof sp.partner === "string" && /^\d+$/.test(sp.partner) ? Number(sp.partner) : undefined;
  const nowOnly = sp.now === "1";

  const league = await api.league(id);
  if (!league.my_team_id) {
    return <ErrorPanel message="Your team couldn't be detected. Set your ESPN cookies in backend/.env, restart, and sync." />;
  }
  let trades;
  try {
    trades = (await api.trades(id, { partnerId, sort, tradeableNow: nowOnly })).trades;
  } catch (e) {
    return <ErrorPanel message={e instanceof ApiError ? e.message : String(e)} />;
  }
  const myRoster = (await api.team(id, league.my_team_id)).roster;
  const teams = new Map(league.teams.map((t) => [t.id, t]));
  const others = league.teams.filter((t) => t.id !== league.my_team_id);
  const label = teamLabeler(league.teams);
  const href = (q: { sort?: string; partner?: number; now?: boolean }) => {
    const p = new URLSearchParams();
    const s = q.sort ?? sort;
    if (s !== "balanced") p.set("sort", s);
    const partner = "partner" in q ? q.partner : partnerId;
    if (partner) p.set("partner", String(partner));
    if (q.now ?? nowOnly) p.set("now", "1");
    const qs = p.toString();
    return `/leagues/${id}/trades${qs ? `?${qs}` : ""}`;
  };
  const chip = (active: boolean) =>
    `rounded-full border px-2.5 py-1 ${active ? "border-accent bg-accent text-accent-ink" : "border-line text-ink-2 hover:bg-surface-2"}`;

  return (
    <div className="space-y-6">
      <Card
        title="Trade ideas"
        subtitle="Searched across every roster (1-for-1 up to 2-for-2). Gains are points per week of your best lineup, plus a little bench depth. Acceptance is a rough estimate of how the other manager will see it."
      >
        <div className="mb-4 space-y-2 text-xs">
          <div className="flex flex-wrap gap-1.5">
            {SORTS.map((s) => (
              <Link key={s.key} href={href({ sort: s.key })} title={s.hint} className={chip(s.key === sort)}>
                {s.label}
              </Link>
            ))}
            <span className="mx-1 w-px self-stretch bg-line" aria-hidden />
            <Link
              href={href({ now: !nowOnly })}
              title="Leave out players whose game this week has started: ESPN locks them until the week ends"
              className={chip(nowOnly)}
              aria-pressed={nowOnly}
            >
              Tradeable now
            </Link>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <Link href={href({ partner: undefined })} className={chip(!partnerId)}>
              All teams
            </Link>
            {others.map((t) => (
              <Link key={t.id} href={href({ partner: t.id })} className={chip(partnerId === t.id)}>
                {label(t)}
              </Link>
            ))}
          </div>
        </div>
        {trades.length === 0 ? (
          <EmptyState>
            No trades found that improve your lineup{partnerId ? " with this team" : ""}
            {nowOnly ? " among players who haven't played yet this week" : ""}.
          </EmptyState>
        ) : (
          <div className="grid gap-3 lg:grid-cols-2">
            {trades.slice(0, 20).map((t, i) => (
              <TradeCard key={i} trade={t} partnerName={teams.get(t.partner_team_id)?.name ?? "?"} />
            ))}
          </div>
        )}
      </Card>

      <Card title="Trade analyzer" subtitle="Build any trade and see how it changes both lineups and both teams' playoff odds.">
        <TradeAnalyzer
          leagueId={id}
          myTeamId={league.my_team_id}
          myRoster={myRoster}
          teams={others.map((t) => ({ id: t.id, name: t.name }))}
          initialPartnerId={partnerId}
        />
      </Card>
    </div>
  );
}
