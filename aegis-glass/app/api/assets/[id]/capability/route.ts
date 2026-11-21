// Policy enforcement point #1: issue a single-use media capability, or say why not.

import { ASSET_ID, json, mutationGuard, principalFrom, runtimeOr503 } from "../../../../../lib/http.ts";
import { cookieValue, DEVICE_COOKIE } from "../../../../../lib/session.ts";

export async function POST(request: Request, ctx: { params: Promise<{ id: string }> }): Promise<Response> {
  const blocked = mutationGuard(request);
  if (blocked) return blocked;
  const rt = await runtimeOr503();
  if (rt instanceof Response) return rt;
  const p = principalFrom(request, rt);
  if (!p) return json({ error: "unauthenticated" }, 401);

  const { id } = await ctx.params;
  if (!ASSET_ID.test(id)) return json({ error: "not_found" }, 404);

  const deviceId = cookieValue(request.headers.get("cookie"), DEVICE_COOKIE);
  const result = await rt.service.requestCapability(p, id, { deviceId });
  return json(result.body, result.status);
}
