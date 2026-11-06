import { getRuntime } from "@/lib/runtime";
import { forbiddenOrigin, json, sameOrigin, sessionIdFrom } from "@/lib/http";
import { clearSessionCookie } from "@/lib/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const rt = await getRuntime();
  if (!sameOrigin(request, rt)) return forbiddenOrigin();
  const sessionId = sessionIdFrom(request, rt);
  if (sessionId) {
    const r = await rt.service.revokeSession(sessionId, sessionId);
    // A paused session cannot act, but it can still end itself.
    if (!r.ok) await rt.store.revokeSession(sessionId, Date.now());
  }
  return json({ ok: true }, 200, { "Set-Cookie": clearSessionCookie(rt.config.appOrigin) });
}
