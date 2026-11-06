import { getRuntime } from "@/lib/runtime";
import { UUID_RE, json, rateLimited, refusal, sessionIdFrom, tooMany } from "@/lib/http";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Polled by the viewer so a revoked view disappears without a page reload. */
export async function GET(request: Request, { params }: { params: Promise<{ viewId: string }> }) {
  const rt = await getRuntime();
  const { viewId } = await params;
  if (!UUID_RE.test(viewId)) return json({ error: "not_found" }, 404);
  const sessionId = sessionIdFrom(request, rt);
  if (sessionId && rateLimited(`status:${sessionId}`, 120)) return tooMany();
  const r = await rt.service.viewStatus(sessionId, viewId);
  return r.ok ? json({ active: r.active, reason: r.reason }) : refusal(r);
}
