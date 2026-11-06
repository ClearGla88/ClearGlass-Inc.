"use client";

import { useState } from "react";
import { postJson } from "./api";

type Intake = { confidence?: string; trace?: Record<string, unknown>; perceptual?: Record<string, unknown>; notes?: string[]; incidentId?: string; error?: string };

const CONFIDENCE_TEXT: Record<string, string> = {
  confirmed_cryptographic_trace: "Confirmed cryptographic trace: the token is genuine and a signed receipt shows the view was served.",
  likely_perceptual_match: "Likely perceptual match: the image resembles a registered asset. It does not identify a person.",
  inconclusive: "Inconclusive: not enough evidence to attribute this copy.",
};

export function InvestigatorPanel({ canIntake }: { canIntake: boolean }) {
  const [audit, setAudit] = useState<string | null>(null);
  const [intake, setIntake] = useState<Intake | null>(null);
  const [busy, setBusy] = useState(false);

  async function verify() {
    setBusy(true);
    const r = await postJson<{ ok?: boolean; events?: number; checkpoints?: number; failedAtSeq?: number; reason?: string }>("/api/audit/verify");
    setBusy(false);
    setAudit(
      r.data.ok
        ? `Chain intact: ${r.data.events} events, ${r.data.checkpoints} signed checkpoints.`
        : r.data.reason
          ? `Chain BROKEN at event ${r.data.failedAtSeq}: ${r.data.reason}.`
          : "Verification refused.",
    );
  }

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    const res = await fetch("/api/leak-intake", { method: "POST", body: new FormData(e.currentTarget), credentials: "same-origin", cache: "no-store" });
    setIntake((await res.json().catch(() => ({ error: "unreadable_response" }))) as Intake);
    setBusy(false);
  }

  return (
    <section className="panel" aria-labelledby="forensics-title">
      <h2 id="forensics-title">Forensics</h2>
      <div className="forensics">
        <div>
          <h3>Audit chain</h3>
          <p className="muted">Replays every hash link and checks each signed checkpoint.</p>
          <button type="button" className="btn" onClick={verify} disabled={busy}>
            Verify audit trail
          </button>
          {audit && (
            <p className="result" role="status">
              {audit}
            </p>
          )}
        </div>
        {canIntake && (
          <form onSubmit={submit}>
            <h3>Leak intake</h3>
            <p className="muted">Submit the suspected copy and, if legible, the trace token printed on it. Results open a case for human review.</p>
            <label htmlFor="leak-image">Suspected copy (PNG, JPEG, or WebP)</label>
            <input id="leak-image" name="image" type="file" accept="image/png,image/jpeg,image/webp" />
            <label htmlFor="leak-token">Trace token</label>
            <input id="leak-token" name="traceToken" placeholder="XXXX-XXXX-XXXX" autoComplete="off" maxLength={40} />
            <button type="submit" className="btn" disabled={busy}>
              Submit for matching
            </button>
          </form>
        )}
      </div>
      {intake && (
        <div className="result" role="status">
          {intake.error ? (
            <p>Refused: {intake.error}</p>
          ) : (
            <>
              <p>
                <strong>{CONFIDENCE_TEXT[intake.confidence ?? ""] ?? intake.confidence}</strong>
              </p>
              {intake.trace && intake.trace.status !== "not_provided" && <p>Trace: {String(intake.trace.status)}{intake.trace.viewerPseudonym ? ` · viewer ${String(intake.trace.viewerPseudonym)}` : ""}</p>}
              {intake.perceptual && intake.perceptual.status !== "not_provided" && <p>Image: {String(intake.perceptual.status)} (distance {String(intake.perceptual.bestDistance)})</p>}
              {intake.notes?.map((n) => (
                <p key={n} className="muted">
                  {n}
                </p>
              ))}
              <p className="muted">Case {intake.incidentId} opened: needs human review.</p>
            </>
          )}
        </div>
      )}
    </section>
  );
}
