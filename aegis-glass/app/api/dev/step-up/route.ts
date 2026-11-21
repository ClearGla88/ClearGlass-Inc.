// Demo-mode step-up. Stands in for a passkey (WebAuthn) re-authentication:
// same session ID, so risk state carries over, but a stronger, fresher
// authentication level. Production routes this through the identity provider.

import { json, mutationGuard, principalFrom, runtimeOr503 } from "../../../../lib/http.ts";
import { issueSessionCookie, SESSION_TTL_SECONDS, sessionCookieHeader } from "../../../../lib/session.ts";

export async function POST(request: Request): Promise<Response> {
  const blocked = mutationGuard(request);
  if (blocked) return blocked;
  const rt = await runtimeOr503();
  if (rt instanceof Response) return rt;
  if (rt.config.mode !== "demo") return json({ error: "not_found" }, 404);

  const p = principalFrom(request, rt);
  if (!p) return json({ error: "unauthenticated" }, 401);
  if (await rt.service.isSessionRevoked(p.sessionId)) return json({ error: "session_revoked" }, 401);

  const now = Math.floor(Date.now() / 1000);
  const stepped = { ...p, authLevel: "phishing_resistant" as const, authTime: now };
  return json({ ok: true }, 200, {
    "Set-Cookie": sessionCookieHeader(issueSessionCookie(rt.config.sessionKey, stepped, now, SESSION_TTL_SECONDS)),
  });
}
