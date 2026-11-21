// Demo-mode sign-in. Stands in for the OIDC callback: production replaces this
// route with the identity provider and keeps the same session format.

import { json, mutationGuard, readJson, runtimeOr503 } from "../../../../lib/http.ts";
import { PERSONAS, personaPrincipal } from "../../../../lib/seed.ts";
import { cookieValue, DEVICE_COOKIE, deviceCookieHeader, issueSessionCookie, newDeviceId, newSessionId, SESSION_TTL_SECONDS, sessionCookieHeader } from "../../../../lib/session.ts";

export async function POST(request: Request): Promise<Response> {
  const blocked = mutationGuard(request);
  if (blocked) return blocked;
  const rt = await runtimeOr503();
  if (rt instanceof Response) return rt;
  if (rt.config.mode !== "demo") return json({ error: "not_found" }, 404);

  const body = await readJson<{ persona?: unknown }>(request);
  const persona = PERSONAS.find((p) => p.key === body?.persona);
  if (!persona) return json({ error: "unknown_persona" }, 400);

  const now = Math.floor(Date.now() / 1000);
  const principal = personaPrincipal(persona, newSessionId(), now);
  await rt.service.registerSession(principal, SESSION_TTL_SECONDS);

  const headers = new Headers({ "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" });
  headers.append("Set-Cookie", sessionCookieHeader(issueSessionCookie(rt.config.sessionKey, principal, now)));
  if (!cookieValue(request.headers.get("cookie"), DEVICE_COOKIE)) headers.append("Set-Cookie", deviceCookieHeader(newDeviceId()));
  return new Response(JSON.stringify({ ok: true, persona: persona.key }), { status: 200, headers });
}
