import { getRuntime } from "@/lib/runtime";
import { json } from "@/lib/http";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Liveness plus database reachability. Reveals no configuration. */
export async function GET() {
  try {
    const rt = await getRuntime();
    return json({ ok: await rt.store.ping(), engine: rt.db.engine });
  } catch {
    return json({ ok: false }, 503);
  }
}
