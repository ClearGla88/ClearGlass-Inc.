import { ActionButton } from "@/components/actions";
import { Chip, Empty, NoData, PageHeader, Panel, Stat, StatusChip, TIER_COLOR, TierChip, pct, when } from "@/components/ui";
import { getSnapshot } from "@/lib/snapshot";

type Row = Record<string, any>;

export default async function BriefingPage() {
  const { snap } = await getSnapshot();
  const b = snap.reports.briefing;
  const e = snap.reports.eod;
  const sec = snap.reports.security_review;
  const k = snap.kpis;
  const names = Object.fromEntries(snap.agents.map((a) => [a.id, a.name]));

  return (
    <>
      <PageHeader kicker="Prepared by the Chief of Staff" title="Executive Briefing Room">
        <ActionButton path="daily-loop/run" variant="primary">Run today&apos;s loop</ActionButton>
      </PageHeader>

      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <Stat label="Task completion" value={pct(k.tasks.completion_rate)} />
        <Stat label="Agent success" value={pct(k.agents.success_rate)} />
        <Stat label="Policy checks" value={k.policy.evaluations} hint={Object.entries(k.policy.by_outcome).map(([o, n]) => `${o.replace("_", " ")} ${n}`).join(" · ")} />
        <Stat label="Decision time" value={k.approvals.median_decision_minutes ?? <NoData>no data</NoData>} hint="median minutes" />
        <Stat label="Pipeline" value={k.pipeline.qualified_leads ?? <NoData>—</NoData>} hint={k.pipeline.is_sample_data ? "qualified · sample data" : "qualified"} />
        <Stat label="Published" value={k.content.published} hint="approved posts" />
        <Stat label="Deploy success" value={pct(k.deployments.success_rate)} hint={`${k.deployments.executed} deploys`} />
        <Stat label="Audit chain" value={k.risk.audit_chain_ok ? "verified" : "broken"} tone={k.risk.audit_chain_ok ? "var(--cg-ok)" : "var(--cg-bad)"} hint={`${k.risk.audit_events} events`} />
      </div>

      {!b && !e && <Empty>No briefing yet. Run the daily loop.</Empty>}

      <div className="grid gap-5 xl:grid-cols-2">
        {b && (
          <Panel kicker={`Daily briefing · ${b.period} · ${when(b.generated_at)}`} title={b.title}>
            <h3 className="label mb-2">Today&apos;s priorities</h3>
            <ol className="space-y-2">
              {(b.sections.priorities as Row[]).slice(0, 8).map((p) => (
                <li key={p.task_id} className="grid grid-cols-[2.5rem_minmax(0,1fr)] gap-2 text-sm">
                  <span className="mono text-accent">{p.score}</span>
                  <span>{p.title} <span className="text-faint">· {names[p.assignee] ?? p.assignee} · {(p.why as string[]).join(", ")}</span></span>
                </li>
              ))}
            </ol>
            <h3 className="label mb-2 mt-5">Department status</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-faint"><tr><th className="py-1 font-normal">Department</th><th className="font-normal">Agents</th><th className="font-normal">Open</th><th className="font-normal">Waiting</th><th className="font-normal">Blocked</th></tr></thead>
                <tbody>{(b.sections.departments as Row[]).map((d) => (
                  <tr key={d.id} className="border-t border-line"><td className="py-1.5">{d.name}</td><td className="mono">{d.agents}</td><td className="mono">{d.open_tasks}</td><td className="mono">{d.waiting_approval}</td><td className="mono">{d.blocked}</td></tr>
                ))}</tbody>
              </table>
            </div>
            <h3 className="label mb-2 mt-5">Risks at the start of the day</h3>
            {(b.sections.risks as Row[]).length === 0 ? <p className="text-sm text-faint">None recorded this morning.</p> : (
              <ul className="space-y-1 text-sm">{(b.sections.risks as Row[]).map((r, i) => <li key={i}><TierChip tier={r.severity} /> {r.title}</li>)}</ul>
            )}
            <h3 className="label mb-2 mt-5">Recommended actions</h3>
            <ul className="space-y-1 text-sm text-dim">{(b.sections.recommended_actions as string[]).map((a) => <li key={a}>· {a}</li>)}</ul>
          </Panel>
        )}

        {e && (
          <Panel kicker={`End of day · ${e.period} · ${when(e.generated_at)}`} title={e.title}>
            <h3 className="label mb-2">Completed ({(e.sections.completed as Row[]).length})</h3>
            <ul className="space-y-1 text-sm">{(e.sections.completed as Row[]).map((c, i) => (
              <li key={i}><span className="text-ink">{c.title}</span> <span className="text-faint">· {names[c.agent] ?? c.agent}</span>
                {c.summary && <span className="block text-xs text-dim">{c.summary}</span>}</li>
            ))}</ul>
            <h3 className="label mb-2 mt-5">Waiting for you</h3>
            {(e.sections.approvals.pending as Row[]).length === 0 ? <p className="text-sm text-faint">Nothing pending.</p> : (
              <ul className="space-y-1 text-sm">{(e.sections.approvals.pending as Row[]).map((a) => (
                <li key={a.id}><TierChip tier={a.tier} /> <span className="mono">{a.action_type}</span> <span className="text-faint">· {a.id} · {names[a.requested_by] ?? a.requested_by}</span></li>
              ))}</ul>
            )}
            <h3 className="label mb-2 mt-5">Medium-tier actions for your review</h3>
            {(e.sections.medium_tier_for_review as Row[]).length === 0 ? <p className="text-sm text-faint">None today.</p> : (
              <ul className="space-y-1 text-sm text-dim">{(e.sections.medium_tier_for_review as Row[]).map((m) => (
                <li key={m.seq}><span className="mono text-faint">#{m.seq}</span> {m.summary} <span className="text-faint">· {names[m.actor] ?? m.actor}</span></li>
              ))}</ul>
            )}
            <h3 className="label mb-2 mt-5">Policy outcomes today</h3>
            <div className="flex flex-wrap gap-2">{Object.entries(e.sections.policy_outcomes_today as Record<string, number>).map(([o, n]) => <Chip key={o}>{o.replace("_", " ")} {n}</Chip>)}</div>
            <h3 className="label mb-2 mt-5">Audit</h3>
            <p className="mono text-xs" style={{ color: e.sections.audit.ok ? "var(--cg-ok)" : "var(--cg-bad)" }}>
              {e.sections.audit.ok ? "verified" : "BROKEN"} · {e.sections.audit.count} events · head {String(e.sections.audit.head).slice(0, 16)}…
            </p>
            <h3 className="label mb-2 mt-5">Carry over</h3>
            {(e.sections.carry_over as Row[]).length === 0 ? <p className="text-sm text-faint">Nothing carried over.</p> : (
              <ul className="space-y-1 text-sm">{(e.sections.carry_over as Row[]).map((c) => <li key={c.task_id}><StatusChip status={c.status} /> {c.title}</li>)}</ul>
            )}
          </Panel>
        )}

        {sec && (
          <Panel kicker={`Security review · ${when(sec.generated_at)}`} title={sec.title} className="xl:col-span-2">
            <div className="mb-3 flex flex-wrap gap-2">
              <Chip color="var(--cg-ok)">{String(sec.metrics.control_tests_passed)}/{String(sec.metrics.control_tests)} control tests passed</Chip>
              <Chip>{String(sec.metrics.agents_reviewed)} agents · {String(sec.metrics.tools_reviewed)} tools reviewed</Chip>
              {Object.entries((sec.metrics.by_severity ?? {}) as Record<string, number>).map(([s, n]) => <Chip key={s} color={TIER_COLOR[s]}>{s} {n}</Chip>)}
            </div>
            {(sec.sections.findings as Row[]).length > 0 && (
              <ul className="mb-4 space-y-2 text-sm">{(sec.sections.findings as Row[]).map((f, i) => (
                <li key={i}><Chip color={TIER_COLOR[f.severity]}>{f.severity}</Chip> <span className="text-ink">{f.title}</span><span className="block text-xs text-dim">{f.detail} · Fix: {f.fix}</span></li>
              ))}</ul>
            )}
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-faint"><tr><th className="py-1 font-normal">Control test</th><th className="font-normal">Agent</th><th className="font-normal">Action</th><th className="font-normal">Expected</th><th className="font-normal">Result</th></tr></thead>
                <tbody>{(sec.sections.control_tests as Row[]).map((c) => (
                  <tr key={c.name} className="border-t border-line align-top">
                    <td className="py-1.5 pr-2">{c.name}</td><td className="mono pr-2 text-xs text-dim">{c.agent}</td><td className="mono pr-2 text-xs">{c.action}</td>
                    <td className="mono pr-2 text-xs">{String(c.expected).replace("_", " ")}</td>
                    <td className="mono text-xs" style={{ color: c.passed ? "var(--cg-ok)" : "var(--cg-bad)" }}>{c.passed ? "pass" : `FAIL (${c.actual})`}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          </Panel>
        )}
      </div>
    </>
  );
}
