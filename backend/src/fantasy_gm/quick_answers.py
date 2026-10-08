"""Keyless assistant: a fixed menu of questions answered from the league analytics.

No model involved. Each answer runs the same analytics the Claude assistant's tools use
and fills in a short markdown write-up, so it's instant, free and deterministic. This is
what the public demo (and anyone without an API key) gets.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fantasy_gm.analytics.league import (
    LeagueData,
    PlayerRow,
    positional_strength,
    power_rankings,
    waiver_suggestions,
)
from fantasy_gm.analytics.lineup import optimal_lineup
from fantasy_gm.analytics.simulate import simulate
from fantasy_gm.analytics.trades import find_trades


@dataclass(frozen=True)
class Question:
    id: str
    label: str
    answer: Callable[[LeagueData, int, Callable[[], dict]], str]


class NoTeamError(ValueError):
    """The league has no 'my team' (ESPN cookies not set), so there's no one to advise."""


def answer(data: LeagueData, question_id: str, odds: Callable[[], dict] | None = None) -> str:
    """``odds`` returns the playoff simulation; pass a cached one to skip re-simulating."""
    q = QUESTIONS_BY_ID.get(question_id)
    if q is None:
        raise KeyError(question_id)
    me = data.league.my_team_id
    if me is None or me not in data.teams:
        raise NoTeamError("Your team isn't known for this league, so there's nothing to answer.")
    return q.answer(data, me, odds or (lambda: simulate(data)))


# --- helpers ----------------------------------------------------------------------


def _name(data: LeagueData, tid: int | None) -> str:
    return data.teams[tid].name if tid in data.teams else "?"


def _p(r: dict | PlayerRow) -> str:
    """'Name (POS, TEAM)' from a player_json dict or a PlayerRow."""
    if isinstance(r, PlayerRow):
        return f"{r.player.full_name} ({r.player.position}, {r.player.pro_team or 'FA'})"
    return f"{r['name']} ({r['position']}, {r['pro_team'] or 'FA'})"


def _pct(x: float) -> str:
    return f"{x:.0f}%" if x >= 1 or x == 0 else "<1%"


def _record(t) -> str:
    return f"{t.wins}-{t.losses}" + (f"-{t.ties}" if t.ties else "")


INJURY_WORDS = {
    "QUESTIONABLE": "questionable",
    "DOUBTFUL": "doubtful",
    "OUT": "out",
    "INJURY_RESERVE": "on IR",
}


# --- answers ----------------------------------------------------------------------


def a_lineup(data: LeagueData, me: int, odds: Callable[[], dict]) -> str:
    rows = data.rosters.get(me, [])
    lineup = optimal_lineup([r.lineup_player(this_week=True) for r in rows], data.slot_counts)
    best = {p.player_id for ps in lineup.values() for p in ps}
    current = {r.player.id for r in rows if r.slot not in ("BE", "IR")}
    by_id = {r.player.id: r for r in rows}

    def proj(r: PlayerRow) -> float:
        return r.value.this_week_projection or 0.0

    start = sorted((by_id[i] for i in best - current), key=proj, reverse=True)
    sit = sorted((by_id[i] for i in current - best), key=proj)
    week = data.league.current_week
    if not start and not sit:
        total = sum(proj(by_id[i]) for i in best)
        return (
            f"**Your lineup is already optimal for week {week}.** Your starters project for "
            f"{total:.1f} points; no bench player projects higher than the starter he'd replace."
        )
    gain = sum(proj(r) for r in start) - sum(proj(r) for r in sit)
    lines = [
        f"**Make {len(start)} change{'s' if len(start) != 1 else ''} for week {week}** "
        f"(+{gain:.1f} projected points):",
        "",
    ]
    for r in start:
        lines.append(f"- **Start** {_p(r)}: projected {proj(r):.1f}")
    for r in sit:
        why = INJURY_WORDS.get((r.player.injury_status or "").upper())
        note = f", {why}" if why else " (bye or not expected to play)" if not proj(r) else ""
        lines.append(f"- **Bench** {_p(r)}: projected {proj(r):.1f}{note}")
    lines += ["", "Projections are ESPN's for this week. Make the swap on ESPN before kickoff."]
    return "\n".join(lines)


