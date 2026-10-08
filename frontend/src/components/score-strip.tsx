import Link from "next/link";
import { fmt, GameStatus } from "@/components/ui";
import type { LineupStatus, PlayerRow, Team } from "@/lib/api";

export type Side = {
  team: Team;
  href: string;
  points: number | null;
  projected: number | null;
  winProb: number | null;
  lineup: LineupStatus | null;
};

function lineupNote(l: LineupStatus | null) {
  if (!l) return null;
  const parts = [];
  if (l.playing) parts.push(`${l.playing} playing`);
  if (l.yet_to_play) parts.push(`${l.yet_to_play} to play`);
  if (!parts.length && l.played) parts.push("everyone has played");
  return parts.join(", ");
}

/**
 * Your matchup as a broadcast score strip. The win probability is drawn as a football
 * field: you drive from your end zone (left) toward theirs, and the yellow first-down
 * line sits at your chance to win. 74% puts you on their 26.
 */
export function ScoreStrip({
  week,
  me,
  them,
  final,
  stillToPlay,
}: {
  week: number | null;
  me: Side;
  them: Side | null;
  final: boolean;
  stillToPlay: PlayerRow[];
}) {
  const leading = them && (me.points ?? 0) >= (them.points ?? 0);
  return (
    <section
      aria-label={`Week ${week ?? ""} matchup`}
      className="rounded-lg border border-line bg-surface p-4 sm:p-6"
    >
      <div className="mb-3 flex items-baseline justify-between text-xs text-muted">
        <span>Week {week}</span>
        {final && <span className="font-semibold text-ink">Final</span>}
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-end gap-3 sm:gap-6">
        <TeamScore side={me} mine align="left" emphasized={!them || !!leading} />
        <span className="pb-3 font-display text-lg font-semibold text-muted sm:pb-5">vs</span>
        {them ? (
          <TeamScore side={them} align="right" emphasized={!leading} />
        ) : (
          <div className="text-right text-sm text-muted">Bye week</div>
        )}
      </div>

      {them && me.winProb != null && !final && <WinField pct={me.winProb * 100} />}

      {stillToPlay.length > 0 && (
        <div className="mt-5 border-t border-line pt-3">
          <h3 className="mb-1.5 text-xs text-muted">Your starters still to play</h3>
          <ul className="max-w-xl space-y-1 text-sm">
            {stillToPlay.map((p) => (
              <li key={p.id} className="flex min-w-0 items-baseline justify-between gap-3">
                <span className="truncate">
                  <span className="font-medium text-ink">{p.name}</span>
                  <span className="ml-1.5 text-xs text-muted">
                    {p.position}, {p.pro_team}
                  </span>
                </span>
                <span className="shrink-0 whitespace-nowrap text-xs">
                  <GameStatus game={p.game} />
                  {p.game?.state === "pre" && p.value.this_week_projection != null && (
                    <span className="num ml-2 text-muted">{fmt(p.value.this_week_projection)} proj</span>
                  )}
                  {p.game?.state === "in" && (
                    <span className="num ml-2 font-semibold text-link">{fmt(p.value.this_week_actual ?? 0)}</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function TeamScore({
  side,
  mine = false,
  align,
  emphasized,
}: {
  side: Side;
  mine?: boolean;
  align: "left" | "right";
  emphasized: boolean;
}) {
  const right = align === "right";
  const note = lineupNote(side.lineup);
  return (
    <div className={`min-w-0 ${right ? "text-right" : ""}`}>
      <Link
        href={side.href}
        className={`block truncate font-display text-xl font-semibold tracking-wide sm:text-2xl ${
          mine ? "text-ink" : "text-ink-2 hover:text-ink"
        }`}
      >
        {mine && <span className="mr-2 inline-block h-3 w-1.5 bg-accent align-middle" aria-hidden />}
        {side.team.name}
      </Link>
      <div
        className={`num font-display text-6xl leading-none font-extrabold sm:text-8xl ${
          mine ? "text-[var(--score-mine)]" : emphasized ? "text-ink" : "text-ink-2"
        }`}
      >
        {fmt(side.points)}
      </div>
      <div className="mt-2 text-xs text-muted">
        <span className="num">proj {fmt(side.projected)}</span>
        {note && <span>, {note}</span>}
      </div>
    </div>
  );
}

const YARD_LINES = [10, 20, 30, 40, 50, 60, 70, 80, 90];

function WinField({ pct }: { pct: number }) {
  const clamped = Math.min(100, Math.max(0, pct));
  const yardsToGo = Math.round(100 - clamped);
  const spot =
    clamped >= 99.5
      ? "in the end zone"
      : yardsToGo === 50
        ? "at midfield"
        : yardsToGo < 50
          ? `on their ${yardsToGo}`
          : `on your ${Math.round(clamped)}`;
  return (
    <figure className="mt-5">
      <div
        role="img"
        aria-label={`Win probability ${Math.round(clamped)}%`}
        className="relative grid h-14 grid-cols-[7%_1fr_7%] overflow-hidden rounded-sm"
        style={{ background: "var(--turf)" }}
      >
        <div className="border-r-2" style={{ background: "var(--endzone-mine)", borderColor: "var(--chalk-line)" }} />
        <div className="relative">
          {YARD_LINES.map((y) => (
            <span
              key={y}
              className="absolute top-0 bottom-0 w-px"
              style={{ left: `${y}%`, background: "var(--chalk-line)" }}
            >
              <span
                className="num absolute bottom-0.5 -translate-x-1/2 font-display text-[10px] font-semibold"
                style={{ color: "var(--chalk-text)" }}
              >
                {y <= 50 ? y : 100 - y}
              </span>
            </span>
          ))}
          {/* The yellow line: your chance to win, as field position. */}
          <span
            className="absolute -top-1 -bottom-1 w-1.5 -translate-x-1/2 bg-[var(--first-down)] shadow-[0_0_0_1px_var(--first-down-edge),0_0_14px_var(--first-down)] transition-[left] duration-700 ease-out motion-reduce:transition-none"
            style={{ left: `${clamped}%` }}
          />
        </div>
        <div className="border-l-2" style={{ background: "var(--endzone-them)", borderColor: "var(--chalk-line)" }} />
      </div>
      <figcaption className="mt-1.5 flex justify-between text-xs text-muted">
        <span>
          <span className="num font-semibold text-link">{Math.round(clamped)}%</span> to win, {spot}
        </span>
        <span className="num">{Math.round(100 - clamped)}%</span>
      </figcaption>
    </figure>
  );
}
