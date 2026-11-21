import sharp from "sharp";
import type { WatermarkDensity } from "./classification";
import { watermarkSvg, type WatermarkLayout } from "./watermark";

// Image handling for untrusted uploads and per-view derivatives.
// Uploads are parsed by libvips (sharp) with a pixel ceiling; derivatives are
// re-encoded, which drops EXIF/XMP metadata (camera, GPS) from what viewers get.

export const MAX_UPLOAD_BYTES = 15 * 1024 * 1024;
const MAX_INPUT_PIXELS = 40_000_000;
const MAX_DIMENSION = 8000;
const ALLOWED_FORMATS = new Map([
  ["png", "image/png"],
  ["jpeg", "image/jpeg"],
  ["webp", "image/webp"],
]);

export class ImageRejected extends Error {}

export async function inspectUpload(bytes: Buffer): Promise<{ contentType: string; width: number; height: number }> {
  if (bytes.length === 0 || bytes.length > MAX_UPLOAD_BYTES) throw new ImageRejected("image size out of bounds");
  let meta: Awaited<ReturnType<ReturnType<typeof sharp>["metadata"]>>;
  try {
    meta = await sharp(bytes, { limitInputPixels: MAX_INPUT_PIXELS, failOn: "error" }).metadata();
  } catch {
    throw new ImageRejected("image could not be parsed");
  }
  const contentType = meta.format ? ALLOWED_FORMATS.get(meta.format) : undefined;
  if (!contentType) throw new ImageRejected("only PNG, JPEG, and WebP are accepted");
  if (!meta.width || !meta.height || meta.width > MAX_DIMENSION || meta.height > MAX_DIMENSION) {
    throw new ImageRejected("image dimensions out of bounds");
  }
  return { contentType, width: meta.width, height: meta.height };
}

/**
 * 64-bit difference hash (dHash) as 16 hex chars. Tolerates resizing,
 * recompression, and colour or brightness changes. It does NOT tolerate heavy
 * cropping or rotation; leak matching reports such copies as inconclusive.
 */
export async function dHash(bytes: Buffer): Promise<string> {
  const px = await sharp(bytes, { limitInputPixels: MAX_INPUT_PIXELS }).rotate().grayscale().resize(9, 8, { fit: "fill" }).raw().toBuffer();
  let bits = "";
  for (let row = 0; row < 8; row++) {
    for (let col = 0; col < 8; col++) {
      bits += (px[row * 9 + col] as number) > (px[row * 9 + col + 1] as number) ? "1" : "0";
    }
  }
  return BigInt(`0b${bits}`).toString(16).padStart(16, "0");
}

export function hamming(a: string, b: string): number {
  let x = BigInt(`0x${a}`) ^ BigInt(`0x${b}`);
  let n = 0;
  while (x) {
    n += Number(x & 1n);
    x >>= 1n;
  }
  return n;
}

export interface DerivedPreview {
  bytes: Buffer;
  contentType: "image/webp";
  width: number;
  height: number;
  dhash: string;
}

/** Per-view derivative: resized to the policy ceiling, watermark burned in, metadata stripped. */
export async function derivePreview(
  original: Buffer,
  opts: { maxWidth: number; density: WatermarkDensity; lines: readonly string[]; layout: WatermarkLayout },
): Promise<DerivedPreview> {
  const resized = await sharp(original, { limitInputPixels: MAX_INPUT_PIXELS, failOn: "error" })
    .rotate()
    .resize({ width: opts.maxWidth, withoutEnlargement: true })
    .toBuffer({ resolveWithObject: true });
  const { width, height } = resized.info;
  let pipeline = sharp(resized.data);
  if (opts.density !== "none") {
    pipeline = pipeline.composite([{ input: Buffer.from(watermarkSvg(width, height, opts.lines, opts.layout, opts.density)), top: 0, left: 0 }]);
  }
  const bytes = await pipeline.webp({ quality: 82 }).toBuffer();
  return { bytes, contentType: "image/webp", width, height, dhash: await dHash(bytes) };
}
