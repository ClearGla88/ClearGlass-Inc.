import { z } from "zod";
import { getRuntime } from "@/lib/runtime";
import { forbiddenOrigin, json, rateLimited, sameOrigin, tooMany } from "@/lib/http";
import { PERSONAS } from "@/lib/demo";
import { sealSessionId, sessionCookie } from "@/lib/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// DEVELOPMENT ONLY. Stands in for the organisation's identity provider so the
// demo can be exercised. Returns 404 in production and when AEGIS_DEV_LOGIN=0.
const Body = z.object({ persona: z.enum(["analyst", "admin", "investigator", "outsider"]) });

export async function POST(request: Request) {
  const rt = await getRuntime();
  if (rt.config.env === "production" || !rt.config.devLogin) return json({ error: "not_found" }, 404);
  if (!sameOrigin(request, rt)) return forbiddenOrigin();
  if (rateLimited(`dev-login:${request.headers.get("x-forwarded-for") ?? "local"}`, 30)) return tooMany();
  const parsed = Body.safeParse(await request.json().catch(() => null));
  if (!parsed.success) return json({ error: "invalid_request" }, 400);
  const p = PERSONAS.find((x) => x.key === parsed.data.persona);
  if (!p) return json({ error: "invalid_request" }, 400);
  const sessionId = await rt.service.createSession({ tenantId: p.tenantId, userId: p.userId, authLevel: p.authLevel });
  return json({ ok: true, persona: p.key }, 200, {
    "Set-Cookie": sessionCookie(rt.config.appOrigin, sealSessionId(rt.config.keys.session, sessionId), rt.config.sessionTtlSeconds),
  });
}
