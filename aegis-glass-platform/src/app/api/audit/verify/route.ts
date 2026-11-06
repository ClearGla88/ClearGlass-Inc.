import { getRuntime } from "@/lib/runtime";
import { forbiddenOrigin, json, refusal, sameOrigin, sessionIdFrom } from "@/lib/http";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Investigators and tenant admins: replay the audit hash chain and its signed checkpoints. */
export async function POST(request: Request) {
  const rt = await getRuntime();
  if (!sameOrigin(request, rt)) return forbiddenOrigin();
  await rt.service.checkpointNow();
  const r = await rt.service.verifyAudit(sessionIdFrom(request, rt) ?? "");
  if ("httpStatus" in r) return refusal(r);
  return json(r.ok ? { ok: true, events: r.events, checkpoints: r.checkpoints, headSeq: r.headSeq, checkedAt: r.checkedAt } : { ok: false, failedAtSeq: r.failedAtSeq, reason: r.reason, checkedAt: r.checkedAt });
}
