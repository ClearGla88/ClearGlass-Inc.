import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // This package lives inside a larger repository; trace files from here only.
  outputFileTracingRoot: fileURLToPath(new URL(".", import.meta.url)),
  // Native / WASM packages stay outside the server bundle.
  serverExternalPackages: ["sharp", "@electric-sql/pglite", "pg"],
  images: { unoptimized: true },
};

export default nextConfig;
