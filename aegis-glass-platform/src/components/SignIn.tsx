"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { postJson } from "./api";

interface Props {
  devLogin: boolean;
  paused: boolean;
  personas: Array<{ key: string; displayName: string; description: string }>;
}

export function SignIn({ devLogin, paused, personas }: Props) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function signIn(persona: string) {
    setBusy(persona);
    setError(null);
    const r = await postJson("/api/dev/login", { persona });
    setBusy(null);
    if (r.status === 200) router.refresh();
    else setError("Sign-in failed.");
  }

  async function reauth() {
    setBusy("reauth");
    const r = await postJson("/api/dev/step-up");
    setBusy(null);
    if (r.status === 200) router.refresh();
    else setError("Re-authentication failed. Sign in again.");
  }

  return (
    <section className="panel" aria-labelledby="signin-title">
      <h2 id="signin-title">{paused ? "Session paused" : "Sign in"}</h2>
      {paused && (
        <div className="notice notice-critical" role="alert">
          <p>Unusual activity paused this session and closed its open views. Nothing has been decided about you: a person reviews these cases.</p>
          {devLogin && (
            <button type="button" className="btn" onClick={reauth} disabled={busy !== null}>
              Re-authenticate with passkey (development simulation)
            </button>
          )}
        </div>
      )}
      {devLogin ? (
        <>
          <p className="muted">
            Development sign-in. In production, sessions come from your organisation&apos;s identity provider with MFA or a passkey.
          </p>
          <ul className="persona-list">
            {personas.map((p) => (
              <li key={p.key}>
                <button type="button" className="persona" onClick={() => signIn(p.key)} disabled={busy !== null} aria-describedby={`persona-${p.key}`}>
                  <span className="persona-name">{p.displayName}</span>
                  <span id={`persona-${p.key}`} className="persona-desc">
                    {p.description}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="muted">Sign-in requires the organisation identity provider, which is not configured for this deployment.</p>
      )}
      {error && (
        <p className="notice notice-critical" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
