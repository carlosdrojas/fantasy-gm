import { LiveBadge, LiveRefresher } from "@/components/live";
import { LeagueTabs, SyncButton } from "@/components/league-nav";
import { ErrorPanel } from "@/components/ui";
import { ApiError, api } from "@/lib/api";

function ago(iso: string | null) {
  if (!iso) return "never";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)}h ago`;
  return `${Math.round(mins / 1440)}d ago`;
}

export default async function LeagueLayout({ children, params }: LayoutProps<"/leagues/[id]">) {
  const id = Number((await params).id);
  let league;
  try {
    league = await api.league(id);
  } catch (e) {
    return <ErrorPanel message={e instanceof ApiError ? e.message : String(e)} />;
  }
  const failed = league.last_sync?.status === "error";

  return (
    <div className="space-y-6">
      <div className="border-b border-line">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="font-display text-3xl font-extrabold tracking-wide">
                {league.name ?? `League ${league.external_id}`}
              </h1>
              <LiveBadge active={league.live.active} updatedAt={league.live.updated_at} />
            </div>
            <p className="mt-0.5 text-xs text-muted">
              {league.season} season, week {league.current_week ?? "–"}
              {league.final_regular_week ? ` of ${league.final_regular_week}` : ""},{" "}
              {league.settings.reception_points ? `${league.settings.reception_points} PPR` : "standard scoring"}.
              Synced {ago(league.last_synced_at)}.
            </p>
            {failed && (
              <p className="mt-2 text-xs text-critical">
                <span aria-hidden>● </span>Last sync failed: {league.last_sync?.error}
              </p>
            )}
          </div>
          <SyncButton leagueId={id} />
        </div>
        <LeagueTabs leagueId={id} myTeamId={league.my_team_id} />
      </div>
      <LiveRefresher active={league.live.active} />
      {children}
    </div>
  );
}
