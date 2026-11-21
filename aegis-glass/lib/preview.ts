// Derived previews. The master original never leaves the server: every view
// gets a fresh, downscaled raster with the watermark burned in and all
// metadata stripped. A perceptual hash (dHash) of each served preview is kept so
// that a leaked copy, even resized or recompressed, can be matched later.

import { createHash } from "node:crypto";
import sharp from "sharp";
import { watermarkOverlaySvg, type WatermarkLayout } from "./watermark-layout.ts";

export interface RenderedPreview {
  bytes: Buffer;
  mime: "image/webp";
  width: number;
  height: number;
  sha256: string;
  dhash: string;
}

export interface RenderOptions {
  maxWidth: number;
  lines: string[];
  layout: WatermarkLayout;
  density: number;
}

export async function renderPreview(original: Buffer, opts: RenderOptions): Promise<RenderedPreview> {
  // limitInputPixels guards against decompression bombs in uploaded originals.
  const resized = await sharp(original, { limitInputPixels: 64_000_000, failOn: "error" })
    .rotate()
    .resize({ width: opts.maxWidth, withoutEnlargement: true })
    .toBuffer({ resolveWithObject: true });

  const { width, height } = resized.info;
  const overlay = watermarkOverlaySvg(width, height, opts.lines, opts.layout, opts.density);
  let pipeline = sharp(resized.data);
  if (overlay) pipeline = pipeline.composite([{ input: Buffer.from(overlay), top: 0, left: 0 }]);
  // sharp drops EXIF, XMP and ICC metadata unless withMetadata() is called.
  const bytes = await pipeline.webp({ quality: 80 }).toBuffer();

  return {
    bytes,
    mime: "image/webp",
    width,
    height,
    sha256: createHash("sha256").update(bytes).digest("hex"),
    dhash: await dhash(bytes),
  };
}

/** 64-bit difference hash as 16 hex characters. */
export async function dhash(image: Buffer): Promise<string> {
  const pixels = await sharp(image).greyscale().resize(9, 8, { fit: "fill" }).raw().toBuffer();
  let bits = 0n;
  for (let row = 0; row < 8; row += 1) {
    for (let col = 0; col < 8; col += 1) {
      const left = pixels[row * 9 + col];
      const right = pixels[row * 9 + col + 1];
      bits = (bits << 1n) | (left > right ? 1n : 0n);
    }
  }
  return bits.toString(16).padStart(16, "0");
}

export function hammingDistance(a: string, b: string): number {
  let x = BigInt(`0x${a}`) ^ BigInt(`0x${b}`);
  let count = 0;
  while (x > 0n) {
    count += Number(x & 1n);
    x >>= 1n;
  }
  return count;
}

/** Evidence grades used in the leak-intake workflow. Thresholds are starting points to calibrate. */
export function matchGrade(distance: number): "likely_match" | "possible_match" | "inconclusive" {
  if (distance <= 6) return "likely_match";
  if (distance <= 12) return "possible_match";
  return "inconclusive";
}
