import { ApprovalActions } from "@/components/approval-actions";
import { Trace } from "@/components/trace";
import { Chip, Empty, Json, PageHeader, Panel, StatusChip, TierChip, when } from "@/components/ui";
import { getSnapshot } from "@/lib/snapshot";

export default async function ApprovalsPage() {
  const { snap } = await getSnapshot();
  const agents = Object.fromEntries(snap.agents.map((a) => [a.id, a]));
  const tasks = Object.fromEntries(snap.missions.flatMap((m) => m.tasks).map((t) => [t.id, t]));
  const pending = snap.approvals.filter((a) => a.status === "pending");
  const history = snap.approvals.filter((a) => a.status !== "pending");

  return (
    <>
      <PageHeader kicker="High and critical actions stop here" title="Approval Desk">
        <Chip color="var(--cg-warn)">{pending.length} pending</Chip>
        <Chip>{history.length} decided</Chip>
      </PageHeader>

      <div className="space-y-5">
        {pending.length === 0 && <Empty>Nothing is waiting for you.</Empty>}
        {pending.map((a) => {
          const agent = agents[a.requested_by];
          const task = a.task_id ? tasks[a.task_id] : undefined;
          const notes = snap.messages.filter((m) => m.kind === "review" && m.subject.includes(a.id));
          const text = typeof a.action.params.text === "string" ? a.action.params.text : null;
          return (
            <Panel key={a.id} kicker={`${a.id} · requested ${when(a.created_at)} · expires ${when(a.expires_at)}`}
              title={<span className="mono">{a.action_type}</span>}
              actions={<><TierChip tier={a.risk_tier} /><StatusChip status={a.status} /></>}>
              <div className="grid gap-5 lg:grid-cols-2">
                <div className="space-y-3">
                  <p className="text-sm">
                    <span className="text-dim">Requested by </span>{agent ? `${agent.callsign} ${agent.name}` : a.requested_by}
                    <span className="text-dim"> via </span><span className="mono">{a.action.tool_id}</span>
                  </p>
                  {task && <p className="text-sm text-dim">Task: <span className="text-ink">{task.title}</span></p>}
                  <div>
                    <p className="label">Why it stopped</p>
                    <ul className="mt-1 space-y-0.5 text-sm text-dim">{a.reasons.map((r) => <li key={r}>· {r}</li>)}</ul>
                  </div>
                  {text && (
                    <div>
                      <p className="label">Exact text that would be published</p>
                      <blockquote className="mt-1 whitespace-pre-line rounded-lg border border-line bg-black/30 p-3 text-sm">{text}</blockquote>
                    </div>
                  )}
                  <div>
                    <p className="label">Full payload (digest {a.action_digest.slice(0, 16)}…)</p>
                    <Json value={a.action.params} />
                  </div>
                  {a.risk_tier === "critical" && (
                    <dl className="grid gap-2 text-sm">
                      <div><dt className="label">Change plan</dt><dd className="text-dim">{a.change_plan}</dd></div>
                      <div><dt className="label">Rollback plan</dt><dd className="text-dim">{a.rollback_plan}</dd></div>
                      <div><dt className="label">Verification plan</dt><dd className="text-dim">{a.verification_plan}</dd></div>
                    </dl>
                  )}
                </div>
                <div className="space-y-4">
                  {notes.map((n) => (
                    <div key={n.id} className="rounded-lg border border-info/30 bg-info/5 p-3 text-sm">
                      <p className="label">Risk &amp; Compliance note</p>
                      <p className="mt-1 text-dim">{n.body}</p>
                    </div>
                  ))}
                  {task?.output?.governance && (
                    <div>
                      <p className="label mb-1">Policy pipeline so far</p>
                      <Trace steps={task.output.governance.trace} />
                    </div>
                  )}
                  <ApprovalActions id={a.id} params={a.action.params} />
                  <p className="text-xs text-faint">
                    Approval binds to this exact payload. Connectors are dry-run in this build: an approved action is
                    recorded with a receipt; nothing is sent until a reviewed live adapter is registered.
                  </p>
                </div>
              </div>
            </Panel>
          );
        })}

        <Panel kicker="Immutable history" title="Decided approvals">
          {history.length === 0 ? <Empty>No decisions yet.</Empty> : (
            <ul className="space-y-4">
              {history.map((a) => (
                <li key={a.id} className="border-b border-line pb-4 last:border-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="mono text-sm">{a.action_type}</span><TierChip tier={a.risk_tier} /><StatusChip status={a.status} />
                    <span className="mono text-xs text-faint">{a.id}</span>
                  </div>
                  <ol className="mt-2 space-y-1 text-xs">
                    {a.decisions.map((d) => (
                      <li key={d.seq} className="text-dim">
                        <span className="mono text-faint">#{d.seq} {when(d.decided_at)}</span> · <span className="text-ink">{d.decision}</span> by {d.decided_by}: “{d.reason}”
                        {d.modifications && <span className="text-warn"> (edited: {Object.keys(d.modifications).join(", ")})</span>}
                      </li>
                    ))}
                  </ol>
                  {a.execution?.receipt && (
                    <p className="mono mt-1 text-[0.7rem] text-ok">receipt {String(a.execution.receipt.receipt_id)} · {String(a.execution.receipt.mode)}</p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </>
  );
}
