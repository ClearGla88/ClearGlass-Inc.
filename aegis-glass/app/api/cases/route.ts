import { json, principalFrom, runtimeOr503 } from "../../../lib/http.ts";

export async function GET(request: Request): Promise<Response> {
  const rt = await runtimeOr503();
  if (rt instanceof Response) return rt;
  const p = principalFrom(request, rt);
  if (!p) return json({ error: "unauthenticated" }, 401);
  const result = await rt.service.listCases(p);
  return result.status === 200 ? json({ cases: result.cases }) : json({ error: result.error }, result.status);
}
