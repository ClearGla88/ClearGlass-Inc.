// Revoke a session: your own (sign out) or, for a tenant admin, any session in
// the same tenant. Takes effect on the next capability or media request.

import { json, mutationGuard, principalFrom, readJson, runtimeOr503 } from "../../../../lib/http.ts";
import { SESSION_COOKIE } from "../../../../lib/session.ts";

export async function POST(request: Request): Promise<Response> {
  const blocked = mutationGuard(request);
  if (blocked) return blocked;
  const rt = await runtimeOr503();
  if (rt instanceof Response) return rt;
  const p = principalFrom(request, rt);
  if (!p) return json({ error: "unauthenticated" }, 401);

  const body = await readJson<{ sessionId?: unknown; reason?: unknown }>(request);
  const target = typeof body?.sessionId === "string" && /^[A-Za-z0-9_-]{8,64}$/.test(body.sessionId) ? body.sessionId : p.sessionId;
  const reason = typeof body?.reason === "string" ? body.reason : target === p.sessionId ? "signed out" : "revoked by admin";

  const result = await rt.service.revokeSession(p, target, reason);
  if (!result.ok) return json({ error: result.error }, 403);
  const headers: Record<string, string> = {};
  if (target === p.sessionId) headers["Set-Cookie"] = `${SESSION_COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0`;
  return json({ ok: true }, 200, headers);
}
