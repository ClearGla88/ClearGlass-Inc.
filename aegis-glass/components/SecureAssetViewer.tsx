"use client";

// Renders one protected preview.
//
// What it does: fetches a single-use capability, fetches the preview exactly
// once into a blob URL, refreshes both every rotation period (so the burned-in
// watermark moves and an expired grant or revoked session takes effect within
// seconds), and draws a moving overlay on top.
//
// What it does not do: stop screenshots or cameras. Nothing in a browser can.
// The context-menu, drag, selection and print rules below are friction only;
// attribution comes from the server-side watermark and the signed receipt.

import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { apiPost, errorCode } from "../lib/client-api.ts";
import { clampDensity, DENSITY_TILE, epochAt, layoutFor, watermarkTileSvg } from "../lib/watermark-layout.ts";

export interface CapabilityGrant {
  url: string;
  expiresAt: string;
  title: string;
  altText: string;
  classification: string;
  riskState: "LOW" | "GUARDED" | "HIGH" | "CRITICAL";
  previewMaxWidth: number;
  watermark: { lines: string[]; seed: number; density: number; rotateSeconds: number };
}

type BlockReason = "step_up" | "revoked" | "paused" | "forbidden" | "missing" | "error";

type View = { kind: "loading" } | { kind: "ready"; grant: CapabilityGrant; src: string } | { kind: "blocked"; reason: BlockReason };

const BLOCK_TEXT: Record<BlockReason, { title: string; body: string }> = {
  step_up: { title: "Verify it's you", body: "This item needs a recent passkey sign-in." },
  revoked: { title: "Access ended", body: "This session was signed out or revoked. Sign in again to continue." },
  paused: { title: "Session paused", body: "Unusual activity paused this session. A reviewer has been notified; sign in again to continue." },
  forbidden: { title: "Not available to you", body: "You don't have access to this item right now." },
  missing: { title: "Not found", body: "This item doesn't exist or isn't shared with you." },
  error: { title: "Couldn't load the preview", body: "Try again in a moment." },
};

function reasonFor(status: number, code: string | undefined): BlockReason {
  if (code === "step_up_required") return "step_up";
  if (code === "session_paused") return "paused";
  if (code === "session_revoked" || code === "unauthenticated" || status === 401) return "revoked";
  if (status === 404) return "missing";
  if (status === 403) return "forbidden";
  return "error";
}

export interface SecureAssetViewerProps {
  assetId: string;
  onStepUp?: () => void;
  onRiskChange?: (risk: CapabilityGrant["riskState"]) => void;
}

