import Link from "next/link";
import { Chip, Empty, PageHeader, Panel, when } from "@/components/ui";
import { getSnapshot } from "@/lib/snapshot";

const KIND_COLOR: Record<string, string> = {
  handoff: "var(--cg-accent)", assignment: "var(--cg-accent-2)", escalation: "var(--cg-warn)",
  review: "var(--cg-info)", report: "var(--cg-ok)", decision: "var(--cg-ok)", meeting_summary: "var(--cg-paused)",
  notification: "var(--cg-bad)", note: "var(--cg-ink-dim)",
};

export default async function FloorPage({ searchParams }: { searchParams: Promise<{ kind?: string }> }) {
  const { snap } = await getSnapshot();
  const { kind } = await searchParams;
  const who = (id: string) => {
    const a = snap.agents.find((x) => x.id === id);
    if (a) return `${a.callsign} ${a.name}`;
    return id === "operator" || id.startsWith("operator.") ? "Operator" : id === "all" ? "All agents" : id;
  };
  const messages = snap.messages.filter((m) => !kind || m.kind === kind);
  const threads = new Map<string, typeof messages>();
  for (const m of [...messages].reverse()) threads.set(m.thread_id, [...(threads.get(m.thread_id) ?? []), m]);
  const missionTitle = Object.fromEntries(snap.missions.map((m) => [m.id, m.title]));
  const kinds = [...new Set(snap.messages.map((m) => m.kind))].sort();

  return (
    <>
      <PageHeader kicker={`${snap.messages.length} messages · ${threads.size} threads`} title="Collaboration Floor" />
      <nav aria-label="Filter by message kind" className="mb-4 flex flex-wrap gap-2">
        <Link href="/floor" className={`rounded-full border px-3 py-1 text-xs ${!kind ? "border-accent/50 text-accent" : "border-line text-dim"}`}>All</Link>
        {kinds.map((k) => (
          <Link key={k} href={`/floor?kind=${k}`}
            className={`rounded-full border px-3 py-1 text-xs ${kind === k ? "border-accent/50 text-accent" : "border-line text-dim hover:text-ink"}`}>
            {k.replace(/_/g, " ")}
          </Link>
        ))}
      </nav>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="space-y-4">
          {threads.size === 0 && <Empty>No messages yet.</Empty>}
          {[...threads.entries()].map(([thread, items]) => (
            <Panel key={thread} kicker="Thread" title={missionTitle[thread] ?? thread.replace(/-/g, " ")}>
              <ol className="space-y-3">
                {items.map((m) => (
                  <li key={m.id} className="grid grid-cols-[auto_minmax(0,1fr)] gap-3">
                    <span className="mt-1.5 size-2 rounded-full" style={{ background: KIND_COLOR[m.kind] ?? "var(--cg-muted)" }} />
                    <div>
                      <div className="flex flex-wrap items-center gap-2 text-xs">
                        <span className="text-ink">{who(m.sender)}</span>
                        <span className="text-faint">→ {who(m.recipient)}</span>
                        <Chip color={KIND_COLOR[m.kind]}>{m.kind.replace(/_/g, " ")}</Chip>
                        <span className="mono text-faint">{when(m.created_at)}</span>
                      </div>
                      <p className="mt-1 text-sm font-medium">{m.subject}</p>
                      {m.body && <p className="mt-0.5 whitespace-pre-line text-sm text-dim">{m.body}</p>}
                    </div>
                  </li>
                ))}
              </ol>
            </Panel>
          ))}
        </div>
        <Panel kicker="Decision records" title={`${snap.decisions.length} recorded`} className="h-fit">
          {snap.decisions.length === 0 ? <Empty>No decisions yet.</Empty> : (
            <ul className="space-y-3">
              {snap.decisions.map((d) => (
                <li key={d.id} className="border-b border-line pb-3 last:border-0">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm">{d.summary}</p>
                    <Chip>{d.kind}</Chip>
                  </div>
                  <p className="mt-1 text-xs text-dim">{d.rationale}</p>
                  <p className="mt-1 text-xs">Outcome: <span className="mono text-ink">{d.outcome}</span></p>
                  <p className="mono mt-1 text-[0.68rem] text-faint">{who(d.made_by)} · {d.kind} · {when(d.created_at)}</p>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </>
  );
}
