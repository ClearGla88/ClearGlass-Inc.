"use client";

// Same-origin JSON helper. Cookies are HttpOnly and SameSite=Strict; the server
// also checks Origin on every state-changing request.
export async function postJson<T = Record<string, unknown>>(path: string, body: unknown = {}): Promise<{ status: number; data: T }> {
  const res = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return { status: res.status, data: (await res.json().catch(() => ({}))) as T };
}