def a_waivers(data: LeagueData, me: int, odds: Callable[[], dict]) -> str:
    picks = waiver_suggestions(data, me, limit=3)
    if not picks:
        return (
            "**Nobody on waivers improves your lineup right now.** Every available player "
            "projects below the starters and top backups you already have."
        )
    lines = ["**Top waiver pickups for your team:**", ""]
    for i, s in enumerate(picks, 1):
        p = s["player"]
        v = p["value"]
        drop = f" Drop {_p(s['drop'])}." if s["drop"] else ""
        recent = f", {v['recent_avg']:.1f} recent avg" if v["recent_avg"] is not None else ""
        if s["ros_gain"] > 0:
            gain = f"Adds {s['ros_gain']:+.1f} pts/week to your best lineup"
            gain += f" ({s['week_gain']:+.1f} this week)." if s["week_gain"] else "."
        else:
            gain = f"A one-week fill-in: {s['week_gain']:+.1f} pts to this week's lineup."
        lines.append(
            f"{i}. **{_p(p)}**: {v['per_game']:.1f} expected pts/game{recent}. {gain}{drop}"
        )
    lines += [
        "",
        "Gains are how much your best possible lineup improves, not the player's raw points.",
    ]
    return "\n".join(lines)


def a_trades(data: LeagueData, me: int, odds: Callable[[], dict]) -> str:
    trades = find_trades(data, me, None, limit=3, sort="balanced")
    if not trades:
        return "**No trades found that improve your lineup** without being lopsided."
    lines = ["**Best trade ideas** (ranked by your gain times the chance they accept):", ""]
    for i, t in enumerate(trades, 1):
        give = " + ".join(_p(p) for p in t["give"])
        get = " + ".join(_p(p) for p in t["get"])
        lines.append(
            f"{i}. To **{_name(data, t['partner_team_id'])}**: send {give}, get {get}. "
            f"Your lineup gains {t['my_gain']:+.1f} pts/week; about "
            f"{t['acceptance'] * 100:.0f}% likely to be accepted."
        )
    lines += ["", "Run any of these through the Trades tab to see the playoff-odds swing."]
    return "\n".join(lines)


def a_needs(data: LeagueData, me: int, odds: Callable[[], dict]) -> str:
    strength = positional_strength(data)
    mine = strength[me]
    n = len(data.teams)
    needs = sorted((p for p, c in mine.items() if c["label"] == "need"), key=lambda p: mine[p]["z"])
    surplus = [p for p, c in mine.items() if c["label"] == "surplus"]
    ranks = ", ".join(f"{p} #{c['rank']}" for p, c in mine.items())
    if not needs:
        return f"**No glaring weaknesses.** Your league rank at each position: {ranks} (of {n})."
    lines = [f"**Your weakest spot{'s' if len(needs) > 1 else ''}: {', '.join(needs)}.**", ""]
    for pos in needs:
        partners = [
            tid
            for tid, cells in strength.items()
            if tid != me
            and cells[pos]["label"] == "surplus"
            and any(cells[s]["label"] == "need" for s in surplus)
        ]
        line = f"- **{pos}**: ranked #{mine[pos]['rank']} of {n}."
        if partners:
            names = ", ".join(_name(data, t) for t in partners)
            line += f" {names} {'are' if len(partners) > 1 else 'is'} deep at {pos} and short where you're deep: natural trade partners."
        lines.append(line)
    if surplus:
        lines += ["", f"You have depth to deal from at **{', '.join(surplus)}**."]
    lines += ["", f"All positions: {ranks}."]
    return "\n".join(lines)


def a_odds(data: LeagueData, me: int, odds: Callable[[], dict]) -> str:
    odds_ = odds()
    o = odds_[me]
    rank = sorted(odds_, key=lambda t: -odds_[t]["playoff_pct"]).index(me) + 1
    playoff_teams = (data.league.settings or {}).get("playoff_team_count")
    t = data.teams[me]
    lines = [
        f"**{_pct(o['playoff_pct'])} to make the playoffs** "
        f"({rank}{_ordinal(rank)}-best odds in the league).",
        "",
        f"- Record now: {_record(t)}. Projected finish: {o['avg_wins']:.1f} wins, "
        f"average seed {o['avg_seed']:.1f}"
        + (f" ({playoff_teams} teams make it)." if playoff_teams else "."),
        f"- Championship: {_pct(o['champion_pct'])}. #1 seed: {_pct(o['first_seed_pct'])}.",
        "",
        "From 5,000 simulated seasons using each team's points so far and current roster strength.",
    ]
    return "\n".join(lines)


