// Console sign-in and sign-out. Sets or clears the signed, HttpOnly session cookie.
import { NextResponse, type NextRequest } from "next/server";
import { authMode, checkPassphrase, issueToken, SESSION_COOKIE, sessionCookieOptions } from "@/lib/session";

const attempts = new Map<string, number[]>();

function limited(key: string): boolean {
  const now = Date.now();
  const recent = (attempts.get(key) ?? []).filter((t) => now - t < 60_000);
  recent.push(now);
  attempts.set(key, recent);
  return recent.length > 5;
}

export async function POST(req: NextRequest) {
  const origin = req.headers.get("origin");
  if (!origin || new URL(origin).host !== req.headers.get("host")) {
    return NextResponse.json({ detail: "cross-origin request refused" }, { status: 403 });
  }
  if (authMode() !== "required") {
    return NextResponse.json({ detail: "sign-in is not configured" }, { status: 400 });
  }
  const ip = req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || "local";
  if (limited(ip)) return NextResponse.json({ detail: "too many attempts; wait a minute" }, { status: 429 });
  const { passphrase } = (await req.json().catch(() => ({}))) as { passphrase?: string };
  if (typeof passphrase !== "string" || !checkPassphrase(passphrase)) {
    return NextResponse.json({ detail: "wrong passphrase" }, { status: 401 });
  }
  const res = NextResponse.json({ ok: true });
  res.cookies.set(SESSION_COOKIE, issueToken(), sessionCookieOptions);
  return res;
}

export async function DELETE() {
  const res = NextResponse.json({ ok: true });
  res.cookies.set(SESSION_COOKIE, "", { ...sessionCookieOptions, maxAge: 0 });
  return res;
}
