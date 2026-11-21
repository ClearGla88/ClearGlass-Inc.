// Visible watermark: payload text, per-epoch layout, and an SVG renderer.
//
// Isomorphic on purpose. The server burns a watermark into every derived
// preview with watermarkSvg(), and the browser overlay recomputes the same
// layout family every rotation period with layoutFor(). Layout seeds are not
// secrets; the watermark's job is attribution, not concealment.

import type { Classification, WatermarkDensity } from "./classification";

export interface WatermarkPayload {
  classification: Classification;
  tenantPseudonym: string;
  viewerPseudonym: string;
  sessionFragment: string;
  traceToken: string;
  /** ISO timestamp of the view. Rendered to the minute. */
  issuedAt: string;
}

export interface DensitySpec {
  columns: number;
  rows: number;
  opacity: number;
  fontPx: number;
  rotationSeconds: number;
}

export const DENSITY_SPEC: Readonly<Record<Exclude<WatermarkDensity, "none">, DensitySpec>> = Object.freeze({
  light: { columns: 3, rows: 4, opacity: 0.1, fontPx: 12, rotationSeconds: 30 },
  standard: { columns: 4, rows: 6, opacity: 0.14, fontPx: 13, rotationSeconds: 20 },
  dense: { columns: 6, rows: 9, opacity: 0.2, fontPx: 14, rotationSeconds: 10 },
});

export const rotationSecondsFor = (density: WatermarkDensity): number =>
  density === "none" ? 0 : DENSITY_SPEC[density].rotationSeconds;

/** Two lines per tile. Pseudonyms and the trace token only: never an email, IP address, or name. */
export function watermarkLines(p: WatermarkPayload): [string, string] {
  const minute = p.issuedAt.slice(0, 16).replace("T", " ") + "Z";
  return [
    `${p.classification.replace("_", " ")} · ${p.tenantPseudonym} · ${p.viewerPseudonym} · ${p.sessionFragment}`,
    `TRACE ${p.traceToken} · ${minute}`,
  ];
}

export interface WatermarkLayout {
  offsetXPct: number;
  offsetYPct: number;
  angleDeg: number;
  scale: number;
  opacity: number;
  nonce: string;
}

export const epochFor = (nowMs: number, rotationSeconds: number): number =>
  rotationSeconds > 0 ? Math.floor(nowMs / (rotationSeconds * 1000)) : 0;

// FNV-1a then mulberry32: small, deterministic, identical in Node and browsers.
function fnv1a(input: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}

function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Position, angle, scale, and opacity shift every epoch, so a single crop rarely removes every tile. */
export function layoutFor(seed: string, epoch: number, density: WatermarkDensity): WatermarkLayout {
  const spec = density === "none" ? null : DENSITY_SPEC[density];
  const rand = mulberry32(fnv1a(`${seed}:${epoch}:${density}`));
  const between = (lo: number, hi: number) => lo + (hi - lo) * rand();
  return {
    offsetXPct: Math.round(between(0, 100 / (spec?.columns ?? 1)) * 100) / 100,
    offsetYPct: Math.round(between(0, 100 / (spec?.rows ?? 1)) * 100) / 100,
    angleDeg: Math.round(between(-38, -22) * 10) / 10,
    scale: Math.round(between(0.9, 1.15) * 1000) / 1000,
    opacity: spec ? Math.round(spec.opacity * between(0.85, 1.15) * 1000) / 1000 : 0,
    nonce: Math.floor(rand() * 0xffff)
      .toString(16)
      .padStart(4, "0"),
  };
}

const escapeXml = (s: string): string =>
  s.replace(/[<>&"']/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;", "'": "&apos;" })[c] as string);

/** SVG of tiled, rotated watermark text, sized to the image it will be composited onto. */
export function watermarkSvg(
  width: number,
  height: number,
  lines: readonly string[],
  layout: WatermarkLayout,
  density: WatermarkDensity,
): string {
  if (density === "none") return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"/>`;
  const spec = DENSITY_SPEC[density];
  const font = Math.max(10, Math.round(spec.fontPx * layout.scale * Math.max(1, width / 1200)));
  const cellW = width / spec.columns;
  const cellH = height / spec.rows;
  const ox = (layout.offsetXPct / 100) * width;
  const oy = (layout.offsetYPct / 100) * height;
  const tiles: string[] = [];
  for (let r = -1; r <= spec.rows; r++) {
    for (let c = -1; c <= spec.columns; c++) {
      const x = Math.round(c * cellW + ox + (r % 2 ? cellW / 2 : 0));
      const y = Math.round(r * cellH + oy);
      const text = lines
        .map((line, i) => `<tspan x="${x}" dy="${i === 0 ? 0 : font * 1.3}">${escapeXml(line)}</tspan>`)
        .join("");
      tiles.push(`<text x="${x}" y="${y}" transform="rotate(${layout.angleDeg} ${x} ${y})">${text}</text>`);
    }
  }
  // Light and dark strokes together keep the mark legible on both bright and dark content.
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">` +
    `<g font-family="DejaVu Sans Mono, Menlo, Consolas, monospace" font-size="${font}" font-weight="600" ` +
    `fill="#ffffff" fill-opacity="${layout.opacity}" stroke="#04111c" stroke-opacity="${layout.opacity}" ` +
    `stroke-width="0.6" paint-order="stroke">${tiles.join("")}</g></svg>`
  );
}
