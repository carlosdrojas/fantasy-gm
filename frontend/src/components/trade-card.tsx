import { PlayerName } from "@/components/ui";
import type { PlayerRow, Trade } from "@/lib/api";

export function acceptanceLabel(a: number) {
  return a >= 0.6 ? "Likely" : a >= 0.35 ? "Possible" : "Long shot";
}

const VERDICT: Record<Trade["verdict"], string> = {
  win_win: "Helps both teams",
  neutral_for_them: "Even for them",
  they_lose: "Hurts their lineup",
  bad_for_you: "Hurts your lineup",
};

export function Gain({ value, suffix = "/wk" }: { value: number; suffix?: string }) {
  const cls = value > 0.05 ? "text-good" : value < -0.05 ? "text-critical" : "text-ink-2";
  return (
    <span className={`num font-semibold ${cls}`}>
      {value > 0 ? "+" : ""}
      {value.toFixed(1)}
      <span className="text-xs font-normal text-muted">{suffix}</span>
    </span>
  );
}

export function AcceptanceMeter({ value }: { value: number }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="h-1.5 w-16 overflow-hidden rounded-full bg-surface-2">
        <span className="block h-full rounded-full bg-accent" style={{ width: `${Math.round(value * 100)}%` }} />
      </span>
      <span className="num text-ink-2">
        {Math.round(value * 100)}% · {acceptanceLabel(value)}
      </span>
    </div>
  );
}

function TradePlayer({ p }: { p: PlayerRow }) {
  return (
    <div className={p.locked ? "opacity-60" : undefined}>
      <PlayerName p={p} /> <span className="num text-xs text-ink-2">{p.value.per_game.toFixed(1)}</span>
      {p.locked && (
        <span className="ml-1.5 text-xs text-muted" title="His game this week has started. ESPN locks him until the week ends.">
          played this week
        </span>
      )}
    </div>
  );
}

export function TradeCard({ trade, partnerName }: { trade: Trade; partnerName: string }) {
  return (
    <div className="rounded-lg border border-line p-3.5">
      <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium text-ink">with {partnerName}</span>
        <AcceptanceMeter value={trade.acceptance} />
      </div>
      <div className="grid gap-3 text-sm sm:grid-cols-2">
        <div>
          <div className="mb-1 text-xs text-muted">You send</div>
          {trade.give.map((p) => (
            <TradePlayer key={p.id} p={p} />
          ))}
        </div>
        <div>
          <div className="mb-1 text-xs text-muted">You get</div>
          {trade.get.map((p) => (
            <TradePlayer key={p.id} p={p} />
          ))}
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 border-t border-line pt-2.5 text-xs text-ink-2">
        <span>
          You <Gain value={trade.my_gain} />
        </span>
        <span>
          Them <Gain value={trade.their_gain} />
        </span>
        <span title="Points per game you receive minus what you send, by player value alone">
          Raw value {trade.raw_value_edge > 0 ? "+" : ""}
          {trade.raw_value_edge.toFixed(1)}
        </span>
        <span className="text-muted">{VERDICT[trade.verdict]}</span>
        {!trade.tradeable_now && <span className="text-link">Can be made after this week&apos;s games</span>}
        {trade.my_drops.length > 0 && (
          <span className="text-muted">You&apos;d drop {trade.my_drops.map((p) => p.name).join(", ")}</span>
        )}
      </div>
    </div>
  );
}
