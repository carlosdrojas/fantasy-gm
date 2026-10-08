// Streams a chat turn from the backend to the browser (server-sent events passthrough).
import { API_URL } from "@/lib/api";

export async function POST(request: Request, ctx: RouteContext<"/api/leagues/[id]/chat">) {
  const { id } = await ctx.params;
  if (!/^\d+$/.test(id)) return Response.json({ detail: "Bad league id" }, { status: 400 });
  let upstream: Response;
  try {
    upstream = await fetch(`${API_URL}/api/leagues/${id}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: await request.text(),
      signal: request.signal,
    });
  } catch {
    return Response.json({ detail: `Can't reach the backend at ${API_URL}.` }, { status: 503 });
  }
  if (!upstream.ok || !upstream.body) {
    const detail = await upstream.json().then((b) => b.detail).catch(() => upstream.statusText);
    return Response.json({ detail }, { status: upstream.status });
  }
  return new Response(upstream.body, {
    headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" },
  });
}
