// Security headers. Edge-safe (no Node imports): used by middleware.ts.

export function contentSecurityPolicy(nonce: string, dev: boolean, https = false): string {
  return [
    "default-src 'self'",
    // Next.js reads the nonce from this header and applies it to its own scripts.
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${dev ? " 'unsafe-eval'" : ""}`,
    `style-src 'self' 'nonce-${nonce}'${dev ? " 'unsafe-inline'" : ""}`,
    // React renders style attributes for the watermark transforms; attribute styles cannot run script.
    "style-src-attr 'unsafe-inline'",
    // Protected previews arrive as same-origin blobs; nothing is loaded from third parties.
    "img-src 'self' blob: data:",
    "font-src 'self'",
    "connect-src 'self'",
    "media-src 'none'",
    "object-src 'none'",
    "frame-src 'none'",
    "frame-ancestors 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "worker-src 'self'",
    ...(https ? ["upgrade-insecure-requests"] : []),
  ].join("; ");
}

export function securityHeaders(opts: { nonce: string; dev: boolean; https: boolean }): Record<string, string> {
  return {
    "Content-Security-Policy": contentSecurityPolicy(opts.nonce, opts.dev, opts.https),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    // display-capture=() stops script on this origin from calling getDisplayMedia.
    // It does not, and cannot, stop operating-system screenshots or cameras.
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), display-capture=(), clipboard-read=(), usb=(), payment=()",
    ...(opts.https ? { "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload" } : {}),
  };
}
