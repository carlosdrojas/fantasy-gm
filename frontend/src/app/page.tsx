import Link from "next/link";
import { AddLeagueForm } from "@/components/add-league-form";
import { Card, ErrorPanel, record } from "@/components/ui";
import { ApiError, api } from "@/lib/api";

export default async function Home() {
  let leagues, health;
  try {
    [leagues, health] = await Promise.all([api.leagues(), api.health()]);
  } catch (e) {
    return <ErrorPanel message={e instanceof ApiError ? e.message : String(e)} />;
  }

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Your leagues</h1>

      {!health.espn_auth_configured && (
        <p className="rounded-lg border border-line bg-surface-2 px-4 py-3 text-sm text-ink-2">
          ESPN cookies aren&apos;t set, so only public leagues will load and your team won&apos;t be
          detected. Add <code>FGM_ESPN_S2</code> and <code>FGM_ESPN_SWID</code> to{" "}
          <code>backend/.env</code> and restart the backend.
        </p>
      )}

      {leagues.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {leagues.map((lg) => (
            <Link
              key={lg.id}
              href={`/leagues/${lg.id}`}
              className="rounded-xl border border-line bg-surface p-4 transition-colors hover:bg-surface-2"
            >
              <div className="font-medium text-ink">{lg.name ?? `League ${lg.external_id}`}</div>
              <div className="mt-0.5 text-xs text-muted">
                {lg.season} · Week {lg.current_week ?? "–"} · {lg.settings.team_count} teams
              </div>
              {lg.my_team && (
                <div className="mt-3 text-sm text-ink-2">
                  {lg.my_team.name} <span className="num text-ink">{record(lg.my_team)}</span>
                </div>
              )}
            </Link>
          ))}
        </div>
      )}

      <Card
        title="Add an ESPN league"
        subtitle="Open your league on fantasy.espn.com and copy the number after leagueId= in the address bar."
        className="max-w-xl"
      >
        <AddLeagueForm defaultSeason={new Date().getFullYear()} />
      </Card>
    </div>
  );
}
