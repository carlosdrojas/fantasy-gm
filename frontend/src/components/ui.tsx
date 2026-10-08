import Link from "next/link";
import type { ReactNode } from "react";
import type { PlayerGame, PlayerRow } from "@/lib/api";

/** A page section. Sections are divided by a rule and space, not boxed: only the score
 * strip gets a strong container, so it stays the one thing that stands out. */
export function Card({
  title,
  subtitle,
  action,
  children,
  className = "",
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`border-t border-line pt-4 ${className}`}>
      {(title || action) && (
        <header className="mb-4 flex items-start justify-between gap-3">
          <div className="min-w-0">
            {title && (
              <h2 className="font-display text-xl font-semibold tracking-wide text-ink">{title}</h2>
            )}
            {subtitle && <p className="mt-0.5 max-w-prose text-xs text-muted">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function StatTile({
  label,
  value,
  detail,
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-ink">{value}</div>
      {detail && <div className="mt-1 text-xs text-ink-2">{detail}</div>}
    </div>
  );
}

const INJURY_LABELS: Record<string, string> = {
  QUESTIONABLE: "Q",
  DOUBTFUL: "D",
  OUT: "O",
  INJURY_RESERVE: "IR",
  SUSPENSION: "SSPD",
};

export function InjuryBadge({ status }: { status: string | null }) {
  const label = status ? INJURY_LABELS[status] : undefined;
  if (!label) return null;
  const severe = status !== "QUESTIONABLE";
  return (
    <span
      title={status!.replace("_", " ").toLowerCase()}
      className={`ml-1.5 inline-flex items-center gap-0.5 rounded px-1 text-[10px] font-semibold ${
        severe ? "text-critical" : "text-ink-2"
      }`}
    >
      <span aria-hidden>{severe ? "●" : "○"}</span>
      {label}
    </span>
  );
}

export function PlayerName({ p }: { p: PlayerRow }) {
  return (
    <span className="whitespace-nowrap">
      <span className="font-medium text-ink">{p.name}</span>
      <span className="ml-1.5 text-xs text-muted">
        {p.position} · {p.pro_team ?? "FA"}
      </span>
      <InjuryBadge status={p.injury_status} />
    </span>
  );
}

export function Trend({ value }: { value: number | null }) {
  if (value == null || Math.abs(value) < 0.5) return <span className="text-muted">–</span>;
  const up = value > 0;
  return (
    <span className={up ? "text-good" : "text-critical"}>
      {up ? "▲" : "▼"} {Math.abs(value).toFixed(1)}
    </span>
  );
}

export function fmt(n: number | null | undefined, digits = 1) {
  return n == null ? "–" : n.toFixed(digits);
}

export function record(t: { wins: number; losses: number; ties: number }) {
  return `${t.wins}-${t.losses}${t.ties ? `-${t.ties}` : ""}`;
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-muted">{children}</p>;
}

export function ErrorPanel({ message }: { message: string }) {
  return (
    <div className="mx-auto max-w-xl rounded-lg border border-line bg-surface p-6 text-sm">
      <p className="font-semibold text-critical">Couldn&apos;t load this page</p>
      <p className="mt-2 text-ink-2">{message}</p>
      <Link href="/" className="mt-4 inline-block text-link underline">
        Back to leagues
      </Link>
    </div>
  );
}

function kickoffLabel(iso: string | null) {
  if (!iso) return "TBD";
  return new Date(iso).toLocaleString("en-US", {
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** A player's game this week: kickoff, live clock and score, or final result. */
export function GameStatus({ game }: { game: PlayerGame | null }) {
  if (!game || game.state === "none") return <span className="text-muted">–</span>;
  if (game.state === "bye") return <span className="text-muted">Bye</span>;
  const opp = `${game.is_home ? "vs" : "@"} ${game.opponent}`;
  const score = `${game.team_score ?? 0}-${game.opponent_score ?? 0}`;
  if (game.state === "pre") {
    return (
      <span className="text-muted">
        {kickoffLabel(game.kickoff)} · {opp}
      </span>
    );
  }
  if (game.state === "in") {
    return (
      <span className="inline-flex items-center gap-1 text-ink">
        <span className="h-1.5 w-1.5 rounded-full bg-critical" aria-label="In progress" />
        <span className="font-medium">{game.detail}</span>
        <span className="text-ink-2">
          · {score} {opp}
        </span>
      </span>
    );
  }
  const diff = (game.team_score ?? 0) - (game.opponent_score ?? 0);
  const result = diff > 0 ? "W" : diff < 0 ? "L" : "T";
  return (
    <span className="text-ink-2">
      <span className={diff > 0 ? "text-good" : diff < 0 ? "text-critical" : ""}>{result}</span> {score}{" "}
      {opp}
    </span>
  );
}

/** This week's fantasy points: live while the game is on, final after, blank before kickoff. */
export function WeekPoints({ p }: { p: PlayerRow }) {
  const state = p.game?.state;
  const pts = p.value.this_week_actual;
  if (state === "pre" || state === "bye" || (pts == null && state !== "in")) {
    return <span className="text-muted">–</span>;
  }
  return (
    <span className={state === "in" ? "font-semibold text-link" : "font-medium text-ink"}>
      {fmt(pts ?? 0)}
    </span>
  );
}

/** Short team labels for pill rows. ESPN abbreviations can collide (two "GGT"s), so a
 * duplicated abbreviation falls back to the full team name. */
export function teamLabeler(teams: { abbrev: string | null; name: string }[]) {
  const counts = new Map<string, number>();
  for (const t of teams) if (t.abbrev) counts.set(t.abbrev, (counts.get(t.abbrev) ?? 0) + 1);
  return (t: { abbrev: string | null; name: string }) =>
    t.abbrev && counts.get(t.abbrev) === 1 ? t.abbrev : t.name;
}
