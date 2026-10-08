"use server";

import { refresh } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, api, type TradeAnalysis } from "@/lib/api";

export type ActionState = { error?: string; ok?: boolean };

export async function addLeagueAction(_: ActionState, form: FormData): Promise<ActionState> {
  const leagueId = String(form.get("league_id") ?? "").trim();
  const season = Number(form.get("season"));
  if (!/^\d+$/.test(leagueId)) return { error: "League ID must be a number (from leagueId= in the URL)." };
  let id: number;
  try {
    ({ id } = await api.addLeague(leagueId, season));
  } catch (e) {
    return { error: e instanceof ApiError ? e.message : "Something went wrong." };
  }
  redirect(`/leagues/${id}`);
}

export async function syncLeagueAction(leagueId: number): Promise<ActionState> {
  try {
    await api.sync(leagueId);
  } catch (e) {
    return { error: e instanceof ApiError ? e.message : "Sync failed." };
  }
  refresh();
  return { ok: true };
}

export async function deleteLeagueAction(leagueId: number): Promise<void> {
  await api.deleteLeague(leagueId);
  redirect("/");
}

export async function analyzeTradeAction(
  leagueId: number,
  body: { partner_team_id: number; give: number[]; get: number[] },
): Promise<{ result?: TradeAnalysis; error?: string }> {
  try {
    return { result: await api.analyzeTrade(leagueId, body) };
  } catch (e) {
    return { error: e instanceof ApiError ? e.message : "Couldn't analyze that trade." };
  }
}

export async function chatHistoryAction(
  leagueId: number,
  conversationId: string,
): Promise<{ role: "user" | "assistant"; text: string }[]> {
  try {
    return await api.chatHistory(leagueId, conversationId);
  } catch {
    return [];
  }
}

export async function teamRosterAction(leagueId: number, teamId: number) {
  try {
    return (await api.team(leagueId, teamId)).roster;
  } catch {
    return [];
  }
}

export async function quickAnswerAction(
  leagueId: number,
  question: string,
): Promise<{ answer?: string; error?: string }> {
  try {
    return { answer: (await api.quickAnswer(leagueId, question)).answer };
  } catch (e) {
    return { error: e instanceof ApiError ? e.message : "Couldn't answer that." };
  }
}
