import Link from "next/link";
import { POSITIONS, type Positions } from "@/lib/api";

// Diverging scale on league z-score: red (weak) <- gray (average) -> blue (strong).
function cellStyle(z: number): React.CSSProperties {
  const mag = Math.abs(z);
  const pct = mag < 0.5 ? 0 : mag < 1 ? 30 : mag < 1.5 ? 55 : 80;
  if (pct === 0) return { background: "var(--mid)", color: "var(--ink)" };
  const pole = z > 0 ? "var(--pos)" : "var(--neg)";
  return {
    background: `color-mix(in oklab, ${pole} ${pct}%, var(--mid))`,
    color: pct >= 55 ? "#fff" : "var(--ink)",
  };
}

export function PositionHeatmap({
  rows,
}: {
  rows: { teamId: number; name: string; href: string; isMine: boolean; positions: Positions }[];
}) {
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full border-separate border-spacing-0.5 text-xs">
          <thead>
            <tr className="text-muted">
              <th className="px-2 py-1 text-left font-normal">Team</th>
              {POSITIONS.map((p) => (
                <th key={p} className="w-16 px-1 py-1 font-normal">
                  {p}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.teamId}>
                <td className="max-w-40 truncate px-2 py-1">
                  <Link
                    href={r.href}
                    className={r.isMine ? "font-semibold text-ink" : "text-ink-2 hover:text-ink"}
                  >
                    {r.name}
                  </Link>
                </td>
                {POSITIONS.map((pos) => {
                  const c = r.positions[pos];
                  if (!c) return <td key={pos} />;
                  return (
                    <td
                      key={pos}
                      title={`${r.name} ${pos}: rank ${c.rank}, starters ${c.starters.toFixed(1)} pts/g, best backup ${c.depth.toFixed(1)}`}
                      className="num rounded px-1 py-1.5 text-center"
                      style={cellStyle(c.z)}
                    >
                      #{c.rank}
                      {c.label !== "ok" && (
                        <span className="ml-1 text-[10px] font-semibold opacity-90">
                          {c.label === "need" ? "Need" : "Deep"}
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex items-center gap-2 text-xs text-muted">
        <span>Weaker</span>
        {[-2, -1.2, -0.7, 0, 0.7, 1.2, 2].map((z) => (
          <span key={z} className="h-3 w-6 rounded-sm" style={{ background: cellStyle(z).background }} />
        ))}
        <span>Stronger than league average</span>
      </div>
    </div>
  );
}
