import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "Aegis Glass",
  description: "Protected, attributable previews for confidential concept work.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: "#07131f",
  colorScheme: "dark",
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  // Reading request headers makes every page dynamic, which the per-request CSP nonce requires.
  await headers();
  return (
    <html lang="en">
      <body>
        <a className="skip-link" href="#content">
          Skip to content
        </a>
        <div id="content">{children}</div>
      </body>
    </html>
  );
}
