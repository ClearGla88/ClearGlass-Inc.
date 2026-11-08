import type { TraceStep } from "@/lib/types";

const STATE_COLOR: Record<string, string> = {
  pass: "var(--cg-ok)", fail: "var(--cg-bad)", pending: "var(--cg-warn)", skipped: "var(--cg-ink-faint)",
};

export function Trace({ steps }: { steps: TraceStep[] }) {
  return (
    <ol className="space-y-1">
      {steps.map((s) => (
        <li key={s.step} className="grid grid-cols-[1.25rem_8.5rem_minmax(0,1fr)] items-start gap-2 text-[0.72rem]">
          <span className="mono text-faint">{s.step}</span>
          <span className="mono" style={{ color: STATE_COLOR[s.state] }}>{s.name.replace(/_/g, " ")}</span>
          <span className="text-dim">{s.detail}</span>
        </li>
      ))}
    </ol>
  );
}
