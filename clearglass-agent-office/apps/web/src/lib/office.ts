// Server-side data access. The browser never sees the API URL or the operator token.
import demo from "@/data/demo-snapshot.json";
import type { Snapshot } from "./types";

export interface Loaded {
  snap: Snapshot;
  live: boolean;
  note: string | null;
}

export function apiConfig(): { url: string; token: string | undefined } | null {
  const url = process.env.OFFICE_API_URL?.replace(/\/+$/, "");
  return url ? { url, token: process.env.OFFICE_API_TOKEN || undefined } : null;
}

export async function loadSnapshot(): Promise<Loaded> {
  const api = apiConfig();
  if (api) {
    try {
      const res = await fetch(`${api.url}/snapshot`, {
        headers: api.token ? { Authorization: `Bearer ${api.token}` } : {},
        cache: "no-store",
        signal: AbortSignal.timeout(5000),
      });
      if (res.ok) return { snap: (await res.json()) as Snapshot, live: true, note: null };
      return { snap: offline(), live: false, note: `API returned ${res.status}; showing the offline snapshot.` };
    } catch {
      return { snap: offline(), live: false, note: "API unreachable; showing the offline snapshot." };
    }
  }
  return { snap: offline(), live: false, note: null };
}

function offline(): Snapshot {
  return { ...(demo as unknown as Snapshot), source: "snapshot" };
}
