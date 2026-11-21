// POST because verification is itself recorded in the audit chain.

import { json, mutationGuard, principalFrom, runtimeOr503 } from "../../../../lib/http.ts";

export async function POST(request: Request): Promise<Response> {
  const blocked = mutationGuard(request);
  if (blocked) return blocked;
  const rt = await runtimeOr503();
  if (rt instanceof Response) return rt;
  const p = principalFrom(request, rt);
  if (!p) return json({ error: "unauthenticated" }, 401);
  const result = await rt.service.verifyAudit(p);
  return result.status === 200 ? json(result.result) : json({ error: result.error }, result.status);
}
