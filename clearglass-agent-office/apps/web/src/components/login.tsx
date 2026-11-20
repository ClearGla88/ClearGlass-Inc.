"use client";

import { useState } from "react";

export function LoginGate() {
  const [pass, setPass] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <main className="grid min-h-dvh place-items-center px-4">
      <form
        className="glass glass-edge w-full max-w-sm p-6"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          const res = await fetch("/api/session", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ passphrase: pass }),
          });
          setBusy(false);
          if (res.ok) window.location.reload();
          else setError(((await res.json().catch(() => ({}))) as { detail?: string }).detail ?? "sign-in failed");
        }}
      >
        <p className="label">ClearGlass Agent Office</p>
        <h1 className="mt-1 text-xl font-semibold">Operator sign-in</h1>
        <label htmlFor="pass" className="label mt-5 block">Passphrase</label>
        <input id="pass" type="password" autoComplete="current-password" value={pass}
          onChange={(e) => setPass(e.target.value)} className="mt-1 w-full px-3 py-2" />
        <button type="submit" disabled={busy || !pass}
          className="mt-4 w-full rounded-lg border border-accent/50 bg-accent/15 py-2 text-sm font-medium text-accent disabled:opacity-40">
          {busy ? "Checking…" : "Enter the office"}
        </button>
        {error && <p role="alert" className="mt-3 text-sm text-bad">{error}</p>}
      </form>
    </main>
  );
}
