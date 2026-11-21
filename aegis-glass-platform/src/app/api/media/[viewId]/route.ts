import { getRuntime } from "@/lib/runtime";
import { NO_STORE, UUID_RE, json, rateLimited, refusal, sessionIdFrom, tooMany } from "@/lib/http";
import { CAPABILITY_HEADER } from "@/lib/capability";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Deliver one derived, watermarked preview. Requires the session cookie AND the
 * single-use capability in a request header. A custom header cannot be sent
 * cross-origin without a CORS preflight, which this app never grants.
 */
export async function GET(request: Request, { params }: { params: Promise<{ viewId: string }> }) {
  const rt = await getRuntime();
  const site = request.headers.get("sec-fetch-site");
  if (site && site !== "same-origin") return json({ error: "cross_origin_request_refused" }, 403);
  const { viewId } = await params;
  if (!UUID_RE.test(viewId)) return json({ error: "not_found" }, 404);
  const sessionId = sessionIdFrom(request, rt);
  if (!sessionId) return json({ error: "session_required" }, 401);
  if (rateLimited(`media:${sessionId}`, 90)) return tooMany();

  const r = await rt.service.serveMedia(sessionId, viewId, request.headers.get(CAPABILITY_HEADER));
  if (!r.ok) return refusal(r);
  return new Response(new Uint8Array(r.bytes), {
    status: 200,
    headers: {
      "Content-Type": r.contentType,
      "Content-Length": String(r.bytes.length),
      ...NO_STORE,
      Expires: "0",
      "Content-Disposition": "inline",
      "X-Content-Type-Options": "nosniff",
      "Cross-Origin-Resource-Policy": "same-origin",
      "X-Aegis-Receipt": r.receiptId,
    },
  });
}
