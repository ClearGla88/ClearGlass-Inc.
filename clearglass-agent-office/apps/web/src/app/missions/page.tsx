import { ActionButton } from "@/components/actions";
import { MissionCreate } from "@/components/mission-create";
import { Trace } from "@/components/trace";
import { Chip, Dot, Empty, PageHeader, Panel, StatusChip, TierChip, label } from "@/components/ui";
import { getSnapshot } from "@/lib/snapshot";

export default async function MissionsPage() {
  const { snap } = await getSnapshot();
  const names = Object.fromEntries(snap.agents.map((a) => [a.id, a]));
  const depts = Object.fromEntries(snap.departments.map((d) => [d.id, d.name]));
  const missions = [...snap.missions].sort((a, b) => a.priority - b.priority || a.title.localeCompare(b.title));

  return (
    <>
      <PageHeader kicker={`${snap.missions.length} missions`} title="Mission Control">
        <ActionButton path="daily-loop/run" variant="ghost">Run daily loop</ActionButton>
        <MissionCreate />
      </PageHeader>
      {missions.length === 0 && <Empty>No missions yet. Run the daily loop or create one.</Empty>}
      <div className="space-y-5">
        {missions.map((m) => {
          const byId = Object.fromEntries(m.tasks.map((t) => [t.id, t]));
          return (
            <Panel key={m.id} kicker={`${depts[m.department]} · P${m.priority}${m.deadline ? ` · due ${m.deadline}` : ""} · owner ${names[m.owner]?.name ?? m.owner}`}
              title={m.title}
              actions={<>
                <StatusChip status={m.workflow_status ?? m.status} />
                {m.status === "active" && <ActionButton path={`missions/${m.id}/run`}>Advance</ActionButton>}
              </>}>
              <p className="text-sm text-dim">{m.objective}</p>
              <div className="mt-3 grid gap-3 text-xs md:grid-cols-3">
                <div><p className="label">Deliverables</p><ul className="mt-1 space-y-0.5 text-dim">{m.deliverables.map((d) => <li key={d}>· {d}</li>)}</ul></div>
                <div><p className="label">Constraints</p><ul className="mt-1 space-y-0.5 text-dim">{m.constraints.map((d) => <li key={d}>· {d}</li>)}</ul></div>
                <div><p className="label">Approval rules</p><ul className="mt-1 space-y-0.5 text-dim">{m.approval_rules.map((d) => <li key={d}>· {d}</li>)}</ul></div>
              </div>
              <div className="mt-4 flex gap-3 overflow-x-auto pb-1" aria-label="Workflow waves">
                {m.waves.map((wave, w) => (
                  <div key={w} className="min-w-[15rem] flex-1">
                    <p className="label mb-2">Wave {w + 1}{wave.length > 1 ? " · parallel" : ""}</p>
                    <div className="space-y-2">
                      {wave.map((id) => {
                        const t = byId[id];
                        if (!t) return null;
                        const gov = t.output?.governance;
                        return (
                          <details key={id} className="rounded-lg border border-line bg-black/20 p-3">
                            <summary className="cursor-pointer list-none">
                              <div className="flex items-start justify-between gap-2">
                                <p className="text-sm leading-snug"><Dot status={t.status} /> <span className="ml-1">{t.title}</span></p>
                                {gov && <TierChip tier={gov.tier} />}
                              </div>
                              <p className="mt-1 text-xs text-faint">
                                {names[t.assignee]?.callsign} {names[t.assignee]?.name} · <span className="mono">{t.action.type}</span>
                              </p>
                              <div className="mt-1.5 flex flex-wrap gap-1">
                                <StatusChip status={t.status} />
                                {t.depends_on.length > 0 && <Chip>after {t.depends_on.map((d) => byId[d]?.key ?? d).join(", ")}</Chip>}
                              </div>
                            </summary>
                            <div className="mt-3 space-y-2 border-t border-line pt-3">
                              {t.output?.summary && <p className="text-xs text-ink">{t.output.summary}</p>}
                              {t.error && <p className="text-xs text-bad">{t.error}</p>}
                              {gov && <>
                                <p className="label">Governance trace · score {gov.score} · digest {gov.digest.slice(0, 12)}</p>
                                <Trace steps={gov.trace} />
                              </>}
                              {!gov && <p className="text-xs text-faint">Not run yet ({label(t.status)}).</p>}
                            </div>
                          </details>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </Panel>
          );
        })}
      </div>
    </>
  );
}
