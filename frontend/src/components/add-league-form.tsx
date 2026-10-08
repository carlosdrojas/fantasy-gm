"use client";

import { useActionState } from "react";
import { type ActionState, addLeagueAction } from "@/app/actions";

export function AddLeagueForm({ defaultSeason }: { defaultSeason: number }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(addLeagueAction, {});
  return (
    <form action={action} className="flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-1 text-xs text-ink-2">
        League ID
        <input
          name="league_id"
          required
          inputMode="numeric"
          placeholder="12345678"
          className="w-40 rounded-md border border-line bg-page px-2.5 py-1.5 text-sm text-ink"
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-ink-2">
        Season
        <input
          name="season"
          type="number"
          defaultValue={defaultSeason}
          className="w-24 rounded-md border border-line bg-page px-2.5 py-1.5 text-sm text-ink"
        />
      </label>
      <button
        disabled={pending}
        className="rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-accent-ink disabled:opacity-60"
      >
        {pending ? "Importing…" : "Add league"}
      </button>
      {state.error && <p className="basis-full text-sm text-critical">{state.error}</p>}
    </form>
  );
}
