// Security headers. Edge-safe: no Node APIs, so middleware can import it.

export function contentSecurityPolicy(nonce: string, opts: { dev: boolean }): string {
  const scriptSrc = ["'self'", `'nonce-${nonce}'`, "'strict-dynamic'"];
  // React Fast Refresh needs eval in `next dev` only.
  if (opts.dev) scriptSrc.push("'unsafe-eval'");
  return [
    "default-src 'self'",
    `script-src ${scriptSrc.join(" ")}`,
    // Inline style attributes position the watermark overlay. Style injection is
    // far weaker than script injection, and scripts stay nonce-locked.
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    "connect-src 'self'",
    "media-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "worker-src 'self'",
    "manifest-src 'self'",
    ...(opts.dev ? [] : ["upgrade-insecure-requests"]),
  ].join("; ");
}

export const BASE_SECURITY_HEADERS: Record<string, string> = {
  "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Referrer-Policy": "no-referrer",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=(), display-capture=()",
  "Cross-Origin-Opener-Policy": "same-origin",
  "Cross-Origin-Resource-Policy": "same-origin",
};

/** Applied to every protected preview response. */
export const MEDIA_HEADERS: Record<string, string> = {
  "Cache-Control": "no-store, private, max-age=0",
  Pragma: "no-cache",
  Expires: "0",
  "Content-Disposition": 'inline; filename="preview.webp"',
  "X-Content-Type-Options": "nosniff",
  "Cross-Origin-Resource-Policy": "same-origin",
  "Referrer-Policy": "no-referrer",
  "X-Robots-Tag": "noindex, nofollow, noarchive",
};

export const API_HEADERS: Record<string, string> = {
  "Cache-Control": "no-store, private, max-age=0",
  "X-Content-Type-Options": "nosniff",
};

/** Header that every state-changing browser request must carry (CSRF defence, with SameSite=Strict and the Origin check). */
export const CSRF_HEADER = "x-aegis-request";
export const CSRF_HEADER_VALUE = "1";
