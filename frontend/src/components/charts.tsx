"use client";

import Link from "next/link";
import { useMemo, useRef, useState } from "react";

// ---------------------------------------------------------------------------
// Power rankings: one horizontal bar per team, my team in the accent color.

export type PowerBarDatum = {
  teamId: number;
  name: string;
  href: string;
  score: number;
  isMine: boolean;
  parts: { label: string; value: number }[];
};

export function PowerBars({ data }: { data: PowerBarDatum[] }) {
  const [hover, setHover] = useState<number | null>(null);
  return (
    <ol className="space-y-1.5" onMouseLeave={() => setHover(null)}>
      {data.map((d, i) => (
        <li key={d.teamId} className="relative">
          <Link
            href={d.href}
            onMouseEnter={() => setHover(d.teamId)}
            onFocus={() => setHover(d.teamId)}
            onBlur={() => setHover(null)}
            className="grid grid-cols-[1.25rem_minmax(0,9rem)_1fr_2.5rem] items-center gap-2 rounded py-1 text-sm hover:bg-surface-2"
          >
            <span className="num text-right text-xs text-muted">{i + 1}</span>
            <span className={`truncate ${d.isMine ? "font-semibold text-ink" : "text-ink-2"}`}>
              {d.name}
            </span>
            <span className="h-3 overflow-hidden">
              <span
                className="block h-full rounded-r"
                style={{
                  width: `${Math.max(d.score, 1.5)}%`,
                  background: d.isMine ? "var(--accent)" : "var(--other)",
                }}
              />
            </span>
            <span className="num text-right text-xs text-ink">{d.score.toFixed(0)}</span>
          </Link>
          {hover === d.teamId && (
            <div
              role="tooltip"
              className="pointer-events-none absolute right-12 top-full z-10 mt-1 w-52 rounded-lg border border-line bg-surface p-2.5 text-xs shadow-lg"
            >
              <div className="mb-1.5 font-medium text-ink">{d.name}</div>
              {d.parts.map((p) => (
                <div key={p.label} className="flex justify-between text-ink-2">
                  <span>{p.label}</span>
                  <span className="num text-ink">{p.value.toFixed(0)}</span>
                </div>
              ))}
            </div>
          )}
        </li>
      ))}
    </ol>
  );
}

// ---------------------------------------------------------------------------
// Weekly scoring: every team as a thin gray line, my team emphasized in accent.
// Crosshair + tooltip lists all teams for the hovered week.

export type ScoreSeries = { teamId: number; name: string; isMine: boolean; points: { week: number; points: number }[] };

const W = 960;
const H = 260;
const M = { top: 12, right: 16, bottom: 28, left: 40 };

function niceTicks(max: number, count = 4) {
  const step = Math.pow(10, Math.floor(Math.log10(max / count)));
  const err = max / count / step;
  const nice = step * (err >= 5 ? 10 : err >= 2 ? 5 : err >= 1 ? 2 : 1);
  const ticks = [];
  for (let v = 0; v <= max + nice / 2; v += nice) ticks.push(v);
  return ticks;
}

