// Helpers shared by route handlers. Server only.

import "server-only";
import { ProductionNotReadyError } from "./config.ts";
import { API_HEADERS, CSRF_HEADER, CSRF_HEADER_VALUE } from "./headers.ts";
import { getRuntime, type AegisRuntime } from "./runtime.ts";
import { cookieValue, readSessionCookie, SESSION_COOKIE } from "./session.ts";
import type { Principal } from "./types.ts";

export function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...API_HEADERS, ...headers },
  });
}

export async function runtimeOr503(): Promise<AegisRuntime | Response> {
  try {
    return await getRuntime();
  } catch (err) {
    if (err instanceof ProductionNotReadyError) return json({ error: "not_configured" }, 503);
    throw err;
  }
}

export function principalFrom(request: Request, rt: AegisRuntime): Principal | undefined {
  const value = cookieValue(request.headers.get("cookie"), SESSION_COOKIE);
  return readSessionCookie(rt.config.sessionKey, value, Math.floor(Date.now() / 1000));
}

/**
 * CSRF defence for state-changing requests, layered on SameSite=Strict cookies:
 * the custom header forces a CORS preflight for any cross-origin caller, and
 * the Origin must match the Host the request was sent to.
 */
export function mutationGuard(request: Request): Response | undefined {
  if (request.headers.get(CSRF_HEADER) !== CSRF_HEADER_VALUE) return json({ error: "csrf" }, 403);
  const origin = request.headers.get("origin");
  const host = request.headers.get("host");
  if (!origin || !host) return json({ error: "csrf" }, 403);
  try {
    if (new URL(origin).host !== host) return json({ error: "csrf" }, 403);
  } catch {
    return json({ error: "csrf" }, 403);
  }
  return undefined;
}

export async function readJson<T>(request: Request, maxBytes = 4096): Promise<T | undefined> {
  const text = await request.text();
  if (text.length > maxBytes) return undefined;
  try {
    return JSON.parse(text) as T;
  } catch {
    return undefined;
  }
}

export const ASSET_ID = /^[A-Za-z0-9-]{1,64}$/;
export const TRACE_TOKEN = /^T-[0-9A-Z]{10}$/;
