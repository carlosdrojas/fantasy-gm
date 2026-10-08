"use client";

export default function LeagueError({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <div className="mx-auto max-w-xl rounded-xl border border-line bg-surface p-6 text-sm">
      <p className="font-semibold text-critical">Something went wrong loading this page</p>
      <p className="mt-2 text-ink-2">{error.message}</p>
      <button onClick={reset} className="mt-4 text-link underline">
        Try again
      </button>
    </div>
  );
}
