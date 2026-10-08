import Link from "next/link";
import { PowerBars } from "@/components/charts";
import { OddsTable } from "@/components/odds-table";
import { ScoreStrip, type Side } from "@/components/score-strip";
import { Card, EmptyState, fmt, record } from "@/components/ui";
import { api, type LeagueOverview, type Team } from "@/lib/api";

function ordinal(n: number) {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

type WeekMatchup = LeagueOverview["current_matchups"][number];

export default async function Dashboard({ params }: PageProps<"/leagues/[id]">) {
  const id = Number((await params).id);
  const [league, power, odds] = await Promise.all([api.league(id), api.power(id), api.odds(id)]);
  const teams = new Map<number, Team>(league.teams.map((t) => [t.id, t]));
  const mine = league.my_team_id;
  const teamHref = (tid: number) => `/leagues/${id}/teams/${tid}`;
  const myPower = power.find((p) => p.team_id === mine);
  const myTeam = mine ? teams.get(mine) : undefined;
  const myMatchup = league.current_matchups.find((m) => m.home_team_id === mine || m.away_team_id === mine);
  const others = league.current_matchups.filter((m) => m !== myMatchup);
  const myRoster = myMatchup && mine ? (await api.team(id, mine)).roster : [];

  const side = (m: WeekMatchup, home: boolean): Side | null => {
    const tid = home ? m.home_team_id : m.away_team_id;
    const team = tid != null ? teams.get(tid) : undefined;
    if (!team) return null;
    return {
      team,
      href: teamHref(team.id),
      points: home ? m.home_points : m.away_points,
      projected: home ? m.home_projected : m.away_projected,
      winProb: home ? m.home_win_prob : m.away_win_prob,
      lineup: home ? m.home_lineup : m.away_lineup,
    };
  };
  const iAmHome = myMatchup?.home_team_id === mine;
  const stillToPlay = myRoster.filter(
    (p) => p.slot !== "BE" && p.slot !== "IR" && (p.game?.state === "pre" || p.game?.state === "in"),
  );

  return (
    <div className="space-y-8">
      {myMatchup && (
        <ScoreStrip
          week={league.current_week}
          me={side(myMatchup, iAmHome)!}
          them={side(myMatchup, !iAmHome)}
          final={myMatchup.winner !== "UNDECIDED"}
          stillToPlay={stillToPlay}
        />
      )}

      {myTeam && myPower && (
        <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
          <Stat label="Record" value={record(myTeam)} detail={myTeam.playoff_seed ? `${ordinal(myTeam.playoff_seed)} seed` : undefined} />
          <Stat label="Power rank" value={`#${myPower.rank}`} detail={`of ${power.length}, score ${myPower.power_score.toFixed(0)}`} />
          <Stat
            label="All-play record"
            value={`${myPower.all_play.wins}-${myPower.all_play.losses}`}
            detail={`${(myPower.all_play.pct * 100).toFixed(0)}% against every team, every week`}
          />
          <Stat
            label="Luck"
            value={`${myPower.luck > 0 ? "+" : ""}${myPower.luck.toFixed(1)} W`}
            detail={`${myPower.actual_wins} actual vs. ${myPower.expected_wins.toFixed(1)} expected wins`}
          />
        </dl>
      )}

      <div className="grid gap-8 lg:grid-cols-5">
        <Card
          title={myMatchup ? "Around the league" : `Week ${league.current_week ?? ""} matchups`}
          subtitle="Live scores"
          className="min-w-0 lg:col-span-2"
        >
          {others.length === 0 ? (
            <EmptyState>No other matchups this week.</EmptyState>
          ) : (
            <ul className="divide-y divide-line">
              {others.map((m) => (
                <MatchupRow key={m.id} m={m} teams={teams} href={teamHref} mine={mine} />
              ))}
            </ul>
          )}
        </Card>

        <Card
          title="Power rankings"
          subtitle={
            power.some((p) => p.weekly_points.length > 0)
              ? "All-play win % (45%), last 3 weeks' scoring (25%), roster strength (30%)"
              : "Preseason: based on roster strength only"
          }
          className="min-w-0 lg:col-span-3"
        >
          <PowerBars
            data={power.map((p) => ({
              teamId: p.team_id,
              name: teams.get(p.team_id)?.name ?? "?",
              href: teamHref(p.team_id),
              score: p.power_score,
              isMine: p.team_id === mine,
              parts: [
                { label: "All-play", value: p.components.all_play },
                { label: "Recent form", value: p.components.recent_form },
                { label: "Roster strength", value: p.components.roster_strength },
              ],
            }))}
          />
        </Card>
      </div>

      <Card
        title="Playoff odds"
        subtitle={`${odds.sims.toLocaleString()} simulated seasons: the ${odds.remaining_weeks.length} remaining regular-season week${odds.remaining_weeks.length === 1 ? "" : "s"} and a ${odds.playoff_teams ?? "?"}-team bracket. Team strength blends points scored with current roster strength.`}
      >
        <OddsTable odds={odds} teams={league.teams} myTeamId={mine} leagueId={id} />
      </Card>

      <p className="text-xs text-muted">
        Standings, weekly scoring and positional strength are on the{" "}
        <Link href={`/leagues/${id}/league`} className="text-link hover:underline">
          League
        </Link>{" "}
        tab.
      </p>
    </div>
  );
}

function Stat({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="num font-display text-3xl font-extrabold tracking-wide text-ink">{value}</dd>
      {detail && <dd className="text-xs text-ink-2">{detail}</dd>}
    </div>
  );
}

function MatchupRow({
  m,
  teams,
  href,
  mine,
}: {
  m: WeekMatchup;
  teams: Map<number, Team>;
  href: (tid: number) => string;
  mine: number | null;
}) {
  const home = teams.get(m.home_team_id);
  const away = m.away_team_id != null ? teams.get(m.away_team_id) : undefined;
  if (!home) return null;
  const homeLeads = (m.home_points ?? 0) >= (m.away_points ?? 0);
  const name = (t: Team) => (
    <Link
      href={href(t.id)}
      className={`block truncate ${t.id === mine ? "font-semibold text-ink" : "text-ink-2 hover:text-ink"}`}
    >
      {t.name}
    </Link>
  );
  const left = (l: WeekMatchup["home_lineup"]) => (l ? l.playing + l.yet_to_play : 0);
  const notes = [
    left(m.home_lineup) > 0 && `${home.name}: ${left(m.home_lineup)} left`,
    away && left(m.away_lineup) > 0 && `${away.name}: ${left(m.away_lineup)} left`,
  ].filter(Boolean);
  return (
    <li className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-0.5 py-2.5 text-sm">
      {name(home)}
      <span className={`num text-right ${homeLeads ? "font-semibold text-ink" : "text-ink-2"}`}>{fmt(m.home_points)}</span>
      {away ? name(away) : <span className="text-muted">Bye</span>}
      <span className={`num text-right ${!homeLeads ? "font-semibold text-ink" : "text-ink-2"}`}>
        {away ? fmt(m.away_points) : ""}
      </span>
      {notes.length > 0 && <span className="col-span-2 text-xs text-muted">{notes.join("; ")}</span>}
    </li>
  );
}
