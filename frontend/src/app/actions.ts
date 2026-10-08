"use server";

import { refresh } from "next/cache";
import { redirect } from "next/navigation";
import { clerkClient } from "@clerk/nextjs/server";
import { ApiError, api, type TradeAnalysis } from "@/lib/api";
import { currentUserId } from "@/lib/auth";

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

export async function saveEspnCookiesAction(_: ActionState, form: FormData): Promise<ActionState> {
  const s2 = String(form.get("espn_s2") ?? "").trim();
  const swid = String(form.get("swid") ?? "").trim();
  if (!s2 || !swid) return { error: "Paste both cookie values." };
  try {
    await api.saveEspnCookies(s2, swid);
  } catch (e) {
    return { error: e instanceof ApiError ? e.message : "Couldn't save your cookies." };
  }
  refresh();
  return { ok: true };
}

export async function deleteEspnCookiesAction(): Promise<void> {
  await api.deleteEspnCookies();
  refresh();
}

export async function pickTeamAction(leagueId: number, teamId: number | null): Promise<ActionState> {
  try {
    await api.pickTeam(leagueId, teamId);
  } catch (e) {
    return { error: e instanceof ApiError ? e.message : "Couldn't save your team." };
  }
  refresh();
  return { ok: true };
}

/** Deletes this app's data (leagues, cookies, chats), then the Clerk account itself. */
export async function deleteAccountAction(): Promise<ActionState> {
  const userId = await currentUserId();
  if (!userId) return { error: "You're not signed in." };
  try {
    await api.deleteAccount();
    await (await clerkClient()).users.deleteUser(userId);
  } catch (e) {
    return { error: e instanceof ApiError ? e.message : "Couldn't delete your account." };
  }
  redirect("/");
}
