// Leak intake: resolve a trace token read off a leaked image to its signed
// view receipt. Investigators only; every lookup is itself audited.

import { json, principalFrom, runtimeOr503, TRACE_TOKEN } from "../../../../lib/http.ts";

export async function GET(request: Request, ctx: { params: Promise<{ token: string }> }): Promise<Response> {
  const rt = await runtimeOr503();
  if (rt instanceof Response) return rt;
  const p = principalFrom(request, rt);
  if (!p) return json({ error: "unauthenticated" }, 401);
  const { token } = await ctx.params;
  if (!TRACE_TOKEN.test(token)) return json({ error: "not_found" }, 404);
  const result = await rt.service.resolveTrace(p, token);
  if (result.status !== 200) return json({ error: result.error }, result.status);
  return json({
    evidenceGrade: result.signatureValid ? "confirmed_cryptographic_trace" : "inconclusive",
    signatureValid: result.signatureValid,
    receipt: result.receipt,
  });
}
