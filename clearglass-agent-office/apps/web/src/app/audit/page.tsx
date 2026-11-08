import { Chip, PageHeader, Panel, TierChip, when } from "@/components/ui";
import { getSnapshot } from "@/lib/snapshot";

export default async function AuditPage() {
  const { snap } = await getSnapshot();
  const v = snap.audit.verify;
  return (
    <>
      <PageHeader kicker="Append-only · SHA-256 hash chain" title="Audit Ledger">
        <Chip color={v.ok ? "var(--cg-ok)" : "var(--cg-bad)"}>{v.ok ? "chain verified" : `broken at #${v.broken_at}: ${v.reason}`}</Chip>
        <Chip>{v.count} events</Chip>
      </PageHeader>
      <Panel kicker={`head ${v.head}`} title={`Latest ${snap.audit.events.length} events`}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[46rem] text-left text-sm">
            <thead className="text-faint">
              <tr><th className="py-1 font-normal">#</th><th className="font-normal">Time</th><th className="font-normal">Actor</th><th className="font-normal">Event</th><th className="font-normal">Subject</th><th className="font-normal">Tier</th><th className="font-normal">Hash</th></tr>
            </thead>
            <tbody>
              {snap.audit.events.map((e) => (
                <tr key={e.seq} className="border-t border-line align-top">
                  <td className="mono py-1.5 pr-2 text-xs text-faint">{e.seq}</td>
                  <td className="mono pr-2 text-xs text-dim">{when(e.ts)}</td>
                  <td className="pr-2 text-xs"><span className="text-ink">{e.actor}</span> <span className="text-faint">({e.actor_type})</span></td>
                  <td className="mono pr-2 text-xs">{e.event_type}{typeof e.payload.action_type === "string" && <span className="block text-faint">{e.payload.action_type}</span>}</td>
                  <td className="mono pr-2 text-xs text-dim">{e.subject}</td>
                  <td className="pr-2">{e.risk_tier && <TierChip tier={e.risk_tier} />}</td>
                  <td className="mono text-[0.68rem] text-faint" title={`prev ${e.prev_hash}`}>{e.hash.slice(0, 12)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}
