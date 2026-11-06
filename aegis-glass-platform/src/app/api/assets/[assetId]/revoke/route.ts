import { getRuntime } from "@/lib/runtime";
import { UUID_RE, forbiddenOrigin, json, refusal, sameOrigin, sessionIdFrom } from "@/lib/http";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Owner or tenant admin: withdraw an asset. Open views stop at their next status check or fetch. */
export async function POST(request: Request, { params }: { params: Promise<{ assetId: string }> }) {
  const rt = await getRuntime();
  if (!sameOrigin(request, rt)) return forbiddenOrigin();
  const { assetId } = await params;
  if (!UUID_RE.test(assetId)) return json({ error: "not_found" }, 404);
  const r = await rt.service.revokeAsset(sessionIdFrom(request, rt) ?? "", assetId);
  return r.ok ? json({ ok: true }) : refusal(r);
}
