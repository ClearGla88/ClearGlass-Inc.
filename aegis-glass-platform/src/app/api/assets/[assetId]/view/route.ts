import { z } from "zod";
import { getRuntime } from "@/lib/runtime";
import { UUID_RE, forbiddenOrigin, json, rateLimited, sameOrigin, sessionIdFrom, tooMany } from "@/lib/http";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const Body = z.object({ purpose: z.string().trim().max(200).nullable().optional() });

/** Ask to view an asset. Returns a single-use capability and the watermark spec, or a reasoned refusal. */
export async function POST(request: Request, { params }: { params: Promise<{ assetId: string }> }) {
  const rt = await getRuntime();
  if (!sameOrigin(request, rt)) return forbiddenOrigin();
  const { assetId } = await params;
  if (!UUID_RE.test(assetId)) return json({ error: "not_found" }, 404);
  const sessionId = sessionIdFrom(request, rt);
  if (!sessionId) return json({ error: "session_required" }, 401);
  // Generous enough for people, low enough that bulk scraping trips risk first and the limiter second.
  if (rateLimited(`view:${sessionId}`, 90)) return tooMany();
  const parsed = Body.safeParse(await request.json().catch(() => ({})));
  if (!parsed.success) return json({ error: "invalid_request" }, 400);

  const r = await rt.service.requestView(sessionId, assetId, parsed.data.purpose ?? null);
  if (r.ok) return json(r);
  if (r.status === "step_up") return json({ error: "step_up_required", requiredAuth: r.requiredAuth, reasons: r.reasons }, 401);
  return json({ error: r.reasons[0] ?? "denied", reasons: r.reasons }, r.httpStatus);
}
