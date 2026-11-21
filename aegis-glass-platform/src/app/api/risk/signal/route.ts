import { z } from "zod";
import { getRuntime } from "@/lib/runtime";
import { CLIENT_SIGNALS } from "@/lib/risk";
import { forbiddenOrigin, json, rateLimited, refusal, sameOrigin, sessionIdFrom, tooMany } from "@/lib/http";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const Body = z.object({ viewId: z.string().uuid(), kind: z.enum(CLIENT_SIGNALS) });

/** Browser-reported signal. Untrusted: it can raise a session's risk, never lower it. */
export async function POST(request: Request) {
  const rt = await getRuntime();
  if (!sameOrigin(request, rt)) return forbiddenOrigin();
  const sessionId = sessionIdFrom(request, rt);
  if (!sessionId) return json({ error: "session_required" }, 401);
  if (rateLimited(`signal:${sessionId}`, 60)) return tooMany();
  const parsed = Body.safeParse(await request.json().catch(() => null));
  if (!parsed.success) return json({ error: "invalid_request" }, 400);
  const r = await rt.service.recordClientSignal(sessionId, parsed.data.viewId, parsed.data.kind);
  return r.ok ? json({ riskState: r.riskState, actions: r.actions }) : refusal(r);
}
