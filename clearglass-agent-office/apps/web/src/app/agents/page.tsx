import Link from "next/link";
import { AgentActions, HireAgent } from "@/components/agent-actions";
import { Chip, Dot, PageHeader, Panel, StatusChip, TierChip, label } from "@/components/ui";
import { getSnapshot } from "@/lib/snapshot";
import type { Agent, Snapshot, Tier } from "@/lib/types";

const LEVEL: Record<string, number> = { none: 0, read: 1, propose: 2, write: 3, execute: 4 };
const TIER_RANK: Record<Tier, number> = { low: 0, medium: 1, high: 2, critical: 3 };

function reachableTier(agent: Agent, snap: Snapshot): Tier {
  const toolActions = new Set(snap.tools.filter((t) => agent.tools.includes(t.id)).flatMap((t) => t.actions));
  let top: Tier = "low";
  for (const [action, spec] of Object.entries(snap.policy.actions)) {
    if (!toolActions.has(action)) continue;
    if ((LEVEL[agent.permissions[spec.domain] ?? "none"] ?? 0) < (LEVEL[spec.level] ?? 9)) continue;
    if (TIER_RANK[spec.tier] > TIER_RANK[top]) top = spec.tier;
  }
  return top;
}

export default async function AgentsPage({ searchParams }: { searchParams: Promise<{ dept?: string }> }) {
  const { snap } = await getSnapshot();
  const { dept } = await searchParams;
  const agents = snap.agents.filter((a) => !dept || a.department === dept);
  const depts = Object.fromEntries(snap.departments.map((d) => [d.id, d]));
  const names = Object.fromEntries(snap.agents.map((a) => [a.id, a.name]));
  const openTasks = (id: string) =>
    snap.missions.flatMap((m) => m.tasks).filter((t) => t.assignee === id && !["completed", "failed", "cancelled"].includes(t.status)).length;
  const taskTitle = Object.fromEntries(snap.missions.flatMap((m) => m.tasks).map((t) => [t.id, t.title]));

  return (
    <>
      <PageHeader kicker={`${snap.agents.length} agents · ${snap.departments.length} departments`} title="Agent Directory">
        <HireAgent />
      </PageHeader>
      <nav aria-label="Filter by department" className="mb-4 flex flex-wrap gap-2">
        <Link href="/agents" className={`rounded-full border px-3 py-1 text-xs ${!dept ? "border-accent/50 text-accent" : "border-line text-dim"}`}>All</Link>
        {snap.departments.map((d) => (
          <Link key={d.id} href={`/agents?dept=${d.id}`}
            className={`rounded-full border px-3 py-1 text-xs ${dept === d.id ? "border-accent/50 text-accent" : "border-line text-dim hover:text-ink"}`}>
            {d.name}
          </Link>
        ))}
      </nav>
      {dept && depts[dept] && (
        <Panel kicker="Department" title={depts[dept].name} className="mb-4">
          <p className="text-sm text-dim">{depts[dept].mission}</p>
          <div className="mt-3 grid gap-3 text-sm md:grid-cols-2">
            <div><p className="label">Responsibilities</p><ul className="mt-1 list-inside list-disc text-dim">{depts[dept].responsibilities.map((r) => <li key={r}>{r}</li>)}</ul></div>
            <div><p className="label">Boundaries</p><ul className="mt-1 list-inside list-disc text-dim">{depts[dept].boundaries.map((r) => <li key={r}>{r}</li>)}</ul></div>
          </div>
        </Panel>
      )}
      <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
        {agents.map((a) => {
          const done = a.metrics.tasks_completed, failed = a.metrics.tasks_failed;
          const rate = done + failed ? `${Math.round((done / (done + failed)) * 100)}%` : "no data";
          return (
            <Panel key={a.id} kicker={`${a.callsign} · ${depts[a.department]?.name ?? a.department}`}
              title={<span className="flex items-center gap-2"><Dot status={a.status} />{a.name}</span>}
              actions={<StatusChip status={a.status} />}>
              <p className="text-sm text-dim">{a.objective}</p>
              <dl className="mt-3 grid grid-cols-3 gap-2 text-center">
                <div className="rounded-lg border border-line py-2"><dt className="label">Workload</dt><dd className="mono mt-0.5 text-sm">{openTasks(a.id)} open</dd></div>
                <div className="rounded-lg border border-line py-2"><dt className="label">Success</dt><dd className="mono mt-0.5 text-sm">{rate}</dd></div>
                <div className="rounded-lg border border-line py-2"><dt className="label">Reach</dt><dd className="mt-0.5"><TierChip tier={reachableTier(a, snap)} /></dd></div>
              </dl>
              {a.current_task_id && taskTitle[a.current_task_id] && (
                <p className="mt-3 text-xs text-dim">Current: <span className="text-ink">{taskTitle[a.current_task_id]}</span></p>
              )}
              <div className="mt-3 space-y-2 text-xs">
                <p><span className="label mr-2">Reports to</span>{a.reports_to === "operator" ? "Operator" : names[a.reports_to] ?? a.reports_to}</p>
                <div className="flex flex-wrap items-center gap-1"><span className="label mr-1">Permissions</span>
                  {Object.entries(a.permissions).map(([d, l]) => <Chip key={d}>{d}:{l}</Chip>)}</div>
                <div className="flex flex-wrap items-center gap-1"><span className="label mr-1">Tools</span>
                  {a.tools.map((t) => <Chip key={t} color="var(--cg-accent-2)">{t}</Chip>)}</div>
                <p><span className="label mr-2">Memory</span><span className="mono text-dim">{a.memory_scopes.join(", ")}</span> · {a.clearance}</p>
                <p className="text-faint">Denials {a.metrics.policy_denials} · approvals requested {a.metrics.approvals_requested} · v{a.version}</p>
              </div>
              <details className="mt-3 text-xs text-dim">
                <summary className="cursor-pointer text-faint">Boundaries ({a.boundaries.length}) and success criteria</summary>
                <ul className="mt-2 list-inside list-disc space-y-1">{a.boundaries.map((b) => <li key={b}>{b}</li>)}</ul>
                <ul className="mt-2 list-inside list-disc space-y-1 text-ink">{a.success_criteria.map((b) => <li key={b}>{b}</li>)}</ul>
                <p className="mt-2 text-faint">Skills: {a.skills.map(label).join(", ")}</p>
              </details>
              <div className="mt-4 border-t border-line pt-3">
                <AgentActions id={a.id} status={a.status} objective={a.objective} department={a.department} />
              </div>
            </Panel>
          );
        })}
      </div>
    </>
  );
}
