import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // sharp is a native module; keep it out of the server bundle.
  serverExternalPackages: ["sharp"],
  images: { unoptimized: true },
};

export default config;
