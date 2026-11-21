"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { apiPost, errorCode } from "../lib/client-api.ts";

export interface PersonaOption {
  key: string;
  label: string;
  description: string;
}

export function DevLogin({ personas }: { personas: PersonaOption[] }) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");

  const signIn = async (persona: string) => {
    setBusy(persona);
    setError("");
    const r = await apiPost("/api/dev/login", { persona });
    setBusy(null);
    if (r.ok) router.refresh();
    else setError(`Sign-in failed (${errorCode(r.data) ?? r.status}).`);
  };

  return (
    <main className="signin glass">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true" />
        <span>Aegis Glass</span>
      </div>
      <h1>Protected previews for confidential work</h1>
      <p className="muted">
        Demo mode. Pick a role to sign in. Every item is synthetic, keys are generated at startup, and nothing is stored after the
        server stops.
      </p>
      <ul className="personas">
        {personas.map((p) => (
          <li key={p.key}>
            <button type="button" className="persona" onClick={() => void signIn(p.key)} disabled={busy !== null}>
              <span className="persona-label">{busy === p.key ? "Signing in…" : p.label}</span>
              <span className="muted">{p.description}</span>
            </button>
          </li>
        ))}
      </ul>
      <p role="alert" className="bad">
        {error}
      </p>
    </main>
  );
}
