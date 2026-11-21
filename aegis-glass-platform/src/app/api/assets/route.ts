import { z } from "zod";
import { getRuntime } from "@/lib/runtime";
import { forbiddenOrigin, json, rateLimited, refusal, sameOrigin, sessionIdFrom, tooMany } from "@/lib/http";
import { CLASSIFICATIONS } from "@/lib/classification";
import { ImageRejected, MAX_UPLOAD_BYTES } from "@/lib/image";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const Fields = z.object({
  title: z.string().trim().min(1).max(200),
  altText: z.string().trim().min(1).max(1000),
  classification: z.enum(CLASSIFICATIONS),
  compartment: z
    .string()
    .trim()
    .regex(/^[a-z0-9][a-z0-9-]{0,62}$/)
    .nullable(),
  honey: z.boolean(),
});

/** Upload an image. It is validated, sealed with a fresh data key, and stored privately. */
export async function POST(request: Request) {
  const rt = await getRuntime();
  if (!sameOrigin(request, rt)) return forbiddenOrigin();
  const sessionId = sessionIdFrom(request, rt);
  if (!sessionId) return json({ error: "session_required" }, 401);
  if (rateLimited(`upload:${sessionId}`, 20)) return tooMany();
  const length = Number(request.headers.get("content-length") ?? 0);
  if (length > MAX_UPLOAD_BYTES + 64 * 1024) return json({ error: "payload_too_large" }, 413);

  const form = await request.formData().catch(() => null);
  const file = form?.get("file");
  if (!form || !(file instanceof Blob)) return json({ error: "invalid_request" }, 400);
  const parsed = Fields.safeParse({
    title: form.get("title"),
    altText: form.get("altText"),
    classification: form.get("classification"),
    compartment: (form.get("compartment") as string | null) || null,
    honey: form.get("honey") === "true",
  });
  if (!parsed.success) return json({ error: "invalid_request", fields: parsed.error.issues.map((i) => i.path.join(".")) }, 400);

  try {
    const result = await rt.service.uploadAsset(sessionId, { ...parsed.data, bytes: Buffer.from(await file.arrayBuffer()) });
    return result.ok ? json({ ok: true, assetId: result.assetId }, 201) : refusal(result);
  } catch (err) {
    if (err instanceof ImageRejected) return json({ error: "image_rejected", detail: err.message }, 422);
    throw err;
  }
}
