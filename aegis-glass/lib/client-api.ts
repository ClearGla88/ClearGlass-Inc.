// Browser-side fetch helpers. Same-origin only; every POST carries the CSRF header.

import { CSRF_HEADER, CSRF_HEADER_VALUE } from "./headers.ts";

export interface ApiResult<T = unknown> {
  ok: boolean;
  status: number;
  data: T;
}

async function parse<T>(res: Response): Promise<ApiResult<T>> {
  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  return { ok: res.ok, status: res.status, data: data as T };
}

export async function apiPost<T = unknown>(path: string, body: unknown = {}): Promise<ApiResult<T>> {
  const res = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers: { "Content-Type": "application/json", [CSRF_HEADER]: CSRF_HEADER_VALUE },
    body: JSON.stringify(body),
  });
  return parse<T>(res);
}

export async function apiGet<T = unknown>(path: string): Promise<ApiResult<T>> {
  const res = await fetch(path, { credentials: "same-origin", cache: "no-store" });
  return parse<T>(res);
}

export function errorCode(data: unknown): string | undefined {
  return data && typeof data === "object" && "error" in data && typeof (data as { error: unknown }).error === "string"
    ? (data as { error: string }).error
    : undefined;
}
