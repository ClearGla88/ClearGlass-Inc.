"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { epochFor, layoutFor, DENSITY_SPEC, type WatermarkLayout } from "@/lib/watermark";
import type { WatermarkDensity } from "@/lib/classification";
import { postJson } from "./api";

// Renders one protected preview.
//
// What it does: fetches a single-use derivative with a header-borne capability,
// overlays a rotating, viewer-attributed watermark (the same text is burned
// into the pixels server-side), polls for revocation, and reports browser
// signals that raise the session's risk.
//
// What it cannot do: stop a camera, an OS screenshot, or a determined user with
// a modified browser. Copy, drag, context-menu, and print controls below are
// friction only. Attribution is the control that holds.

type Permit = {
  viewId: string;
  capability: string;
  mediaPath: string;
  expiresAt: string;
  altText: string;
  classification: string;
  riskState: string;
  watermark: { density: WatermarkDensity; rotationSeconds: number; seed: string; lines: [string, string] };
};

type State =
  | { kind: "requesting" }
  | { kind: "loading"; permit: Permit }
  | { kind: "showing"; permit: Permit; url: string }
  | { kind: "step_up"; requiredAuth: string }
  | { kind: "denied"; reason: string }
  | { kind: "revoked"; reason: string };

const REASON_TEXT: Record<string, string> = {
  no_entitlement: "You do not have access to this asset.",
  purpose_mismatch: "Enter the purpose recorded on your access grant.",
  grant_missing_purpose: "Your grant has no recorded purpose; ask the owner to reissue it.",
  not_found: "This asset is not available.",
  risk_exceeds_classification_ceiling: "Recent activity on this session is too unusual for this classification. Try again later.",
  session_paused: "This session is paused. Re-authenticate to continue.",
  session_revoked: "Your session was ended by an administrator.",
  view_revoked: "This view was withdrawn.",
  asset_revoked: "The owner withdrew this asset.",
  rate_limited: "Too many requests. Wait a minute and try again.",
};
const describe = (reason: string) => REASON_TEXT[reason] ?? `Request refused (${reason}).`;