def a_luck(data: LeagueData, me: int, odds: Callable[[], dict]) -> str:
    rows = power_rankings(data)
    r = next(x for x in rows if x["team_id"] == me)
    ap = r["all_play"]
    luck = r["luck"]
    if luck <= -0.75:
        verdict = "**Unlucky.** You've played better than your record shows."
    elif luck >= 0.75:
        verdict = "**Lucky.** Your record is better than your scoring."
    else:
        verdict = "**Your record is about right** for how you've scored."
    return "\n".join(
        [
            verdict,
            "",
            f"- Power rank: **#{r['rank']}** of {len(rows)} (score {r['power_score']:.0f}/100).",
            f"- All-play record: {ap['wins']}-{ap['losses']} (as if you played every team every "
            f"week), which is worth {r['expected_wins']:.1f} expected wins. You have "
            f"{r['actual_wins']:.0f}: luck {luck:+.1f} wins.",
            f"- Roster strength: {r['roster_strength']:.1f} pts/week from your best lineup.",
        ]
    )


def a_matchup(data: LeagueData, me: int, odds: Callable[[], dict]) -> str:
    week = data.league.current_week
    m = next(
        (x for x in data.matchups if x.week == week and me in (x.home_team_id, x.away_team_id)),
        None,
    )
    if m is None or m.away_team_id is None:
        return f"**No matchup for you in week {week}** (bye or the season is over)."
    home = m.home_team_id == me
    opp = m.away_team_id if home else m.home_team_id
    mine_proj = m.home_projected if home else m.away_projected
    theirs_proj = m.away_projected if home else m.home_projected
    lines = [f"**Week {week}: you vs {_name(data, opp)}** ({_record(data.teams[opp])})", ""]
    if mine_proj is not None and theirs_proj is not None:
        diff = mine_proj - theirs_proj
        side = "favored" if diff > 0 else "the underdog"
        lines.append(
            f"- Projected: {mine_proj:.1f} to {theirs_proj:.1f}. You're {side} by {abs(diff):.1f}."
        )
    top = sorted(
        (r for r in data.rosters.get(opp, []) if r.slot not in ("BE", "IR")),
        key=lambda r: -(r.value.this_week_projection or 0),
    )[:3]
    if top:
        threats = ", ".join(f"{_p(r)} ({r.value.this_week_projection or 0:.1f})" for r in top)
        lines.append(f"- Their biggest threats: {threats}.")
    lines += ["", 'Ask "Is my lineup set right?" to squeeze out extra points.']
    return "\n".join(lines)


def a_threat(data: LeagueData, me: int, odds: Callable[[], dict]) -> str:
    rows = power_rankings(data)
    top = next(r for r in rows if r["team_id"] != me)
    t = data.teams[top["team_id"]]
    lines = [
        f"**{t.name} is the team to beat**: #{top['rank']} in power rankings "
        f"({top['power_score']:.0f}/100), {_record(t)}.",
        "",
        f"- Their best lineup scores {top['roster_strength']:.1f} pts/week; "
        f"{_pct(odds()[t.id]['champion_pct'])} to win it all.",
    ]
    lucky = max(rows, key=lambda r: r["luck"])
    if lucky["luck"] >= 0.75:
        lines.append(
            f"- Watch for a fall: {_name(data, lucky['team_id'])} is the luckiest team "
            f"({lucky['luck']:+.1f} wins above their all-play record)."
        )
    return "\n".join(lines)


def _ordinal(n: int) -> str:
    return "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


QUESTIONS = [
    Question("lineup", "Is my lineup set right for this week?", a_lineup),
    Question("waivers", "Who should I pick up off waivers?", a_waivers),
    Question("trades", "Find me a trade that helps my team.", a_trades),
    Question("needs", "Where is my team weak, and who can fix it?", a_needs),
    Question("odds", "What are my playoff odds?", a_odds),
    Question("luck", "Am I actually good, or just lucky?", a_luck),
    Question("matchup", "How does my matchup look this week?", a_matchup),
    Question("threat", "Who's the team to beat?", a_threat),
]
QUESTIONS_BY_ID = {q.id: q for q in QUESTIONS}
