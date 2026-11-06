import { getRuntime } from "@/lib/runtime";
import { forbiddenOrigin, json, refusal, sameOrigin, sessionIdFrom } from "@/lib/http";
import { sealSessionId, sessionCookie } from "@/lib/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// DEVELOPMENT ONLY. Simulates a passkey re-authentication: the old session is
// revoked and a new, phishing-resistant session is issued. In production this
// is the identity provider's step-up flow (OIDC prompt=login, acr_values).
export async function POST(request: Request) {
  const rt = await getRuntime();
  if (rt.config.env === "production" || !rt.config.devLogin) return json({ error: "not_found" }, 404);
  if (!sameOrigin(request, rt)) return forbiddenOrigin();
  const sessionId = sessionIdFrom(request, rt);
  const session = sessionId ? await rt.store.getSession(sessionId) : null;
  // A paused session may step up: re-authenticating is how a person clears a pause.
  if (!session || session.revokedAt !== null || session.expiresAt <= Date.now()) return refusal({ ok: false, httpStatus: 401, reasons: ["session_invalid"] });
  await rt.store.revokeSession(session.sessionId, Date.now());
  const fresh = await rt.service.createSession({ tenantId: session.tenantId, userId: session.userId, authLevel: "phishing_resistant" });
  return json({ ok: true, authLevel: "phishing_resistant" }, 200, {
    "Set-Cookie": sessionCookie(rt.config.appOrigin, sealSessionId(rt.config.keys.session, fresh), rt.config.sessionTtlSeconds),
  });
}