export function SecureAssetViewer({ assetId, purpose, onStepUp }: { assetId: string; purpose: string | null; onStepUp: (() => void) | null }) {
  const [state, setState] = useState<State>({ kind: "requesting" });
  const [risk, setRisk] = useState("LOW");
  const [layout, setLayout] = useState<WatermarkLayout | null>(null);
  const urlRef = useRef<string | null>(null);
  const viewIdRef = useRef<string | null>(null);
  const lastSignal = useRef<Record<string, number>>({});

  const clearImage = useCallback(() => {
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    urlRef.current = null;
  }, []);

  // 1. Request a view, then spend the capability exactly once.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const r = await postJson<Permit & { error?: string; requiredAuth?: string }>(`/api/assets/${assetId}/view`, { purpose });
      if (cancelled) return;
      if (r.status === 401 && r.data.error === "step_up_required") return setState({ kind: "step_up", requiredAuth: r.data.requiredAuth ?? "mfa" });
      if (r.status !== 200) return setState({ kind: "denied", reason: r.data.error ?? "denied" });
      const permit = r.data;
      viewIdRef.current = permit.viewId;
      setRisk(permit.riskState);
      setState({ kind: "loading", permit });
      const media = await fetch(permit.mediaPath, { credentials: "same-origin", cache: "no-store", headers: { "x-aegis-capability": permit.capability } });
      if (cancelled) return;
      if (!media.ok) {
        const body = (await media.json().catch(() => ({}))) as { error?: string };
        return setState({ kind: "denied", reason: body.error ?? "media_refused" });
      }
      const url = URL.createObjectURL(await media.blob());
      urlRef.current = url;
      setState({ kind: "showing", permit, url });
    })();
    return () => {
      cancelled = true;
      clearImage();
    };
  }, [assetId, purpose, clearImage]);

  const permit = state.kind === "loading" || state.kind === "showing" ? state.permit : null;

  // 2. Rotate the overlay layout every rotation period.
  useEffect(() => {
    if (!permit || permit.watermark.density === "none") return;
    const { seed, density, rotationSeconds } = permit.watermark;
    const tick = () => setLayout(layoutFor(seed, epochFor(Date.now(), rotationSeconds), density));
    tick();
    const id = window.setInterval(tick, rotationSeconds * 1000);
    return () => window.clearInterval(id);
  }, [permit]);

  // 3. Revocation: poll, and re-check whenever the tab becomes visible again.
  useEffect(() => {
    if (state.kind !== "showing") return;
    const check = async () => {
      const res = await fetch(`/api/views/${state.permit.viewId}/status`, { credentials: "same-origin", cache: "no-store" }).catch(() => null);
      const body = (await res?.json().catch(() => null)) as { active?: boolean; reason?: string } | null;
      if (body && body.active === false) {
        clearImage();
        setState({ kind: "revoked", reason: body.reason ?? "view_revoked" });
      }
    };
    const id = window.setInterval(check, 10_000);
    const onVis = () => document.visibilityState === "visible" && void check();
    document.addEventListener("visibilitychange", onVis);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [state, clearImage]);

  // 4. Browser signals. Throttled; each can only raise risk on the server.
  const signal = useCallback(
    async (kind: string, minGapMs = 5000) => {
      const viewId = viewIdRef.current;
      if (!viewId) return;
      const now = Date.now();
      if (now - (lastSignal.current[kind] ?? 0) < minGapMs) return;
      lastSignal.current[kind] = now;
      const r = await postJson<{ riskState?: string; actions?: string[] }>("/api/risk/signal", { viewId, kind });
      if (r.data.riskState) setRisk(r.data.riskState);
      if (r.data.actions?.includes("pause_session")) {
        clearImage();
        setState({ kind: "revoked", reason: "session_paused" });
      }
    },
    [clearImage],
  );

  useEffect(() => {
    if (state.kind !== "showing") return;
    const onVis = () => document.visibilityState === "hidden" && void signal("visibility_hidden");
    const onBlur = () => void signal("focus_lost");
    const onPrint = () => void signal("print_attempt", 0);
    document.addEventListener("visibilitychange", onVis);
    window.addEventListener("blur", onBlur);
    window.addEventListener("beforeprint", onPrint);
    if ((navigator as Navigator & { webdriver?: boolean }).webdriver) void signal("automation_detected", 0);
    // Heuristic with false positives (docked side panels look the same); weighted low on the server.
    if (window.outerWidth - window.innerWidth > 240 || window.outerHeight - window.innerHeight > 240) void signal("devtools_suspected", 60_000);
    return () => {
      document.removeEventListener("visibilitychange", onVis);
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("beforeprint", onPrint);
    };
  }, [state.kind, signal]);

  const tiles = useMemo(() => {
    if (!permit || permit.watermark.density === "none") return 0;
    const spec = DENSITY_SPEC[permit.watermark.density];
    return (spec.columns + 1) * (spec.rows + 1);
  }, [permit]);

  const status =
    state.kind === "requesting"
      ? "Checking access…"
      : state.kind === "loading"
        ? "Preparing your watermarked copy…"
        : state.kind === "showing"
          ? `Showing a ${state.permit.classification.toLowerCase().replace("_", " ")} preview, watermarked with trace ${state.permit.watermark.seed}.`
          : state.kind === "step_up"
            ? "A stronger sign-in is required."
            : describe(state.reason);

  return (
    <div className={`viewer risk-${risk.toLowerCase()}`} data-risk={risk}>
      {/* Progress and success only; refusals are announced once, by their role="alert" notice. */}
      <p className="sr-only" aria-live="polite">
        {state.kind === "requesting" || state.kind === "loading" || state.kind === "showing" ? status : ""}
      </p>
      <div className="viewer-meta" aria-hidden="true">
        <span className={`mesh-dot mesh-${risk.toLowerCase()}`} /> Session risk: {risk}
        {permit && <span className="muted"> · expires {new Date(permit.expiresAt).toLocaleTimeString()}</span>}
      </div>

      {state.kind === "showing" && (
        <figure
          className="aegis-protected"
          aria-label={state.permit.altText}
          onContextMenu={(e) => {
            e.preventDefault();
            void signal("context_menu");
          }}
          onCopy={(e) => {
            e.preventDefault();
            void signal("copy_attempt");
          }}
          onDragStart={(e) => e.preventDefault()}
        >
          {/* eslint-disable-next-line @next/next/no-img-element -- blob URL of a single-use derivative */}
          <img src={state.url} alt={state.permit.altText} draggable={false} />
          {tiles > 0 && layout && (
            <div
              className={`watermark density-${state.permit.watermark.density}`}
              aria-hidden="true"
              style={{
                opacity: Math.min(0.5, layout.opacity * 2),
                transform: `translate(${layout.offsetXPct}%, ${layout.offsetYPct}%) rotate(${layout.angleDeg}deg) scale(${layout.scale})`,
              }}
            >
              {Array.from({ length: tiles }, (_, i) => (
                <span key={`${layout.nonce}-${i}`}>
                  {state.permit.watermark.lines[0]}
                  <br />
                  {state.permit.watermark.lines[1]}
                </span>
              ))}
            </div>
          )}
          <figcaption className="sr-only">
            This preview is watermarked with trace {state.permit.watermark.seed} and attributed to your account. {state.permit.altText}
          </figcaption>
        </figure>
      )}

      {state.kind === "step_up" && (
        <div className="notice" role="alert">
          <p>This asset needs a {state.requiredAuth.replace("_", "-")} sign-in.</p>
          {onStepUp && (
            <button type="button" className="btn" onClick={onStepUp}>
              Step up with passkey (development simulation)
            </button>
          )}
        </div>
      )}
      {(state.kind === "denied" || state.kind === "revoked") && (
        <p className={`notice ${state.kind === "revoked" ? "notice-critical" : ""}`} role="alert">
          {describe(state.reason)}
        </p>
      )}
      {(state.kind === "requesting" || state.kind === "loading") && <p className="muted">{status}</p>}
      <p className="print-notice">Printing protected content is disabled. This attempt was recorded.</p>
    </div>
  );
}
