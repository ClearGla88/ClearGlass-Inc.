import { getRuntime } from "@/lib/runtime";
import { forbiddenOrigin, json, rateLimited, refusal, sameOrigin, sessionIdFrom, tooMany } from "@/lib/http";
import { ImageRejected, MAX_UPLOAD_BYTES } from "@/lib/image";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Investigators: submit a suspected leaked copy and/or the trace token read from it. */
export async function POST(request: Request) {
  const rt = await getRuntime();
  if (!sameOrigin(request, rt)) return forbiddenOrigin();
  const sessionId = sessionIdFrom(request, rt);
  if (!sessionId) return json({ error: "session_required" }, 401);
  if (rateLimited(`leak:${sessionId}`, 20)) return tooMany();
  if (Number(request.headers.get("content-length") ?? 0) > MAX_UPLOAD_BYTES + 64 * 1024) return json({ error: "payload_too_large" }, 413);
  const form = await request.formData().catch(() => null);
  if (!form) return json({ error: "invalid_request" }, 400);
  const file = form.get("image");
  const token = form.get("traceToken");
  const traceToken = typeof token === "string" && token.trim() ? token.trim().slice(0, 40) : null;
  const image = file instanceof Blob && file.size > 0 ? Buffer.from(await file.arrayBuffer()) : null;
  if (!image && !traceToken) return json({ error: "image_or_trace_token_required" }, 400);
  try {
    const r = await rt.service.leakIntake(sessionId, { image, traceToken });
    return r.ok ? json(r) : refusal(r);
  } catch (err) {
    if (err instanceof ImageRejected) return json({ error: "image_rejected", detail: err.message }, 422);
    throw err;
  }
}
