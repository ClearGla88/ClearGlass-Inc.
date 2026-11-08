import { MemoryDecision } from "@/components/memory-actions";
import { Chip, Empty, PageHeader, Panel, StatusChip, when } from "@/components/ui";
import { getSnapshot } from "@/lib/snapshot";

const SECTIONS: { tag: string; title: string }[] = [
  { tag: "goals", title: "Company goals" },
  { tag: "brand", title: "Brand guidelines" },
  { tag: "customer", title: "Customer context" },
  { tag: "policy", title: "Policies" },
  { tag: "technical", title: "Technical documentation" },
  { tag: "prompt", title: "Reusable prompts" },
  { tag: "workflow", title: "Reusable workflows" },
];

export default async function VaultPage() {
  const { snap } = await getSnapshot();
  const long = snap.memory.filter((m) => m.layer === "long_term");
  const approved = long.filter((m) => m.status === "approved");
  const proposed = long.filter((m) => m.status === "proposed");
  const short = snap.memory.filter((m) => m.layer === "short_term");
  const tagged = new Set(SECTIONS.map((s) => s.tag));
  const other = approved.filter((m) => !m.tags.some((t) => tagged.has(t)));

  return (
    <>
      <PageHeader kicker="Long-term memory is operator-approved" title="Knowledge Vault">
        <Chip color="var(--cg-ok)">{approved.length} approved</Chip>
        <Chip color="var(--cg-warn)">{proposed.length} proposed</Chip>
        <Chip>{short.length} task notes</Chip>
      </PageHeader>

      {proposed.length > 0 && (
        <Panel kicker="Curation queue" title="Proposed by agents" className="mb-5">
          <ul className="space-y-3">
            {proposed.map((m) => (
              <li key={m.id} className="rounded-lg border border-warn/30 p-3">
                <p className="text-sm font-medium">{m.title} <span className="mono text-xs text-faint">{m.scope}</span></p>
                <p className="mt-1 whitespace-pre-line text-sm text-dim">{m.content}</p>
                <p className="mt-1 text-xs text-faint">from {m.created_by} · source {m.source}</p>
                <div className="mt-2"><MemoryDecision id={m.id} /></div>
              </li>
            ))}
          </ul>
        </Panel>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        {SECTIONS.map((s) => {
          const items = approved.filter((m) => m.tags.includes(s.tag));
          return (
            <Panel key={s.tag} kicker={s.tag} title={s.title}>
              {items.length === 0 ? <Empty>Nothing recorded yet.</Empty> : (
                <ul className="space-y-3">
                  {items.map((m) => (
                    <li key={m.id}>
                      <details>
                        <summary className="cursor-pointer text-sm">{m.title}</summary>
                        <p className="mt-2 whitespace-pre-line text-sm text-dim">{m.content}</p>
                      </details>
                      <p className="mono mt-1 text-[0.68rem] text-faint">{m.source} · {m.classification} · approved by {m.approved_by}</p>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          );
        })}
        <Panel kicker="decisions" title="Past decisions">
          {snap.decisions.length === 0 ? <Empty>No decisions yet.</Empty> : (
            <ul className="space-y-2 text-sm">
              {snap.decisions.slice(0, 12).map((d) => (
                <li key={d.id}><span className="text-ink">{d.summary}</span> <span className="text-faint">· {d.made_by} · {when(d.created_at)}</span></li>
              ))}
            </ul>
          )}
        </Panel>
        {other.length > 0 && (
          <Panel kicker="other" title="Other approved records">
            <ul className="space-y-2 text-sm">{other.map((m) => <li key={m.id}>{m.title}</li>)}</ul>
          </Panel>
        )}
        <Panel kicker="short-term" title="Task memory (expires daily)" className="lg:col-span-2">
          {short.length === 0 ? <Empty>No task notes.</Empty> : (
            <ul className="grid gap-2 md:grid-cols-2">
              {short.slice(0, 24).map((m) => (
                <li key={m.id} className="rounded-lg border border-line p-2 text-sm">
                  <div className="flex items-center justify-between gap-2"><span>{m.title}</span><StatusChip status={m.status} /></div>
                  <p className="text-xs text-dim">{m.content}</p>
                  <p className="mono text-[0.65rem] text-faint">{m.created_by} · {m.scope}</p>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </>
  );
}
