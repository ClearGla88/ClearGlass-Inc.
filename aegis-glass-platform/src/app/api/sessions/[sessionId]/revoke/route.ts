import { getRuntime } from "@/lib/runtime";
import { UUID_RE, forbiddenOrigin, json, refusal, sameOrigin, sessionIdFrom } from "@/lib/http";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Tenant admin (or the session's own user): revoke a session and every view issued to it. */
export async function POST(request: Request, { params }: { params: Promise<{ sessionId: string }> }) {
  const rt = await getRuntime();
  if (!sameOrigin(request, rt)) return forbiddenOrigin();
  const { sessionId: target } = await params;
  if (!UUID_RE.test(target)) return json({ error: "not_found" }, 404);
  const r = await rt.service.revokeSession(sessionIdFrom(request, rt) ?? "", target);
  return r.ok ? json({ ok: true }) : refusal(r);
}
