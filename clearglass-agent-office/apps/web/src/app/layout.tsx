import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { CanActProvider } from "@/components/actions";
import { EmergencyControl } from "@/components/emergency";
import { LoginGate } from "@/components/login";
import { Motion } from "@/components/motion";
import { NavLinks } from "@/components/nav";
import { Chip } from "@/components/ui";
import { authMode, isAuthed } from "@/lib/session";
import { getSnapshot } from "@/lib/snapshot";
import "./globals.css";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "ClearGlass Agent Office",
  description: "The governed headquarters where ClearGlass Inc.'s AI agents work, with humans in control.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { themeColor: "#04070c", width: "device-width", initialScale: 1 };

export default async function RootLayout({ children }: { children: ReactNode }) {
  const mode = authMode();
  const authed = await isAuthed();
  if (mode === "required" && !authed) {
    return (
      <html lang="en">
        <body><LoginGate /></body>
      </html>
    );
  }
  const { snap, live, note } = await getSnapshot();
  const can = live && authed && mode !== "locked";
  const why = !live
    ? "Offline snapshot: set OFFICE_API_URL to act"
    : mode === "locked"
      ? "Console locked: set OFFICE_CONSOLE_PASSPHRASE and OFFICE_SESSION_SECRET"
      : "";
  const pending = snap.approvals.filter((a) => a.status === "pending").length;
  const chain = snap.audit.verify;

  return (
    <html lang="en">
      <body>
        <a href="#main" className="skip-link">Skip to content</a>
        <Motion>
          <CanActProvider can={can} why={why}>
            <div className="mx-auto flex min-h-dvh max-w-[1600px] flex-col lg:flex-row">
              <aside className="border-b border-line px-4 py-4 lg:sticky lg:top-0 lg:h-dvh lg:w-64 lg:shrink-0 lg:border-b-0 lg:border-r lg:py-6">
                <div className="mb-4 lg:mb-8">
                  <p className="mono text-[0.7rem] tracking-[0.3em] text-accent">CLEARGLASS</p>
                  <p className="mt-1 text-lg font-semibold tracking-tight">Agent Office</p>
                  <p className="mt-1 text-xs text-faint">{snap.company.tagline}</p>
                </div>
                <NavLinks pending={pending} />
                <p className="mono mt-8 hidden text-[0.62rem] leading-relaxed text-faint lg:block">
                  {snap.company.brand_line}
                  <br />
                  policy {snap.policy.version}
                </p>
              </aside>

              <div className="min-w-0 flex-1">
                <header className="sticky top-0 z-30 flex flex-wrap items-center gap-2 border-b border-line bg-bg/70 px-4 py-3 backdrop-blur-md sm:px-6">
                  <Chip color={live ? "var(--cg-ok)" : "var(--cg-warn)"}>{live ? "live api" : "offline snapshot"}</Chip>
                  <Chip color={mode === "open-dev" ? "var(--cg-warn)" : mode === "locked" ? "var(--cg-bad)" : "var(--cg-ok)"}>
                    {mode === "open-dev" ? "dev · no sign-in" : mode === "locked" ? "locked" : "operator signed in"}
                  </Chip>
                  <Chip color={chain.ok ? "var(--cg-ok)" : "var(--cg-bad)"} title={`head ${chain.head}`}>
                    audit {chain.ok ? "verified" : `broken at #${chain.broken_at}`} · {chain.count}
                  </Chip>
                  <span className="mono hidden text-[0.68rem] text-faint md:inline">as of {snap.generated_at.replace("T", " ").slice(0, 16)} UTC</span>
                  <div className="ml-auto">
                    <EmergencyControl halted={snap.emergency.halted} reason={snap.emergency.reason} />
                  </div>
                </header>
                {snap.emergency.halted && (
                  <div role="alert" className="border-b border-bad/40 bg-bad/10 px-6 py-2 text-sm text-bad">
                    Emergency stop engaged: {snap.emergency.reason}. Every agent is paused and no action can execute.
                  </div>
                )}
                {(note || !live) && (
                  <div className="border-b border-line bg-warn/5 px-6 py-2 text-xs text-warn">
                    {note ?? "Showing the committed demo snapshot (fictional sample data). Actions need a running API."}
                  </div>
                )}
                <main id="main" className="px-4 py-6 sm:px-6">{children}</main>
              </div>
            </div>
          </CanActProvider>
        </Motion>
      </body>
    </html>
  );
}
