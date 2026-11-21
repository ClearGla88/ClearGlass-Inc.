// Policy enforcement point #2: verify the capability, re-check policy, and
// stream a freshly rendered, watermarked preview. Never cached anywhere.

import { MEDIA_HEADERS } from "../../../../lib/headers.ts";
import { json, principalFrom, runtimeOr503 } from "../../../../lib/http.ts";

export async function GET(request: Request, ctx: { params: Promise<{ token: string }> }): Promise<Response> {
  const rt = await runtimeOr503();
  if (rt instanceof Response) return rt;
  const { token } = await ctx.params;
  const result = await rt.service.serveMedia(principalFrom(request, rt), token);
  if (result.status !== 200) return json({ error: result.error }, result.status);
  return new Response(new Uint8Array(result.bytes), {
    status: 200,
    headers: { ...MEDIA_HEADERS, "Content-Type": result.mime, "Content-Length": String(result.bytes.length) },
  });
}
