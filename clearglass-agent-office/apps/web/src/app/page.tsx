import Link from "next/link";
import { Rise } from "@/components/motion";
import { Chip, Dot, Empty, NoData, PageHeader, Panel, Stat, StatusChip, TIER_COLOR, TierChip, label, pct } from "@/components/ui";
import { getSnapshot } from "@/lib/snapshot";
import type { Agent, Room } from "@/lib/types";

const VIEW_HREF: Record<string, string> = { missions: "/missions", vault: "/vault" };

function RoomCard({ room, agents, deptName, i }: { room: Room; agents: Agent[]; deptName?: string; i: number }) {
  const href = room.view ? VIEW_HREF[room.view] : room.department ? `/agents?dept=${room.department}` : undefined;
  const busy = agents.filter((a) => a.status === "working" || a.status === "waiting_for_approval").length;
  const body = (
    <div className="glass glass-edge h-full p-3 transition hover:border-accent/40">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold leading-tight">{room.name}</p>
          <p className="label mt-0.5">{deptName ?? room.kind}</p>
        </div>
        <span className="mono text-[0.65rem] text-faint">F{room.floor}</span>
      </div>
      {agents.length > 0 ? (
        <ul className="mt-3 flex flex-wrap gap-1.5" aria-label={`${room.name} agents`}>
          {agents.map((a) => (
            <li key={a.id} className="flex items-center gap-1.5 rounded-md border border-line bg-black/20 px-1.5 py-1">
              <Dot status={a.status} title={`${a.callsign} ${a.name}: ${label(a.status)}`} />
              <span className="mono text-[0.62rem] text-dim">{a.callsign.slice(3)}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-xs text-faint">{room.view ? `Open ${label(room.view)} →` : "Shared facility"}</p>
      )}
      {agents.length > 0 && (
        <p className="mt-2 text-[0.7rem] text-faint">{agents.length} agents{busy ? ` · ${busy} active` : ""}</p>
      )}
    </div>
  );
  return (
    <Rise delay={0.03 * i} className="h-full">
      {href ? <Link href={href} className="block h-full">{body}</Link> : body}
    </Rise>
  );
}

export default async function Headquarters() {
  const { snap } = await getSnapshot();
  const k = snap.kpis;
  const depts = Object.fromEntries(snap.departments.map((d) => [d.id, d.name]));
  const floors = [...new Set(snap.rooms.map((r) => r.floor))].sort((a, b) => b - a);
  const active = snap.missions.filter((m) => m.status === "active" || m.status === "completed");
  const statusCounts = k.agents.by_status;

  return (
    <>
      <PageHeader kicker={`${snap.company.region} · ${snap.company.name}`} title="Headquarters">
        <Chip color="var(--cg-accent)">{k.agents.total} agents</Chip>
        <Chip>{snap.departments.length} departments</Chip>
        <Chip>{snap.rooms.length} rooms</Chip>
      </PageHeader>

      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Tasks done" value={`${k.tasks.by_status.completed ?? 0}/${k.tasks.total}`} hint="all missions" />
        <Stat label="Awaiting you" value={k.approvals.pending} tone={k.approvals.pending ? "var(--cg-warn)" : undefined} hint="approval desk" />
        <Stat label="Agent success" value={pct(k.agents.success_rate)} hint="completed / (completed + failed)" />
        <Stat label="Qualified leads" value={k.pipeline.qualified_leads ?? <NoData>—</NoData>} hint={k.pipeline.is_sample_data ? "sample data" : "pipeline"} />
        <Stat label="Unapproved external" value={k.risk.external_actions_without_approval} tone={k.risk.external_actions_without_approval ? "var(--cg-bad)" : "var(--cg-ok)"} hint="must stay 0" />
        <Stat label="Control tests" value={k.risk.control_tests !== null ? `${k.risk.control_tests_passed}/${k.risk.control_tests}` : <NoData>—</NoData>} hint="latest security review" />
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <Panel kicker="Glass tower" title="Office map"
          actions={Object.entries(statusCounts).map(([s, n]) => (
            <span key={s} className="flex items-center gap-1.5 text-xs text-dim"><Dot status={s} /> {label(s)} {n}</span>
          ))}>
          <div className="space-y-3">
            {floors.map((floor) => {
              const rooms = snap.rooms.filter((r) => r.floor === floor);
              return (
                <div key={floor} className="grid grid-cols-[2.5rem_minmax(0,1fr)] items-stretch gap-3">
                  <div className="mono flex items-center justify-center rounded-lg border border-line text-xs text-faint">{floor}</div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    {rooms.map((room, i) => (
                      <RoomCard key={room.id} room={room} i={floor * 2 + i}
                        agents={snap.agents.filter((a) => a.room === room.id)}
                        deptName={room.department ? depts[room.department] : undefined} />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </Panel>

        <div className="space-y-5">
          <Panel kicker="Company objectives" title="What the office is for">
            <ul className="space-y-3">
              {snap.objectives.map((o) => {
                const ratio = o.measured && o.target ? Math.min(1, (o.current ?? 0) / o.target) : 0;
                const invert = o.target === 0;
                return (
                  <li key={o.id}>
                    <p className="text-sm leading-snug">{o.title}</p>
                    <div className="mt-1 flex items-center justify-between text-xs text-faint">
                      <span>{o.metric}</span>
                      <span className="mono">{o.measured ? `${o.current} / ${o.target}` : "not measured yet"}</span>
                    </div>
                    {!invert && (
                      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-white/5">
                        <div className="h-full rounded-full bg-accent" style={{ width: `${ratio * 100}%` }} />
                      </div>
                    )}
                    {invert && (
                      <p className="mt-1 text-xs" style={{ color: o.current === 0 ? "var(--cg-ok)" : "var(--cg-bad)" }}>
                        {o.current === 0 ? "Holding at zero" : "Breached"}
                      </p>
                    )}
                  </li>
                );
              })}
            </ul>
          </Panel>

          <Panel kicker="Alerts" title={`${snap.alerts.length} open`}>
            {snap.alerts.length === 0 ? <Empty>No open alerts.</Empty> : (
              <ul className="space-y-2">
                {snap.alerts.slice(0, 8).map((a, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm">
                    <span className="mt-1.5 size-2 shrink-0 rounded-full" style={{ background: TIER_COLOR[a.severity] }} />
                    <span>
                      {a.title}
                      {a.detail && <span className="mono block text-[0.7rem] text-faint">{a.detail}</span>}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel kicker="Active missions" title="Mission control" actions={<Link className="text-xs text-accent" href="/missions">Open →</Link>}>
            <ul className="space-y-3">
              {active.map((m) => {
                const done = m.tasks.filter((t) => t.status === "completed").length;
                return (
                  <li key={m.id}>
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-sm leading-snug">{m.title}</p>
                      <StatusChip status={m.workflow_status ?? m.status} />
                    </div>
                    <div className="mt-1.5 flex gap-1" aria-label={`${done} of ${m.tasks.length} tasks complete`}>
                      {m.tasks.map((t) => (
                        <span key={t.id} title={`${t.title}: ${label(t.status)}`} className="h-1.5 flex-1 rounded-full"
                          style={{ background: t.status === "completed" ? "var(--cg-ok)" : t.status === "waiting_approval" ? "var(--cg-warn)" : ["failed", "blocked"].includes(t.status) ? "var(--cg-bad)" : "rgba(255,255,255,0.08)" }} />
                      ))}
                    </div>
                    <p className="mt-1 text-xs text-faint">{depts[m.department]} · P{m.priority} · {done}/{m.tasks.length} tasks
                      {m.tasks.some((t) => t.output?.governance?.tier === "high") && <> · <TierChip tier="high" /></>}</p>
                  </li>
                );
              })}
            </ul>
          </Panel>
        </div>
      </div>
    </>
  );
}
