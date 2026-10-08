"use client";

import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { chatHistoryAction } from "@/app/actions";

type Msg = { role: "user" | "assistant"; text: string; tools?: string[]; error?: string };

const SUGGESTIONS = [
  "Who should I start this week?",
  "Find me a trade that fixes my weakest position.",
  "Which waiver pickups are worth it, and who do I drop?",
  "How likely am I to make the playoffs, and what would change that?",
];

const storageKey = (leagueId: number) => `fgm-chat-${leagueId}`;

function readConversation(leagueId: number): string | null {
  try {
    return localStorage.getItem(storageKey(leagueId));
  } catch {
    return null;
  }
}

function writeConversation(leagueId: number, id: string | null) {
  try {
    if (id) localStorage.setItem(storageKey(leagueId), id);
    else localStorage.removeItem(storageKey(leagueId));
  } catch {}
}

export function Chat({ leagueId }: { leagueId: number }) {
  const [messages, setMessages] = useState<Msg[]>([]);
  // Only read on the client; the id isn't rendered, so server/client markup still match.
  const [conversationId, setConversationId] = useState<string | null>(() =>
    typeof window === "undefined" ? null : readConversation(leagueId),
  );
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string>();
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const id = readConversation(leagueId);
    if (id) chatHistoryAction(leagueId, id).then((h) => setMessages(h));
  }, [leagueId]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [messages, status]);

  function updateLast(fn: (m: Msg) => Msg) {
    setMessages((ms) => [...ms.slice(0, -1), fn(ms[ms.length - 1])]);
  }

  async function send(text: string) {
    const message = text.trim();
    if (!message || busy) return;
    setInput("");
    setBusy(true);
    setStatus("Thinking…");
    setMessages((ms) => [...ms, { role: "user", text: message }, { role: "assistant", text: "", tools: [] }]);
    try {
      const res = await fetch(`/api/leagues/${leagueId}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, conversation_id: conversationId }),
      });
      if (!res.ok || !res.body) {
        const detail = await res.json().then((b) => b.detail).catch(() => res.statusText);
        updateLast((m) => ({ ...m, error: String(detail) }));
        return;
      }
      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += value;
        const parts = buf.split("\n\n");
        buf = parts.pop() ?? "";
        for (const part of parts) {
          const line = part.split("\n").find((l) => l.startsWith("data: "));
          if (!line) continue;
          const ev = JSON.parse(line.slice(6));
          if (ev.type === "start") {
            setConversationId(ev.conversation_id);
            writeConversation(leagueId, ev.conversation_id);
          } else if (ev.type === "text") {
            setStatus(undefined);
            updateLast((m) => ({ ...m, text: m.text + ev.text }));
          } else if (ev.type === "tool") {
            setStatus(`${ev.label}…`);
            updateLast((m) => ({ ...m, tools: [...(m.tools ?? []), ev.label] }));
          } else if (ev.type === "error") {
            updateLast((m) => ({ ...m, error: ev.message }));
          }
        }
      }
    } catch {
      updateLast((m) => ({ ...m, error: "Connection lost." }));
    } finally {
      setBusy(false);
      setStatus(undefined);
    }
  }

  function newChat() {
    writeConversation(leagueId, null);
    setConversationId(null);
    setMessages([]);
  }

  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted">
          Claude reads your league&apos;s synced data (rosters, waivers, trades, odds) to answer. It can&apos;t make moves on
          ESPN.
        </p>
        {messages.length > 0 && (
          <button onClick={newChat} disabled={busy} className="text-xs text-link hover:underline disabled:opacity-50">
            New chat
          </button>
        )}
      </div>

      {messages.length === 0 && (
        <div className="grid gap-2 sm:grid-cols-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => send(s)}
              className="rounded-lg border border-line bg-surface p-3 text-left text-sm text-ink-2 hover:bg-surface-2 hover:text-ink"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      <div className="space-y-4">
        {messages.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="ml-auto max-w-[85%] rounded-2xl bg-accent px-4 py-2 text-sm text-accent-ink">
              {m.text}
            </div>
          ) : (
            <div key={i} className="rounded-xl border border-line bg-surface px-4 py-3 text-sm">
              {m.tools && m.tools.length > 0 && (
                <div className="mb-2 flex flex-wrap gap-1">
                  {[...new Set(m.tools)].map((t) => (
                    <span key={t} className="rounded-full bg-surface-2 px-2 py-0.5 text-[11px] text-muted">
                      {t}
                    </span>
                  ))}
                </div>
              )}
              {m.text && (
                <div className="chat-md text-ink">
                  <Markdown remarkPlugins={[remarkGfm]}>{m.text}</Markdown>
                </div>
              )}
              {i === messages.length - 1 && status && <p className="text-xs text-muted">{status}</p>}
              {m.error && <p className="mt-2 text-xs text-critical">● {m.error}</p>}
            </div>
          ),
        )}
        <div ref={bottom} />
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
        className="sticky bottom-4 flex gap-2 rounded-xl border border-line bg-surface p-2 shadow-lg focus-within:border-accent"
      >
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(input);
            }
          }}
          rows={1}
          placeholder="Ask about your league…"
          className="flex-1 resize-none bg-transparent px-2 py-1.5 text-sm text-ink outline-none placeholder:text-muted"
        />
        <button
          disabled={busy || !input.trim()}
          className="rounded-lg bg-accent px-3 text-sm font-semibold text-accent-ink disabled:bg-surface-2 disabled:text-muted"
        >
          Send
        </button>
      </form>
    </div>
  );
}
