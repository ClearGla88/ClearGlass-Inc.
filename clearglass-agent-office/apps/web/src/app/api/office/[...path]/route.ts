// Server-side proxy for console actions. The operator token never reaches the browser.
//
// Guards, in order: an allow-listed path, a same-origin request, a signed-in operator session (or open local
// development), a configured API, and a body under 64 KiB. Anything else is refused before the API is called.
import { NextResponse, type NextRequest } from "next/server";
import { apiConfig } from "@/lib/office";
import { authMode, isAuthed } from "@/lib/session";

const ID = "[A-Za-z0-9_.-]{1,64}";
const ALLOWED: { method: "POST" | "PATCH"; pattern: RegExp }[] = [
  { method: "POST", pattern: new RegExp(`^approvals/${ID}/decision$`) },
  { method: "POST", pattern: /^agents$/ },
  { method: "POST", pattern: new RegExp(`^agents/${ID}/(clone|pause|resume|retire)$`) },
  { method: "PATCH", pattern: new RegExp(`^agents/${ID}$`) },
  { method: "POST", pattern: /^missions$/ },
  { method: "POST", pattern: new RegExp(`^missions/${ID}/run$`) },
  { method: "POST", pattern: /^daily-loop\/run$/ },
  { method: "POST", pattern: /^memory$/ },
  { method: "POST", pattern: new RegExp(`^memory/${ID}/decision$`) },
  { method: "POST", pattern: /^simulations$/ },
  { method: "POST", pattern: /^emergency-stop(\/release)?$/ },
  { method: "POST", pattern: /^policy\/evaluate$/ },
];
const MAX_BODY = 64 * 1024;

function refuse(status: number, detail: string) {
  return NextResponse.json({ detail }, { status });
}

async function forward(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }, method: "POST" | "PATCH") {
  const path = (await ctx.params).path.join("/");
  if (!ALLOWED.some((r) => r.method === method && r.pattern.test(path))) return refuse(404, "unknown action");

  const origin = req.headers.get("origin");
  if (!origin || new URL(origin).host !== req.headers.get("host")) return refuse(403, "cross-origin request refused");

  const mode = authMode();
  if (mode === "locked") return refuse(503, "console is locked: set OFFICE_CONSOLE_PASSPHRASE and OFFICE_SESSION_SECRET");
  if (!(await isAuthed())) return refuse(401, "sign in to the console first");

  const api = apiConfig();
  if (!api) return refuse(503, "offline snapshot: set OFFICE_API_URL to take actions");

  const body = await req.text();
  if (body.length > MAX_BODY) return refuse(413, "request body too large");

  try {
    const res = await fetch(`${api.url}/${path}`, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(api.token ? { Authorization: `Bearer ${api.token}` } : {}),
      },
      body: body || "{}",
      cache: "no-store",
      signal: AbortSignal.timeout(60_000),
    });
    const text = await res.text();
    return new NextResponse(text, { status: res.status, headers: { "Content-Type": "application/json" } });
  } catch {
    return refuse(502, "the office API did not respond");
  }
}

export function POST(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, ctx, "POST");
}

export function PATCH(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, ctx, "PATCH");
}