export function SecureAssetViewer({ assetId, onStepUp, onRiskChange }: SecureAssetViewerProps) {
  const [view, setView] = useState<View>({ kind: "loading" });
  const [epoch, setEpoch] = useState(() => epochAt(Date.now()));
  const [shielded, setShielded] = useState(false);
  const [notice, setNotice] = useState("");
  const [announcement, setAnnouncement] = useState("Loading protected preview.");
  const blobUrl = useRef<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const generation = useRef(0);
  const lastKind = useRef<View["kind"]>("loading");

  const clearTimer = () => {
    if (timer.current !== undefined) clearTimeout(timer.current);
    timer.current = undefined;
  };

  const block = useCallback((reason: BlockReason) => {
    clearTimer();
    if (blobUrl.current) URL.revokeObjectURL(blobUrl.current);
    blobUrl.current = null;
    setView({ kind: "blocked", reason });
    setAnnouncement(`${BLOCK_TEXT[reason].title}. ${BLOCK_TEXT[reason].body}`);
    lastKind.current = "blocked";
  }, []);

  const load = useCallback(async () => {
    clearTimer();
    const gen = ++generation.current;
    try {
      const cap = await apiPost<CapabilityGrant>(`/api/assets/${encodeURIComponent(assetId)}/capability`);
      if (gen !== generation.current) return;
      if (cap.status === 429) {
        setNotice("Too many requests. Retrying shortly.");
        timer.current = setTimeout(load, 30_000);
        return;
      }
      if (!cap.ok) return block(reasonFor(cap.status, errorCode(cap.data)));
      const grant = cap.data;

      const media = await fetch(grant.url, { credentials: "same-origin", cache: "no-store" });
      if (gen !== generation.current) return;
      if (!media.ok) {
        let code: string | undefined;
        try {
          code = errorCode(await media.json());
        } catch {
          code = undefined;
        }
        if (media.status === 410 || media.status === 429) {
          timer.current = setTimeout(load, 5_000);
          return;
        }
        return block(reasonFor(media.status, code));
      }
      const blob = await media.blob();
      if (gen !== generation.current) return;

      const previous = blobUrl.current;
      blobUrl.current = URL.createObjectURL(blob);
      setView({ kind: "ready", grant, src: blobUrl.current });
      setEpoch(epochAt(Date.now()));
      setNotice("");
      onRiskChange?.(grant.riskState);
      if (lastKind.current !== "ready") setAnnouncement(`Preview loaded. Classification ${grant.classification}.`);
      lastKind.current = "ready";
      // Release the old image after the new one has had a chance to paint.
      if (previous) setTimeout(() => URL.revokeObjectURL(previous), 2_000);
      timer.current = setTimeout(load, grant.watermark.rotateSeconds * 1000);
    } catch {
      if (gen === generation.current) block("error");
    }
  }, [assetId, block, onRiskChange]);

  useEffect(() => {
    setView({ kind: "loading" });
    lastKind.current = "loading";
    void load();
    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        setShielded(true);
        clearTimer();
      } else {
        setShielded(false);
        void load();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      generation.current += 1;
      clearTimer();
      document.removeEventListener("visibilitychange", onVisibility);
      if (blobUrl.current) URL.revokeObjectURL(blobUrl.current);
      blobUrl.current = null;
    };
  }, [load]);

  const ready = view.kind === "ready" ? view : undefined;
  let overlayStyle: CSSProperties | undefined;
  if (ready) {
    const { lines, seed, density } = ready.grant.watermark;
    const d = clampDensity(density);
    if (d > 0) {
      // A different seed from the burned-in mark, so the two layers interleave.
      const layout = layoutFor((seed ^ 0x5bd1e995) >>> 0, epoch, d);
      const tile = DENSITY_TILE[d];
      overlayStyle = {
        backgroundImage: `url("data:image/svg+xml,${encodeURIComponent(watermarkTileSvg(lines, layout, d))}")`,
        backgroundSize: `${tile}px ${tile}px`,
        backgroundPosition: `${Math.round(layout.offsetX * tile)}px ${Math.round(layout.offsetY * tile)}px`,
      };
    }
  }

  return (
    <figure className="viewer" data-risk={ready?.grant.riskState ?? "LOW"} data-shielded={shielded ? "true" : "false"}>
      <div
        className="viewer-stage"
        onContextMenu={(e) => e.preventDefault()}
        onDragStart={(e) => e.preventDefault()}
        style={ready ? { maxWidth: ready.grant.previewMaxWidth } : undefined}
      >
        {view.kind === "loading" && <div className="viewer-placeholder" aria-hidden="true" />}
        {ready && (
          <>
            <img className="viewer-image" src={ready.src} alt={ready.grant.altText} draggable={false} />
            {overlayStyle && <div className="viewer-overlay" style={overlayStyle} aria-hidden="true" />}
          </>
        )}
        {shielded && ready && (
          <div className="viewer-shield" aria-hidden="true">
            Hidden while this tab is in the background
          </div>
        )}
        {view.kind === "blocked" && (
          <div className="viewer-blocked">
            <p className="viewer-blocked-title">{BLOCK_TEXT[view.reason].title}</p>
            <p>{BLOCK_TEXT[view.reason].body}</p>
            {view.reason === "step_up" && onStepUp && (
              <button type="button" className="btn btn-primary" onClick={onStepUp}>
                Verify with passkey
              </button>
            )}
            {view.reason === "error" && (
              <button type="button" className="btn" onClick={() => void load()}>
                Try again
              </button>
            )}
          </div>
        )}
      </div>
      <figcaption className="viewer-caption">
        {ready ? (
          <>
            <span className="badge" data-class={ready.grant.classification}>
              {ready.grant.classification}
            </span>
            <span className="viewer-title">{ready.grant.title}</span>
            <span className="viewer-meta">
              Session risk <strong data-risk={ready.grant.riskState}>{ready.grant.riskState}</strong> · access renews every{" "}
              {ready.grant.watermark.rotateSeconds}s
            </span>
          </>
        ) : (
          <span className="viewer-meta">Protected preview</span>
        )}
        {notice && <span className="viewer-notice">{notice}</span>}
      </figcaption>
      <p className="visually-hidden" role="status" aria-live="polite">
        {announcement}
      </p>
    </figure>
  );
}
