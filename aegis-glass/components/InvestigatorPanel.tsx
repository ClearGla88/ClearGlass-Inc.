"use client";

// Review tools. A case is an allegation to check, not a finding: the panel
// shows evidence and offers only reversible actions. Anything heavier
// (suspending an account, contacting anyone) happens outside this tool, after
// a person has reviewed the evidence.

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { apiGet, apiPost, errorCode } from "../lib/client-api.ts";

interface Case {
  id: string;
  kind: string;
  status: string;
  subjectUserId: string;
  subjectSessionId: string;
  assetId?: string;
  openedAt: string;
  summary: string;
}

interface Verification {
  ok: boolean;
  checked: number;
  brokenAt?: number;
  problem?: string;
}

interface TraceResult {
  evidenceGrade: string;
  signatureValid: boolean;
  receipt: {
    keyId: string;
    body: { assetId: string; userId: string; viewerPseudonym: string; servedAt: string; classification: string; servedSha256: string; policyVersion: string };
  };
}

export function InvestigatorPanel({ canResolveTraces, canRevoke }: { canResolveTraces: boolean; canRevoke: boolean }) {
  const [cases, setCases] = useState<Case[]>([]);
  const [verification, setVerification] = useState<Verification | null>(null);
  const [trace, setTrace] = useState("");
  const [traceResult, setTraceResult] = useState<TraceResult | null>(null);
  const [message, setMessage] = useState("");

  const loadCases = useCallback(async () => {
    const r = await apiGet<{ cases: Case[] }>("/api/cases");
    if (r.ok) setCases(r.data.cases);
  }, []);

  useEffect(() => {
    void loadCases();
  }, [loadCases]);

  const verify = async () => {
    const r = await apiPost<Verification>("/api/audit/verify");
    if (r.ok) setVerification(r.data);
    else setMessage(`Verification failed: ${errorCode(r.data) ?? r.status}`);
  };

  const resolve = async (e: FormEvent) => {
    e.preventDefault();
    setTraceResult(null);
    const token = trace.trim().toUpperCase();
    const r = await apiGet<TraceResult>(`/api/traces/${encodeURIComponent(token)}`);
    if (r.ok) setTraceResult(r.data);
    else setMessage(r.status === 404 ? "No receipt matches that trace token." : `Lookup failed: ${errorCode(r.data) ?? r.status}`);
  };

  const revoke = async (sessionId: string) => {
    const r = await apiPost("/api/sessions/revoke", { sessionId, reason: "revoked after case review" });
    setMessage(r.ok ? "Session revoked. The person can sign in again; their open previews stop within seconds." : `Revoke failed: ${errorCode(r.data) ?? r.status}`);
  };

  return (
    <aside className="investigator glass" aria-label="Review tools">
      <h2 className="panel-title">Review</h2>

      <div className="tool">
        <button type="button" className="btn" onClick={verify}>
          Verify audit chain
        </button>
        {verification && (
          <p className={verification.ok ? "ok" : "bad"}>
            {verification.ok ? `Intact: ${verification.checked} records checked.` : `Broken at record ${verification.brokenAt} (${verification.problem}).`}
          </p>
        )}
      </div>

      {canResolveTraces && (
        <form className="tool" onSubmit={resolve}>
          <label htmlFor="trace">Trace token from a leaked image</label>
          <div className="row">
            <input id="trace" value={trace} onChange={(e) => setTrace(e.target.value)} placeholder="T-XXXXXXXXXX" pattern="[Tt]-[0-9A-Za-z]{10}" autoComplete="off" spellCheck={false} />
            <button type="submit" className="btn">
              Resolve
            </button>
          </div>
          {traceResult && (
            <dl className="evidence">
              <dt>Evidence</dt>
              <dd>{traceResult.evidenceGrade.replaceAll("_", " ")}</dd>
              <dt>Asset</dt>
              <dd>{traceResult.receipt.body.assetId}</dd>
              <dt>Viewer</dt>
              <dd>
                {traceResult.receipt.body.viewerPseudonym} ({traceResult.receipt.body.userId})
              </dd>
              <dt>Served</dt>
              <dd>{traceResult.receipt.body.servedAt}</dd>
              <dt>Preview SHA-256</dt>
              <dd className="mono">{traceResult.receipt.body.servedSha256.slice(0, 16)}…</dd>
            </dl>
          )}
        </form>
      )}

      <div className="tool">
        <div className="row spread">
          <h3>Cases</h3>
          <button type="button" className="btn btn-small" onClick={() => void loadCases()}>
            Refresh
          </button>
        </div>
        {cases.length === 0 ? (
          <p className="muted">No open cases.</p>
        ) : (
          <ul className="cases">
            {cases.map((c) => (
              <li key={c.id}>
                <p>
                  <strong>{c.kind.replaceAll("_", " ")}</strong> · {c.status.replaceAll("_", " ")}
                </p>
                <p className="muted">{c.summary}</p>
                <p className="muted mono">
                  user {c.subjectUserId} · {new Date(c.openedAt).toLocaleString()}
                </p>
                {canRevoke && (
                  <button type="button" className="btn btn-small" onClick={() => void revoke(c.subjectSessionId)}>
                    Revoke that session
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      <p className="visually-hidden" role="status" aria-live="polite">
        {message}
      </p>
      {message && <p className="muted">{message}</p>}
    </aside>
  );
}
