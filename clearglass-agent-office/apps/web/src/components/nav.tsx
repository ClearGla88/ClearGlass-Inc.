"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export const NAV = [
  { href: "/", label: "Headquarters", code: "HQ" },
  { href: "/agents", label: "Agent Directory", code: "AG" },
  { href: "/missions", label: "Mission Control", code: "MC" },
  { href: "/floor", label: "Collaboration Floor", code: "CF" },
  { href: "/approvals", label: "Approval Desk", code: "AD" },
  { href: "/vault", label: "Knowledge Vault", code: "KV" },
  { href: "/simulations", label: "Simulation Chamber", code: "SC" },
  { href: "/briefing", label: "Briefing Room", code: "BR" },
  { href: "/audit", label: "Audit Ledger", code: "AL" },
];

export function NavLinks({ pending }: { pending: number }) {
  const path = usePathname();
  return (
    <nav aria-label="Office views" className="flex gap-1 overflow-x-auto lg:flex-col lg:overflow-visible">
      {NAV.map((item) => {
        const active = item.href === "/" ? path === "/" : path.startsWith(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={`group flex shrink-0 items-center gap-3 rounded-lg border px-3 py-2 text-sm transition ${
              active
                ? "border-accent/40 bg-accent/10 text-ink"
                : "border-transparent text-dim hover:border-line hover:bg-white/[0.04] hover:text-ink"
            }`}
          >
            <span className={`mono text-[0.65rem] ${active ? "text-accent" : "text-faint group-hover:text-dim"}`}>
              {item.code}
            </span>
            <span className="whitespace-nowrap">{item.label}</span>
            {item.href === "/approvals" && pending > 0 && (
              <span className="mono ml-auto rounded-full bg-warn/20 px-1.5 text-[0.65rem] text-warn">{pending}</span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}
