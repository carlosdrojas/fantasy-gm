import { SignInButton } from "@clerk/nextjs";
import Link from "next/link";
import { AddLeagueForm } from "@/components/add-league-form";
import { Card, ErrorPanel, record } from "@/components/ui";
import { ApiError, api, type League, type Me, type Team } from "@/lib/api";
import { REPO_URL } from "@/lib/site";

export default async function Home() {
  let leagues, health, me;
  try {
    [leagues, health, me] = await Promise.all([api.leagues(), api.health(), api.me()]);
  } catch (e) {
    return <ErrorPanel message={e instanceof ApiError ? e.message : String(e)} />;
  }
  const demoLeague = leagues.find((lg) => lg.is_demo);
  const mine = leagues.filter((lg) => !lg.is_demo);

  if (health.accounts_enabled && !me.signed_in) return <DemoHome league={demoLeague} canSignIn />;
  if (health.demo_mode && !health.accounts_enabled) return <DemoHome league={demoLeague} />;

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Your leagues</h1>

      {me.signed_in && <CookieNotice me={me} />}

      {!health.accounts_enabled && !health.espn_auth_configured && (
        <p className="rounded-lg border border-line bg-surface-2 px-4 py-3 text-sm text-ink-2">
          ESPN cookies aren&apos;t set, so only public leagues will load and your team won&apos;t be
          detected. Add <code>FGM_ESPN_S2</code> and <code>FGM_ESPN_SWID</code> to{" "}
          <code>backend/.env</code> and restart the backend.
        </p>
      )}

      {mine.length === 0 && health.accounts_enabled && (
        <p className="text-sm text-ink-2">
          No leagues yet. Add one below, or look around the{" "}
          {demoLeague ? (
            <Link href={`/leagues/${demoLeague.id}`} className="text-link hover:underline">
              demo league
            </Link>
          ) : (
            "demo league"
          )}{" "}
          first.
        </p>
      )}

      {leagues.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[...mine, ...(demoLeague ? [demoLeague] : [])].map((lg) => (
            <Link
              key={lg.id}
              href={`/leagues/${lg.id}`}
              className="rounded-xl border border-line bg-surface p-4 transition-colors hover:bg-surface-2"
            >
              <div className="font-medium text-ink">
                {lg.name ?? `League ${lg.external_id}`}
                {lg.is_demo && <span className="ml-2 text-xs font-normal text-muted">Sample data</span>}
              </div>
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

const FEATURES = [
  ["Power rankings", "All-play records, expected wins and luck: who is good, not just lucky."],
  ["Lineup fixes", "An exact optimizer that handles FLEX slots, byes and injuries."],
  ["Trade finder", "Searches every 1-for-1 to 2-for-2 deal and estimates the odds they accept."],
  ["Playoff odds", "5,000 simulated seasons, re-run for any trade you are weighing."],
  ["Waiver pickups", "Every free agent tested in your lineup, with the right player to drop."],
  ["Assistant", "Instant answers from the analytics, or Claude with your own API key."],
];

function CookieNotice({ me }: { me: Extract<Me, { signed_in: true }> }) {
  if (me.espn?.status === "expired") {
    return (
      <p className="rounded-lg border border-critical px-4 py-3 text-sm text-ink">
        ESPN stopped accepting your cookies, so private leagues can&apos;t sync.{" "}
        <Link href="/settings" className="text-link hover:underline">
          Paste fresh ones in Settings
        </Link>
        .
      </p>
    );
  }
  if (me.espn) return null;
  return (
    <p className="rounded-lg border border-line bg-surface-2 px-4 py-3 text-sm text-ink-2">
      Public leagues work as is. For a private league (most are), first{" "}
      <Link href="/settings" className="text-link hover:underline">
        add your ESPN cookies in Settings
      </Link>
      . They also let us find your team automatically.
    </p>
  );
}

function DemoHome({ league, canSignIn = false }: { league?: League & { my_team: Team | null }; canSignIn?: boolean }) {
  return (
    <div className="space-y-10">
      <section className="max-w-2xl space-y-4 pt-4">
        <h1 className="font-display text-4xl font-extrabold tracking-wide text-ink sm:text-5xl">
          A general manager for your fantasy football league
        </h1>
        <p className="text-ink-2">
          Fantasy GM syncs an ESPN league and works out what the standings don&apos;t show: who is actually good, which
          lineup scores the most, which trades help you, and how they move your playoff odds.
        </p>
        <div className="flex flex-wrap gap-3">
          {league && (
            <Link
              href={`/leagues/${league.id}`}
              className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-accent-ink"
            >
              Open the demo league
            </Link>
          )}
          {canSignIn ? (
            <SignInButton mode="modal">
              <button className="rounded-md border border-line px-4 py-2 text-sm text-ink hover:bg-surface-2">
                Sign in to add your league
              </button>
            </SignInButton>
          ) : (
            <a href={REPO_URL} className="rounded-md border border-line px-4 py-2 text-sm text-ink hover:bg-surface-2">
              Run it on your league
            </a>
          )}
        </div>
        {league?.my_team && (
          <p className="text-xs text-muted">
            You manage <span className="text-ink-2">{league.my_team.name}</span>,{" "}
            <span className="num">{record(league.my_team)}</span> in week {league.current_week} of {league.name}.
          </p>
        )}
      </section>

      <Card title="What it does">
        <dl className="grid gap-x-8 gap-y-5 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map(([name, text]) => (
            <div key={name}>
              <dt className="font-medium text-ink">{name}</dt>
              <dd className="mt-1 text-sm text-ink-2">{text}</dd>
            </div>
          ))}
        </dl>
      </Card>
    </div>
  );
}