export function WeeklyScores({ series }: { series: ScoreSeries[] }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoverWeek, setHoverWeek] = useState<number | null>(null);

  const { weeks, ticks, x, y, leagueAvg } = useMemo(() => {
    const weeks = [...new Set(series.flatMap((s) => s.points.map((p) => p.week)))].sort((a, b) => a - b);
    const max = Math.max(1, ...series.flatMap((s) => s.points.map((p) => p.points)));
    const ticks = niceTicks(max);
    const top = ticks[ticks.length - 1];
    const x = (w: number) =>
      weeks.length < 2
        ? M.left + (W - M.left - M.right) / 2
        : M.left + ((w - weeks[0]) / (weeks[weeks.length - 1] - weeks[0])) * (W - M.left - M.right);
    const y = (v: number) => M.top + (1 - v / top) * (H - M.top - M.bottom);
    const leagueAvg = new Map(
      weeks.map((w) => {
        const vals = series.flatMap((s) => s.points.filter((p) => p.week === w).map((p) => p.points));
        return [w, vals.reduce((a, b) => a + b, 0) / Math.max(vals.length, 1)];
      }),
    );
    return { weeks, ticks, x, y, leagueAvg };
  }, [series]);

  if (weeks.length === 0) {
    return <p className="py-10 text-center text-sm text-muted">No completed weeks yet.</p>;
  }

  const ordered = [...series].sort((a, b) => Number(a.isMine) - Number(b.isMine)); // mine drawn last
  const path = (s: ScoreSeries) =>
    s.points
      .slice()
      .sort((a, b) => a.week - b.week)
      .map((p, i) => `${i ? "L" : "M"}${x(p.week).toFixed(1)},${y(p.points).toFixed(1)}`)
      .join("");

  function onMove(e: React.PointerEvent) {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * W;
    let best = weeks[0];
    for (const w of weeks) if (Math.abs(x(w) - px) < Math.abs(x(best) - px)) best = w;
    setHoverWeek(best);
  }

  const mine = series.find((s) => s.isMine);
  const tooltipRows =
    hoverWeek == null
      ? []
      : series
          .map((s) => ({ s, p: s.points.find((p) => p.week === hoverWeek)?.points }))
          .filter((r) => r.p != null)
          .sort((a, b) => b.p! - a.p!);
  const tipLeftPct = hoverWeek == null ? 0 : (x(hoverWeek) / W) * 100;

  return (
    <div className="relative">
      <div className="mb-2 flex flex-wrap gap-4 text-xs text-ink-2">
        {mine && (
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-0.5 w-4 rounded" style={{ background: "var(--accent)" }} />
            {mine.name}
          </span>
        )}
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 rounded" style={{ background: "var(--other)" }} />
          Rest of league
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 rounded border-t border-dotted" style={{ borderColor: "var(--ink-2)" }} />
          League average
        </span>
      </div>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="w-full touch-none select-none"
        onPointerMove={onMove}
        onPointerLeave={() => setHoverWeek(null)}
        role="img"
        aria-label="Points scored by each team per week"
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)} stroke="var(--grid)" strokeWidth={1} />
            <text x={M.left - 8} y={y(t)} dy="0.32em" textAnchor="end" fontSize={11} fill="var(--muted)" className="num">
              {t}
            </text>
          </g>
        ))}
        {weeks.map((w) => (
          <text key={w} x={x(w)} y={H - 8} textAnchor="middle" fontSize={11} fill="var(--muted)" className="num">
            W{w}
          </text>
        ))}
        <path
          d={weeks.map((w, i) => `${i ? "L" : "M"}${x(w)},${y(leagueAvg.get(w)!)}`).join("")}
          fill="none"
          stroke="var(--ink-2)"
          strokeWidth={1.5}
          strokeDasharray="2 3"
        />
        {ordered.map((s) => (
          <path
            key={s.teamId}
            d={path(s)}
            fill="none"
            stroke={s.isMine ? "var(--accent)" : "var(--other)"}
            strokeWidth={s.isMine ? 2.5 : 1.5}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ))}
        {mine?.points.map((p) => (
          <circle key={p.week} cx={x(p.week)} cy={y(p.points)} r={4} fill="var(--accent)" stroke="var(--surface)" strokeWidth={2} />
        ))}
        {hoverWeek != null && (
          <line x1={x(hoverWeek)} x2={x(hoverWeek)} y1={M.top} y2={H - M.bottom} stroke="var(--axis)" strokeWidth={1} />
        )}
      </svg>
      {hoverWeek != null && (
        <div
          role="tooltip"
          className="pointer-events-none absolute top-8 z-10 w-52 rounded-lg border border-line bg-surface p-2.5 text-xs shadow-lg"
          style={
            tipLeftPct > 55
              ? { right: `${100 - tipLeftPct + 2}%` }
              : { left: `${tipLeftPct + 2}%` }
          }
        >
          <div className="mb-1.5 flex justify-between font-medium text-ink">
            <span>Week {hoverWeek}</span>
            <span className="num text-muted">avg {leagueAvg.get(hoverWeek)!.toFixed(1)}</span>
          </div>
          {tooltipRows.map(({ s, p }) => (
            <div key={s.teamId} className={`flex justify-between gap-2 ${s.isMine ? "font-semibold text-ink" : "text-ink-2"}`}>
              <span className="flex min-w-0 items-center gap-1.5">
                <span className="inline-block size-2 shrink-0 rounded-full" style={{ background: s.isMine ? "var(--accent)" : "var(--other)" }} />
                <span className="truncate">{s.name}</span>
              </span>
              <span className="num text-ink">{p!.toFixed(1)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
