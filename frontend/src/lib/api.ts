// Typed client for the FastAPI backend. Server-side only (used by Server Components/Actions).
import "server-only";
import { cache } from "react";
import { authHeader } from "@/lib/auth";

export const API_URL = process.env.FGM_API_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    const headers = { ...(await authHeader()), ...(init?.headers as Record<string, string> | undefined) };
    res = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init, headers });
  } catch {
    throw new ApiError(503, `Can't reach the backend at ${API_URL}. Is \`fgm serve\` running?`);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {}
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export type Team = {
  id: number;
  external_id: string;
  name: string;
  abbrev: string | null;
  owner_name: string | null;
  logo_url: string | null;
  wins: number;
  losses: number;
  ties: number;
  points_for: number;
  points_against: number;
  playoff_seed: number | null;
  waiver_rank: number | null;
  faab_spent: number | null;
};

export type LeagueSettings = {
  lineup_slot_counts: Record<string, number>;
  scoring_type: string | null;
  reception_points: number;
  regular_season_weeks: number | null;
  playoff_team_count: number | null;
  uses_faab: boolean;
  faab_budget: number | null;
  team_count: number;
};

export type League = {
  id: number;
  platform: string;
  external_id: string;
  season: number;
  name: string | null;
  current_week: number | null;
  final_regular_week: number | null;
  my_team_id: number | null;
  is_demo: boolean;
  settings: LeagueSettings;
  last_synced_at: string | null;
  live_updated_at: string | null;
};

export type Matchup = {
  id: number;
  week: number;
  home_team_id: number;
  away_team_id: number | null;
  home_points: number | null;
  away_points: number | null;
  home_projected: number | null;
  away_projected: number | null;
  winner: string;
  is_playoff: boolean;
  home_win_prob: number | null;
  away_win_prob: number | null;
};

/** How many of a team's starters have played, are playing, or have yet to play this week. */
export type LineupStatus = { played: number; playing: number; yet_to_play: number };

export type ProGame = {
  home_team: string;
  away_team: string;
  home_score: number | null;
  away_score: number | null;
  state: "pre" | "in" | "post";
  detail: string;
  kickoff: string | null;
};

export type LiveStatus = {
  updated_at: string | null;
  /** True while any NFL game is on or about to start: the dashboard auto-refreshes. */
  active: boolean;
  games: ProGame[];
};

/** A player's NFL game this week, from his team's side. */
export type PlayerGame =
  | { state: "bye" }
  | { state: "none" }
  | {
      state: "pre" | "in" | "post";
      detail: string;
      kickoff: string | null;
      opponent: string;
      is_home: boolean;
      team_score: number | null;
      opponent_score: number | null;
    };

export type LeagueOverview = League & {
  /** Opening a stale league started a refresh from ESPN. */
  syncing: boolean;
  teams: Team[];
  current_matchups: (Matchup & {
    home_lineup: LineupStatus | null;
    away_lineup: LineupStatus | null;
  })[];
  live: LiveStatus;
  last_sync: {
    status: string;
    started_at: string;
    finished_at: string | null;
    error: string | null;
  } | null;
};

export type PowerRow = {
  team_id: number;
  rank: number;
  power_score: number;
  components: { all_play: number; recent_form: number; roster_strength: number };
  roster_strength: number;
  all_play: { wins: number; losses: number; ties: number; pct: number };
  actual_wins: number;
  expected_wins: number;
  luck: number;
  weekly_points: { week: number; points: number }[];
  record: { wins: number; losses: number; ties: number };
  points_for: number;
};

export type PositionCell = {
  starters: number;
  depth: number;
  score: number;
  z: number;
  rank: number;
  label: "need" | "surplus" | "ok";
};
export const POSITIONS = ["QB", "RB", "WR", "TE", "K", "D/ST"] as const;
export type Positions = Record<string, PositionCell>;

export type PlayerRow = {
  id: number;
  external_id: string;
  name: string;
  position: string;
  pro_team: string | null;
  injury_status: string | null;
  slot: string | null;
  team_id: number | null;
  percent_owned: number | null;
  percent_owned_change: number | null;
  value: {
    per_game: number;
    projected_per_game: number | null;
    recent_avg: number | null;
    this_week_projection: number | null;
    this_week_actual: number | null;
    trend: number | null;
  };
  game: PlayerGame | null;
  /** The player's game this week has started: ESPN won't let him be traded until the week ends. */
  locked: boolean;
};

export type TeamDetail = {
  team: Team;
  roster: PlayerRow[];
  optimal_lineup: Record<string, number[]>;
  lineup_changes: { start: number[]; sit: number[] };
  positions: Positions;
};

export type WaiverSuggestion = {
  player: PlayerRow;
  ros_gain: number;
  week_gain: number;
  drop: PlayerRow | null;
  score: number;
};

export type TransactionRow = {
  id: number;
  type: string;
  status: string;
  team_id: number | null;
  week: number | null;
  bid_amount: number | null;
  proposed_at: string | null;
  processed_at: string | null;
  items: {
    type: string;
    player_id: number | null;
    from_team_id: number | null;
    to_team_id: number | null;
    player: { name: string; position: string } | null;
  }[];
};

export type TeamOdds = {
  playoff_pct: number;
  bye_pct: number | null;
  first_seed_pct: number;
  champion_pct: number;
  avg_wins: number;
  avg_seed: number;
  weekly_mean: number;
};

export type OddsResponse = {
  teams: Record<string, TeamOdds>;
  sims: number;
  playoff_teams: number | null;
  remaining_weeks: number[];
  weekly_sd: number;
};

export type Trade = {
  partner_team_id: number;
  give: PlayerRow[];
  get: PlayerRow[];
  my_gain: number;
  their_gain: number;
  my_lineup_gain: number;
  their_lineup_gain: number;
  raw_value_edge: number;
  my_drops: PlayerRow[];
  their_drops: PlayerRow[];
  acceptance: number;
  verdict: "win_win" | "neutral_for_them" | "they_lose" | "bad_for_you";
  /** False when a player involved has already played this week. */
  tradeable_now: boolean;
};

export type TradeAnalysis = Trade & {
  odds: Record<string, { before: TeamOdds; after: TeamOdds }>;
};

export type TradeSort = "balanced" | "gain" | "likely";

export type Health = {
  ok: boolean;
  demo_mode: boolean;
  accounts_enabled: boolean;
  assistant_needs_user_key: boolean;
  espn_auth_configured: boolean;
};

export type EspnStatus = { status: "unverified" | "ok" | "expired"; updated_at: string; checked_at: string | null };

export type Me =
  | { signed_in: false; accounts_enabled: boolean }
  | {
      signed_in: true;
      accounts_enabled: true;
      espn: EspnStatus | null;
      leagues: number;
      max_leagues: number;
      can_store_cookies: boolean;
    };

export type QuickQuestion = { id: string; label: string };
export type QuickAnswer = { question: string; label: string; answer: string; source: "rules" };

/** Backend health, once per request (the root layout and pages both need demo_mode). */
export const getHealth = cache(() => request<Health>("/api/health"));

export const api = {
  health: () => getHealth(),
  me: () => request<Me>("/api/me"),
  saveEspnCookies: (espn_s2: string, swid: string) =>
    request<{ espn: EspnStatus }>("/api/me/espn", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ espn_s2, swid }),
    }),
  deleteEspnCookies: () => request<void>("/api/me/espn", { method: "DELETE" }),
  deleteAccount: () => request<void>("/api/me", { method: "DELETE" }),
  pickTeam: (id: number, teamId: number | null) =>
    request<{ my_team_id: number | null }>(`/api/leagues/${id}/my-team`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ team_id: teamId }),
    }),
  quickQuestions: () => request<QuickQuestion[]>("/api/assistant/questions"),
  quickAnswer: (id: number, question: string) =>
    request<QuickAnswer>(`/api/leagues/${id}/assistant/quick`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    }),
  leagues: () => request<(League & { my_team: Team | null })[]>("/api/leagues"),
  league: (id: number) => request<LeagueOverview>(`/api/leagues/${id}`),
  power: (id: number) => request<PowerRow[]>(`/api/leagues/${id}/power`),
  positions: (id: number) =>
    request<{ teams: Record<string, Positions> }>(`/api/leagues/${id}/positions`),
  team: (id: number, teamId: number) => request<TeamDetail>(`/api/leagues/${id}/teams/${teamId}`),
  waivers: (id: number, teamId?: number) =>
    request<{ team_id: number; suggestions: WaiverSuggestion[] }>(
      `/api/leagues/${id}/waivers${teamId ? `?team_id=${teamId}` : ""}`,
    ),
  freeAgents: (id: number, position?: string) =>
    request<PlayerRow[]>(
      `/api/leagues/${id}/free-agents${position ? `?position=${encodeURIComponent(position)}` : ""}`,
    ),
  odds: (id: number) => request<OddsResponse>(`/api/leagues/${id}/odds`),
  trades: (id: number, opts: { partnerId?: number; sort?: TradeSort; tradeableNow?: boolean } = {}) => {
    const q = new URLSearchParams();
    if (opts.tradeableNow) q.set("tradeable_now", "true");
    if (opts.partnerId) q.set("partner_id", String(opts.partnerId));
    if (opts.sort) q.set("sort", opts.sort);
    return request<{ team_id: number; trades: Trade[] }>(`/api/leagues/${id}/trades?${q}`);
  },
  analyzeTrade: (id: number, body: { partner_team_id: number; give: number[]; get: number[] }) =>
    request<TradeAnalysis>(`/api/leagues/${id}/trades/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  chatHistory: (id: number, conversationId: string) =>
    request<{ role: "user" | "assistant"; text: string }[]>(
      `/api/leagues/${id}/chat/${encodeURIComponent(conversationId)}`,
    ),
  transactions: (id: number) => request<TransactionRow[]>(`/api/leagues/${id}/transactions`),
  addLeague: (leagueId: string, season: number) =>
    request<{ id: number }>("/api/leagues", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ league_id: leagueId, season }),
    }),
  sync: (id: number) =>
    request<{ status: string }>(`/api/leagues/${id}/sync`, { method: "POST" }),
  deleteLeague: (id: number) => request<void>(`/api/leagues/${id}`, { method: "DELETE" }),
};
