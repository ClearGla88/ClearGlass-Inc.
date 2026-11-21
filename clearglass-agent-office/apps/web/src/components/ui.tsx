import type { ReactNode } from "react";

export const STATUS_COLOR: Record<string, string> = {
  idle: "var(--cg-muted)",
  working: "var(--cg-accent)",
  running: "var(--cg-accent)",
  waiting_for_approval: "var(--cg-warn)",
  waiting_approval: "var(--cg-warn)",
  pending: "var(--cg-muted)",
  blocked: "var(--cg-bad)",
  failed: "var(--cg-bad)",
  completed: "var(--cg-ok)",
  executed: "var(--cg-ok)",
  approved: "var(--cg-ok)",
  paused: "var(--cg-paused)",
  retired: "var(--cg-ink-faint)",
  cancelled: "var(--cg-ink-faint)",
  rejected: "var(--cg-bad)",
  expired: "var(--cg-ink-faint)",
  active: "var(--cg-accent)",
  stalled: "var(--cg-bad)",
};

export const TIER_COLOR: Record<string, string> = {
  low: "var(--cg-ok)",
  medium: "var(--cg-info)",
  high: "var(--cg-warn)",
  critical: "var(--cg-bad)",
  info: "var(--cg-muted)",
};

export function label(s: string): string {
  return s.replace(/_/g, " ");
}

export function Panel({ title, kicker, actions, children, className = "" }: {
  title?: ReactNode; kicker?: string; actions?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={`glass glass-edge p-4 sm:p-5 ${className}`}>
      {(title || kicker || actions) && (
        <header className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <div>
            {kicker && <p className="label">{kicker}</p>}
            {title && <h2 className="mt-0.5 text-[0.95rem] font-semibold tracking-tight text-ink">{title}</h2>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function PageHeader({ kicker, title, children }: { kicker: string; title: string; children?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <p className="label">{kicker}</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight sm:text-[1.7rem]">{title}</h1>
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

export function Dot({ status, title }: { status: string; title?: string }) {
  const color = STATUS_COLOR[status] ?? "var(--cg-muted)";
  return (
    <span
      role="img"
      aria-label={title ?? label(status)}
      title={title ?? label(status)}
      className={`inline-block size-2.5 shrink-0 rounded-full ${status === "working" || status === "running" ? "pulse" : ""}`}
      style={{ background: color, boxShadow: `0 0 10px ${color}` }}
    />
  );
}

export function Chip({ children, color, title }: { children: ReactNode; color?: string; title?: string }) {
  const c = color ?? "var(--cg-ink-dim)";
  return (
    <span
      title={title}
      className="mono inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[0.68rem] leading-5"
      style={{ color: c, borderColor: `color-mix(in srgb, ${c} 40%, transparent)`, background: `color-mix(in srgb, ${c} 10%, transparent)` }}
    >
      {children}
    </span>
  );
}

export function StatusChip({ status }: { status: string }) {
  return <Chip color={STATUS_COLOR[status]}>{label(status)}</Chip>;
}

export function TierChip({ tier }: { tier: string }) {
  return <Chip color={TIER_COLOR[tier]} title={`risk tier: ${tier}`}>{tier}</Chip>;
}

export function Stat({ label: l, value, hint, tone }: { label: string; value: ReactNode; hint?: string; tone?: string }) {
  return (
    <div className="glass px-4 py-3">
      <p className="label">{l}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums" style={tone ? { color: tone } : undefined}>{value}</p>
      {hint && <p className="mt-0.5 text-xs text-faint">{hint}</p>}
    </div>
  );
}

export function NoData({ children = "No data yet" }: { children?: ReactNode }) {
  return <span className="text-faint">{children}</span>;
}

export function pct(v: number | null | undefined): ReactNode {
  return v === null || v === undefined ? <NoData>no data</NoData> : `${Math.round(v * 100)}%`;
}

export function when(iso: string | null | undefined): string {
  if (!iso) return "";
  return `${iso.slice(0, 10)} ${iso.slice(11, 16)} UTC`;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-lg border border-dashed border-line px-3 py-4 text-sm text-faint">{children}</p>;
}

export function Json({ value, max = 4000 }: { value: unknown; max?: number }) {
  const text = JSON.stringify(value, null, 2) ?? "";
  return (
    <pre className="mono max-h-72 overflow-auto rounded-lg border border-line bg-black/30 p-3 text-[0.72rem] leading-relaxed text-dim">
      {text.length > max ? `${text.slice(0, max)}\n…` : text}
    </pre>
  );
}
