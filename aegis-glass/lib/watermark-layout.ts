// Watermark geometry shared by the server (burned into every preview) and the
// browser (the overlay drawn above it). Pure functions only: no Node or DOM
// APIs, so the client bundle can import this file.
//
// The burned-in mark is the attribution evidence. The overlay is a deterrent
// that keeps moving even while the same preview stays on screen.

export const ROTATE_SECONDS = 20;

/** Tile edge in CSS pixels per density level (index 0 = no watermark). */
export const DENSITY_TILE = [0, 560, 440, 340, 260] as const;
export const DENSITY_OPACITY = [0, 0.16, 0.2, 0.24, 0.28] as const;

export interface WatermarkLayout {
  /** Fractions of the tile size, 0..1. */
  offsetX: number;
  offsetY: number;
  /** Degrees. */
  angle: number;
  /** Multiplier on the base font size. */
  scale: number;
  opacity: number;
}

/** Small deterministic PRNG. Not cryptographic; the seed is not a secret. */
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

export function epochAt(ms: number): number {
  return Math.floor(ms / (ROTATE_SECONDS * 1000));
}

export function clampDensity(density: number): number {
  if (!Number.isFinite(density)) return 4;
  return Math.max(0, Math.min(4, Math.round(density)));
}

export function layoutFor(seed: number, epoch: number, density: number): WatermarkLayout {
  const d = clampDensity(density);
  const rand = mulberry32((seed ^ Math.imul(epoch, 0x9e3779b1)) >>> 0);
  const baseOpacity = DENSITY_OPACITY[d];
  return {
    offsetX: rand(),
    offsetY: rand(),
    angle: -38 + rand() * 16,
    scale: 0.9 + rand() * 0.25,
    opacity: d === 0 ? 0 : Math.min(0.4, baseOpacity + rand() * 0.04),
  };
}

export function escapeXml(text: string): string {
  return text.replace(/[<>&"']/g, (ch) => {
    switch (ch) {
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      case "&":
        return "&amp;";
      case '"':
        return "&quot;";
      default:
        return "&apos;";
    }
  });
}

function tileContent(lines: string[], layout: WatermarkLayout, tile: number): string {
  const fontSize = Math.round(13 * layout.scale);
  const cx = tile / 2;
  const cy = tile / 2;
  const lineGap = Math.round(fontSize * 1.35);
  const firstY = cy - ((lines.length - 1) * lineGap) / 2;
  const texts = lines
    .map(
      (line, i) =>
        `<text x="${cx}" y="${firstY + i * lineGap}" text-anchor="middle">${escapeXml(line)}</text>`,
    )
    .join("");
  // White fill with a dark outline stays legible on light and dark content.
  return (
    `<g transform="rotate(${layout.angle.toFixed(2)} ${cx} ${cy})" font-family="DejaVu Sans Mono, Menlo, Consolas, monospace" ` +
    `font-size="${fontSize}" font-weight="600" fill="#ffffff" fill-opacity="${layout.opacity.toFixed(3)}" ` +
    `stroke="#0b1f33" stroke-opacity="${(layout.opacity * 0.9).toFixed(3)}" stroke-width="0.6" paint-order="stroke">` +
    texts +
    `</g>`
  );
}

/** One repeating tile, for a CSS background in the browser overlay. */
export function watermarkTileSvg(lines: string[], layout: WatermarkLayout, density: number): string {
  const d = clampDensity(density);
  if (d === 0) return "";
  const tile = DENSITY_TILE[d];
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${tile}" height="${tile}" viewBox="0 0 ${tile} ${tile}">${tileContent(lines, layout, tile)}</svg>`;
}

/** Full-size overlay for compositing onto a raster preview on the server. */
export function watermarkOverlaySvg(
  width: number,
  height: number,
  lines: string[],
  layout: WatermarkLayout,
  density: number,
): string {
  const d = clampDensity(density);
  if (d === 0) return "";
  const tile = DENSITY_TILE[d];
  const ox = (layout.offsetX * tile).toFixed(1);
  const oy = (layout.offsetY * tile).toFixed(1);
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">` +
    `<defs><pattern id="wm" width="${tile}" height="${tile}" patternUnits="userSpaceOnUse" patternTransform="translate(${ox} ${oy})">` +
    tileContent(lines, layout, tile) +
    `</pattern></defs><rect width="100%" height="100%" fill="url(#wm)"/></svg>`
  );
}
