"use client";

import { useActionState, useState, useTransition } from "react";
import {
  type ActionState,
  deleteAccountAction,
  deleteEspnCookiesAction,
  deleteLeagueAction,
  saveEspnCookiesAction,
} from "@/app/actions";

const input = "w-full rounded-md border border-line bg-page px-2.5 py-1.5 font-mono text-xs text-ink";

export function EspnCookiesForm({ hasCookies }: { hasCookies: boolean }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(saveEspnCookiesAction, {});
  return (
    <form action={action} className="space-y-3">
      <label className="block space-y-1 text-xs text-ink-2">
        <span>espn_s2</span>
        <input name="espn_s2" required autoComplete="off" spellCheck={false} placeholder="AEB…" className={input} />
      </label>
      <label className="block space-y-1 text-xs text-ink-2">
        <span>SWID (keep the curly braces)</span>
        <input
          name="swid"
          required
          autoComplete="off"
          spellCheck={false}
          placeholder="{XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}"
          className={input}
        />
      </label>
      <div className="flex flex-wrap items-center gap-3">
        <button
          disabled={pending}
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-accent-ink disabled:opacity-60"
        >
          {pending ? "Saving…" : hasCookies ? "Replace cookies" : "Save cookies"}
        </button>
        {state.ok && <span className="text-sm text-good">Saved. They&apos;ll be checked on the next sync.</span>}
        {state.error && <span className="text-sm text-critical">{state.error}</span>}
      </div>
    </form>
  );
}

export function RemoveCookiesButton() {
  const [pending, start] = useTransition();
  return (
    <button
      disabled={pending}
      onClick={() => start(() => deleteEspnCookiesAction())}
      className="text-xs text-link hover:underline disabled:opacity-60"
    >
      {pending ? "Removing…" : "Remove my cookies"}
    </button>
  );
}

export function RemoveLeagueButton({ leagueId, name }: { leagueId: number; name: string }) {
  const [pending, start] = useTransition();
  return (
    <button
      disabled={pending}
      onClick={() => {
        if (confirm(`Remove ${name} from your account?`)) start(() => deleteLeagueAction(leagueId));
      }}
      className="text-xs text-link hover:underline disabled:opacity-60"
    >
      {pending ? "Removing…" : "Remove"}
    </button>
  );
}

export function DeleteAccountButton() {
  const [pending, start] = useTransition();
  const [error, setError] = useState<string>();
  return (
    <div className="space-y-1">
      <button
        disabled={pending}
        onClick={() => {
          if (!confirm("Delete your account, leagues, ESPN cookies and chats? This can't be undone.")) return;
          start(async () => setError((await deleteAccountAction()).error));
        }}
        className="rounded-md border border-critical px-3 py-1.5 text-sm text-critical hover:bg-surface-2 disabled:opacity-60"
      >
        {pending ? "Deleting…" : "Delete my account"}
      </button>
      {error && <p className="text-xs text-critical">{error}</p>}
    </div>
  );
}
