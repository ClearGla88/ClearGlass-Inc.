import Link from "next/link";
import type { ReactNode } from "react";
import { ActionButton } from "@/components/actions";
import { RevenueForm, type FieldSpec } from "@/components/revenue-form";
import { Chip, Empty, Json, PageHeader, Panel, StatusChip, label, when } from "@/components/ui";
import { getSnapshot } from "@/lib/snapshot";
import type { Desk, ExternalAction, MetricItem, Opportunity, Revenue } from "@/lib/types";

const DESK_COLOR: Record<string, string> = {
  idle: "var(--cg-muted)",
  queued: "var(--cg-accent-2)",
  working: "var(--cg-accent)",
  awaiting_approval: "var(--cg-warn)",
  waiting_for_customer: "var(--cg-info)",
  waiting_for_payment: "var(--cg-info)",
  blocked: "var(--cg-bad)",
  completed: "var(--cg-ok)",
  failed: "var(--cg-bad)",
  paused: "var(--cg-paused)",
};
const STAGES = ["new", "qualified", "contacted", "engaged", "proposal_sent", "accepted", "invoiced", "paid", "in_fulfillment"];
const CLOSED = ["disqualified", "lost"];
const OPEN_ACTION = ["awaiting_approval", "approved", "released"];

function money(cents: number | null | undefined, currency = "CAD"): string | null {
  if (cents === null || cents === undefined) return null;
  return `${currency} ${(cents / 100).toLocaleString("en-CA", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function metricValue(m: MetricItem): ReactNode {
  if (m.value === null) return <span className="text-faint">not available</span>;
  if (m.unit === "cents") return money(m.value);
  if (m.unit === "ratio") return `${Math.round(m.value * 100)}%`;
  if (m.unit === "days") return `${m.value} days`;
  return m.value;
}

function Row({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div>
      <dt className="label">{k}</dt>
      <dd className="mt-0.5 text-dim [overflow-wrap:anywhere]">{children}</dd>
    </div>
  );
}

function ProposedAction({ payload }: { payload: Record<string, unknown> }) {
  if (typeof payload.subject === "string") {
    return (
      <span className="block">
        <span className="text-ink">To {(payload.recipients as string[] | undefined)?.join(", ")}: {payload.subject}</span>
        <pre className="mono mt-1 max-h-52 overflow-auto whitespace-pre-wrap rounded-lg border border-line bg-black/30 p-2 text-[0.68rem]">
          {String(payload.body ?? "")}
        </pre>
      </span>
    );
  }
  if (payload.paypal_fields) return <Json value={payload.paypal_fields} max={1500} />;
  return <Json value={payload} max={1500} />;
}

function DeskCard({ desk, opps, actions }: { desk: Desk; opps: Record<string, Opportunity>; actions: ExternalAction[] }) {
  const focus = desk.current ? opps[desk.current.opportunity_id] : undefined;
  const open = actions.filter((a) => a.agent_id === desk.agent_id && OPEN_ACTION.includes(a.status));
  const draftKind = desk.role === "outreach" ? (focus?.stage === "qualified" ? "outreach" : "proposal") : null;
  const draft = draftKind && focus ? focus.drafts[draftKind] : undefined;
  const last = desk.last_activity;
  const exec = desk.last_connector_execution;
  const deps = [...desk.errors, desk.current?.detail].filter(Boolean).join("; ");
  return (
    <details className="glass glass-edge min-w-0 p-3">
      <summary className="cursor-pointer list-none">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="text-sm font-semibold leading-tight">{desk.title}</p>
            <p className="mono mt-0.5 text-[0.65rem] text-faint">{desk.callsign} · {desk.agent_id}</p>
          </div>
          <Chip color={DESK_COLOR[desk.state]}>{label(desk.state)}</Chip>
        </div>
        <p className="mt-2 text-xs text-dim">
          {desk.current ? `${desk.current.organization}: ${desk.current.step}` : "Nothing assigned"}
        </p>
        <p className="mt-1 text-[0.66rem] text-faint">Select for the record behind this desk</p>
      </summary>
      <dl className="mt-3 space-y-2 border-t border-line pt-3 text-xs">
        <Row k="Current task">{desk.current ? `${desk.current.step} (stage: ${label(desk.current.stage)})` : "None"}</Row>
        <Row k="Business record">
          {focus ? <a href={`#${focus.id}`} className="text-accent">{focus.id} · {focus.contact.organization}</a> : "None"}
        </Row>
        <Row k="Source evidence">
          {focus
            ? `${label(focus.source)} · ${focus.source_ref} · consent: ${label(focus.consent.basis)}${focus.consent.date ? ` (${focus.consent.date})` : ""}`
            : "None"}
        </Row>
        <Row k="Exact draft or proposed action">
          {open[0] ? <ProposedAction payload={open[0].payload} /> : draft?.subject ? <ProposedAction payload={{ ...draft, recipients: focus ? [focus.contact.email] : [] }} /> : "None"}
        </Row>
        <Row k="Approval status">
          {desk.approvals.length
            ? desk.approvals.map((a) => `${a.approval_id ?? "none"}: ${label(a.status)}`).join("; ")
            : "Nothing waiting"}
        </Row>
        <Row k="Last governed action">
          {last ? `${last.action_type} · ${last.status}${last.replayed ? " (replayed)" : ""} · ${when(last.at)}` : "None recorded"}
          {last?.detail && <span className="block text-faint">{last.detail}</span>}
        </Row>
        <Row k="Last connector execution">
          {exec ? `${exec.connector} · ${label(exec.kind)} · ${when(exec.executed_at)} · ${label(exec.status)}` : "None recorded"}
        </Row>
        <Row k="External record reference">{exec ? <span className="mono">{exec.external_ref}</span> : "None"}</Row>
        <Row k="Errors and dependencies">{deps || "None"}</Row>
        <Row k="Next step">{focus?.plan.operator_step || focus?.plan.label || "None"}</Row>
        <Row k="Usage and cost">{desk.usage.note}</Row>
      </dl>
    </details>
  );
}

const LEAD_FIELDS = (rev: Revenue): FieldSpec[] => [
  { name: "contact_name", label: "Contact name", required: true },
  { name: "contact_email", label: "Contact email", required: true },
  { name: "contact_role", label: "Contact role" },
  { name: "organization", label: "Organization", required: true },
  { name: "region", label: "Region", initial: "Ontario" },
  { name: "city", label: "City" },
  { name: "sector", label: "Sector", hint: "For example healthcare, legal, accounting, manufacturing, municipal" },
  { name: "employees", label: "Employees", kind: "number" },
  { name: "stated_need", label: "Stated need, in their words", kind: "textarea", hint: "Kept as data. Never copied into a message." },
  { name: "source", label: "Lead source", kind: "select", options: Object.keys(rev.lead_sources), required: true },
  { name: "source_ref", label: "Source reference", required: true, hint: "Thread id, booking URI, or a short note" },
  { name: "consent_basis", label: "Consent basis", kind: "select", options: Object.keys(rev.consent_bases), required: true },
  { name: "consent_evidence", label: "Consent evidence", hint: "Where the consent is recorded (required unless 'none')" },
  { name: "consent_date", label: "Consent date (YYYY-MM-DD)" },
  { name: "rehearsal", label: "Rehearsal (test address only; never counted)", kind: "checkbox" },
];

const REASON: FieldSpec[] = [{ name: "reason", label: "Reason (12+ characters, recorded permanently)", kind: "textarea", required: true }];

function OpportunityCard({ opp, actions }: { opp: Opportunity; actions: ExternalAction[] }) {
  const id = opp.id;
  const proposal = actions.filter((a) => a.kind === "proposal_email" && a.receipt).at(-1);
  const q = opp.qualification;
  const openStage = !["lost", "in_fulfillment", "disqualified"].includes(opp.stage);
  return (
    <details id={id} className="min-w-0 rounded-xl border border-line bg-black/10 p-3">
      <summary className="cursor-pointer list-none">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold">{opp.contact.organization}</span>
          <StatusChip status={opp.stage} />
          {opp.rehearsal && <Chip color="var(--cg-paused)">rehearsal</Chip>}
          {opp.flags.length > 0 && <Chip color="var(--cg-warn)">{opp.flags.length} flag(s)</Chip>}
          <span className="mono text-[0.68rem] text-faint">{id}</span>
        </div>
        <p className="mt-1 text-xs text-dim">
          {opp.plan.label}{opp.plan.detail ? `: ${opp.plan.detail}` : ""}
        </p>
      </summary>
      <div className="mt-3 grid grid-cols-1 gap-4 border-t border-line pt-3 lg:grid-cols-2">
        <dl className="min-w-0 space-y-2 text-xs">
          <Row k="Contact">{opp.contact.name} · {opp.contact.email}{opp.contact.role ? ` · ${opp.contact.role}` : ""}</Row>
          <Row k="Source">{label(opp.source)} · <span className="mono">{opp.source_ref}</span></Row>
          <Row k="Consent">
            {label(opp.consent.basis)}{opp.consent.date ? ` on ${opp.consent.date}` : ""}{opp.consent.evidence ? ` · ${opp.consent.evidence}` : ""}
            {opp.consent.quote_requested_at ? ` · quote requested ${when(opp.consent.quote_requested_at)}` : ""}
          </Row>
          <Row k="Facts">
            {[opp.lead_facts.region, opp.lead_facts.city, opp.lead_facts.sector,
              opp.lead_facts.employees ? `${opp.lead_facts.employees} staff` : null].filter(Boolean).join(" · ") || "None recorded"}
          </Row>
          {opp.lead_facts.stated_need && (
            <Row k={`Stated need (untrusted data${opp.lead_facts.stated_need_quarantined ? ", quarantined" : ""})`}>
              <span className="whitespace-pre-line">{opp.lead_facts.stated_need}</span>
            </Row>
          )}
          <Row k="Qualification">
            {q.outcome ? `${label(q.outcome)} · score ${q.score} of ${q.threshold} needed` : "Not scored yet"}
            {q.rubric && (
              <ul className="mt-1 space-y-0.5">
                {q.rubric.map((r) => (
                  <li key={r.id}>{r.result === "met" ? "+" + r.points : r.result} · {r.label}{r.required ? " (required)" : ""}</li>
                ))}
              </ul>
            )}
          </Row>
          {(opp.research.items?.length ?? 0) > 0 && (
            <Row k="Research brief">
              <ul className="space-y-0.5">
                {opp.research.items!.map((r, i) => (
                  <li key={i}>{r.text} <span className="text-faint">({r.source ?? "unverified"})</span></li>
                ))}
              </ul>
            </Row>
          )}
          <Row k="Offer">{opp.offer_name ?? "Not matched"}</Row>
          {opp.flags.length > 0 && <Row k="Flags"><ul>{opp.flags.map((f) => <li key={f}>· {f}</li>)}</ul></Row>}
          <Row k="Money on this record">
            {Object.keys(opp.money).length === 0
              ? "None"
              : Object.entries(opp.money).map(([k, v]) => `${label(k)} ${money(v)}`).join(" · ")}
          </Row>
          <Row k="Timeline">
            <ol className="space-y-0.5">
              {opp.timeline.slice(-12).map((e, i) => (
                <li key={i}><span className="mono text-faint">{when(e.at)}</span> · {e.detail}{e.ref ? <span className="mono text-faint"> · {e.ref}</span> : null}</li>
              ))}
            </ol>
          </Row>
        </dl>
        <div className="flex min-w-0 flex-col items-start gap-2">
          {opp.plan.kind === "do" && (
            <ActionButton path={`revenue/opportunities/${id}/advance`} body={{}} variant="primary">
              Run next step: {opp.plan.label}
            </ActionButton>
          )}
          {["new", "qualified", "disqualified"].includes(opp.stage) && (
            <RevenueForm path={`revenue/opportunities/${id}/facts`} title="Update facts" variant="ghost"
              note="Changing facts re-runs qualification and cancels any open approval for this record."
              fields={[
                { name: "contact_role", label: "Contact role" }, { name: "region", label: "Region" },
                { name: "city", label: "City" }, { name: "sector", label: "Sector" },
                { name: "employees", label: "Employees", kind: "number" },
                { name: "stated_need", label: "Stated need", kind: "textarea" },
              ]} />
          )}
          {openStage && (
            <RevenueForm path={`revenue/opportunities/${id}/research`} title="Add sourced facts" variant="ghost"
              note="Each fact keeps its source. The Research Agent does not browse; a fact without a source is marked unverified."
              fields={[{ name: "facts", label: "Facts (JSON list)", kind: "json", required: true,
                initial: '[{"text": "", "source": "https://"}]' }]} />
          )}
          <RevenueForm path={`revenue/opportunities/${id}/events`} title="Record a client event" variant="ghost"
            fields={[
              { name: "kind", label: "What happened", kind: "select", required: true,
                options: ["reply_received", "meeting_booked", "quote_requested", "opt_out"] },
              { name: "external_ref", label: "Reference (message id or booking URI)", required: true },
              { name: "occurred_at", label: "When (ISO time with zone)", kind: "datetime", required: true },
              { name: "note", label: "Note", kind: "textarea", hint: "Kept as data only." },
            ]} />
          {opp.stage === "proposal_sent" && (
            <RevenueForm path={`revenue/opportunities/${id}/acceptance`} title="Record the client's acceptance" variant="ok"
              note="Only with evidence: the message or signed document where the client accepted."
              fields={[
                { name: "evidence_ref", label: "Evidence of acceptance", required: true },
                { name: "accepted_at", label: "Accepted at (ISO time with zone)", kind: "datetime", required: true },
                { name: "quoted_total_cents", label: "Accepted total in cents", kind: "number", required: true,
                  initial: typeof proposal?.payload.quoted_total_cents === "number" ? proposal.payload.quoted_total_cents : "" },
              ]} />
          )}
          {["invoiced", "paid"].includes(opp.stage) && (
            <RevenueForm path={`revenue/opportunities/${id}/payments`} title="Import a PayPal record" variant="ok"
              note="Copy each value from PayPal's own record (list_invoices, list_transactions, list_disputes), and paste the record exactly as the connector returned it."
              fields={[
                { name: "record", label: "Normalized record", kind: "json", required: true,
                  initial: JSON.stringify({ provider: "paypal", record_type: "invoice", external_ref: "", status: "",
                    gross_amount_cents: 0, currency: "CAD", occurred_at: "" }, null, 2) },
                { name: "raw_record", label: "Raw record from the connector", kind: "json", required: true, initial: "{}" },
              ]} />
          )}
          {opp.stage === "paid" && (
            <RevenueForm path={`revenue/opportunities/${id}/handoff`} title="Hand off to delivery" variant="ok"
              fields={[{ name: "authorization_ref", label: "Where the client's written authorization is kept", required: true }]} />
          )}
          {openStage && (
            <RevenueForm path={`revenue/opportunities/${id}/close`} title="Close as lost" variant="danger" fields={REASON} />
          )}
        </div>
      </div>
    </details>
  );
}

function verifyTemplate(a: ExternalAction): string {
  const blank = a.kind === "invoice"
    ? { invoice_id: "", status: "", total_cents: 0, currency: "", recipient_email: "" }
    : { message_id: "", to: [""], subject: "", sent_at: "" };
  return JSON.stringify(blank, null, 2);
}

function ActionCard({ action, opp }: { action: ExternalAction; opp?: Opportunity }) {
  const a = action;
  return (
    <li className="min-w-0 border-b border-line pb-4 [overflow-wrap:anywhere] last:border-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm">{label(a.kind)}</span>
        <StatusChip status={a.status} />
        <span className="mono text-xs text-faint">{a.id} · {a.connector}</span>
        {a.rehearsal && <Chip color="var(--cg-paused)">rehearsal</Chip>}
      </div>
      <p className="mt-1 text-xs text-dim">
        {opp ? <a className="text-accent" href={`#${opp.id}`}>{opp.contact.organization}</a> : a.opportunity_id}
        {" · "}approval <span className="mono">{a.approval_id ?? "none"}</span> · requested {when(a.created_at)}
      </p>
      {a.error && <p className="mt-1 text-xs text-bad">{a.error}</p>}
      {a.status === "awaiting_approval" && (
        <p className="mt-2 text-xs text-warn">Waiting for a decision in the <Link className="underline" href="/approvals">Approval Desk</Link>.</p>
      )}
      <div className="mt-2 flex flex-wrap items-start gap-2">
        {a.status === "approved" && (
          <ActionButton path={`revenue/actions/${a.id}/release`} variant="primary"
            confirm="Release this ticket? The state is checked again now, and the approval is used up.">
            Release ticket
          </ActionButton>
        )}
        {["approved", "released", "stale", "blocked", "awaiting_approval"].includes(a.status) && (
          <RevenueForm path={`revenue/actions/${a.id}/abandon`} title="Abandon" variant="ghost"
            note={a.status === "released" ? "This ticket was released: check the destination before abandoning it." : undefined}
            fields={[...REASON, { name: "reconciliation", label: "What you checked at the destination", kind: "textarea" }]} />
        )}
      </div>
      {a.ticket && a.status === "released" && (
        <div className="mt-3 space-y-2 rounded-lg border border-warn/30 bg-warn/5 p-3 text-xs">
          <p className="text-warn">{a.ticket.warning}</p>
          {a.ticket.steps.map((s, i) => (
            <div key={i}>
              <p className="text-ink">{i + 1}. {s.connector}: <span className="mono">{s.tool}</span></p>
              {s.note && <p className="text-dim">{s.note}</p>}
              {typeof s.fields.body === "string" ? (
                <div className="mt-1 space-y-1">
                  <p><span className="label">To </span>{(s.fields.to as string[]).join(", ")}</p>
                  <p><span className="label">Subject </span>{String(s.fields.subject)}</p>
                  <pre className="mono max-h-80 overflow-auto whitespace-pre-wrap rounded-lg border border-line bg-black/30 p-2 text-[0.7rem]">{s.fields.body}</pre>
                </div>
              ) : <Json value={s.fields} max={3000} />}
            </div>
          ))}
          <p className="text-dim">{a.ticket.record}</p>
          <RevenueForm path={`revenue/actions/${a.id}/receipt`} title="Record the receipt" variant="ok"
            fixed={{ payload_digest: a.payload_digest }}
            note="Record it only if what was sent is exactly this ticket."
            fields={[
              { name: "external_ref", label: a.kind === "invoice" ? "PayPal invoice id" : "Message id", required: true },
              { name: "executed_at", label: "Sent at (ISO time with zone)", kind: "datetime", required: true },
            ]} />
        </div>
      )}
      {a.receipt && (
        <p className="mono mt-2 text-[0.7rem] text-ok">
          sent · {a.receipt.connector} {a.receipt.external_ref} · {when(a.receipt.executed_at)} · recorded by {a.receipt.recorded_by}
        </p>
      )}
      {["executed", "verification_failed"].includes(a.status) && (
        <div className="mt-2">
          <RevenueForm path={`revenue/actions/${a.id}/verify`} title="Verify against the provider's record" variant="ok"
            note="Copy each value from the provider's own record, not from this page."
            fields={[{ name: "record", label: "Provider record", kind: "json", required: true, initial: verifyTemplate(a) }]} />
        </div>
      )}
      {a.verification?.mismatches && a.verification.mismatches.length > 0 && (
        <p className="mt-1 text-xs text-bad">Mismatches: {a.verification.mismatches.join("; ")}</p>
      )}
    </li>
  );
}

export default async function RevenuePage() {
  const { snap } = await getSnapshot();
  const rev = snap.revenue;
  if (!rev) {
    return (
      <>
        <PageHeader kicker="Governed sales path" title="Revenue Floor" />
        <Empty>This API does not serve the Revenue Floor. Update the Agent Office API.</Empty>
      </>
    );
  }
  const opps = Object.fromEntries(rev.opportunities.map((o) => [o.id, o]));
  const open = rev.opportunities.filter((o) => STAGES.includes(o.stage) && o.stage !== "in_fulfillment");
  const waiting = rev.actions.filter((a) => a.status === "awaiting_approval").length;
  const settings = rev.settings?.values;

  return (
    <>
      <PageHeader kicker={`Governed sales path · config ${rev.config_version}`} title="Revenue Floor">
        <Chip color={rev.readiness.ready_for_first_send ? "var(--cg-ok)" : "var(--cg-warn)"}>
          {rev.readiness.ready_for_first_send ? "ready for a first send" : `${rev.readiness.blockers} blocker(s)`}
        </Chip>
        <Chip>{open.length} open</Chip>
        {waiting > 0 && <Chip color="var(--cg-warn)">{waiting} awaiting approval</Chip>}
        {rev.paused.paused && <Chip color="var(--cg-paused)">paused</Chip>}
      </PageHeader>
      <p className="mb-4 max-w-4xl text-sm text-dim">{rev.execution_model}</p>

      <div className="mb-5 flex flex-wrap items-start gap-2">
        <RevenueForm path="revenue/opportunities" title="Record a lead" fields={LEAD_FIELDS(rev)}
          note="Authorized sources only, with the consent basis and its evidence. Nothing is sent." />
        <ActionButton path="revenue/cycle">Run one cycle</ActionButton>
        {rev.paused.paused
          ? <RevenueForm path="revenue/resume" title="Resume" variant="ok" fields={REASON} />
          : <RevenueForm path="revenue/pause" title="Pause the Revenue Floor" variant="danger" fields={REASON} />}
      </div>
      {rev.paused.paused && (
        <p role="alert" className="mb-4 rounded-lg border border-paused/40 bg-paused/10 px-3 py-2 text-sm">
          Paused by {rev.paused.by} at {when(rev.paused.at)}: {rev.paused.reason}. Facts and receipts can still be recorded.
        </p>
      )}

      <Panel kicker="One desk per role" title="The revenue team" className="mb-5">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {rev.team.map((d) => <DeskCard key={d.role} desk={d} opps={opps} actions={rev.actions} />)}
        </div>
      </Panel>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_25rem]">
        <div className="min-w-0 space-y-5">
          <Panel kicker="Pipeline" title="Opportunities by stage">
            {rev.opportunities.length === 0 ? (
              <Empty>No opportunities yet. Record a lead from an authorized source to start.</Empty>
            ) : (
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-3 2xl:grid-cols-5">
                {[...STAGES, ...CLOSED].map((stage) => {
                  const here = rev.opportunities.filter((o) => o.stage === stage);
                  if (here.length === 0) return null;
                  return (
                    <div key={stage} className="rounded-lg border border-line p-2">
                      <p className="label">{label(stage)} · {here.length}</p>
                      <ul className="mt-1 space-y-1 text-xs">
                        {here.map((o) => <li key={o.id}><a className="text-accent" href={`#${o.id}`}>{o.contact.organization}</a></li>)}
                      </ul>
                    </div>
                  );
                })}
              </div>
            )}
          </Panel>

          <Panel kicker="Business records" title={`${rev.opportunities.length} opportunities`}>
            {rev.opportunities.length === 0 ? <Empty>Nothing recorded.</Empty> : (
              <div className="space-y-3">
                {rev.opportunities.map((o) => (
                  <OpportunityCard key={o.id} opp={o} actions={rev.actions.filter((a) => a.opportunity_id === o.id)} />
                ))}
              </div>
            )}
          </Panel>

          <Panel kicker="Approved, released, executed, verified" title="External actions">
            {rev.actions.length === 0 ? <Empty>No external action has been requested.</Empty> : (
              <ul className="space-y-4">
                {[...rev.actions].reverse().map((a) => <ActionCard key={a.id} action={a} opp={opps[a.opportunity_id]} />)}
              </ul>
            )}
          </Panel>
        </div>

        <div className="min-w-0 space-y-5">
          <Panel kicker="Before the first live send" title="Readiness">
            <ul className="space-y-3">
              {rev.readiness.items.map((i) => (
                <li key={i.id} className="text-sm">
                  <div className="flex items-center gap-2">
                    <Chip color={i.severity === "blocker" ? "var(--cg-bad)" : "var(--cg-warn)"}>{i.severity}</Chip>
                    <span>{i.title}</span>
                  </div>
                  <p className="mt-1 text-xs text-dim">{i.detail}</p>
                  <p className="mt-0.5 text-xs text-faint">Owner: {i.owner_action}</p>
                </li>
              ))}
            </ul>
          </Panel>

          <Panel kicker="Each category separate" title="Money">
            <ul className="space-y-2">
              {rev.money.categories.map((c) => (
                <li key={c.id}>
                  <div className="flex items-baseline justify-between gap-2 text-sm">
                    <span>{c.label}</span>
                    <span className="mono tabular-nums">{money(c.value_cents, c.currency) ?? <span className="text-faint">not available</span>}</span>
                  </div>
                  <p className="text-[0.7rem] text-faint">{c.definition}</p>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-xs text-dim">Revenue recognition: not available. {rev.money.revenue_recognition.reason}</p>
            {rev.money.rehearsal_events_excluded > 0 && (
              <p className="mt-1 text-xs text-faint">{rev.money.rehearsal_events_excluded} rehearsal record(s) excluded.</p>
            )}
          </Panel>

          <Panel kicker={`${rev.metrics.window_days} days to ${when(rev.metrics.to)}`} title="Measured results">
            <ul className="space-y-2">
              {rev.metrics.items.map((m) => (
                <li key={m.id}>
                  <div className="flex items-baseline justify-between gap-2 text-sm">
                    <span>{m.label}</span>
                    <span className="mono tabular-nums">{metricValue(m)}</span>
                  </div>
                  <p className="text-[0.7rem] text-faint">
                    {m.definition}{m.denominator !== null && m.unit === "ratio" ? ` (${m.numerator} of ${m.denominator})` : ""}
                  </p>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-faint">{rev.metrics.excludes}</p>
          </Panel>

          <Panel kicker="Published offers" title="Offer catalog">
            <ul className="space-y-4">
              {rev.offers.map((o) => (
                <li key={o.sku} className="space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold">{o.name}</span>
                    <span className="mono text-xs">{o.price_text}</span>
                    <StatusChip status={o.status === "candidate" ? "pending" : o.status} />
                  </div>
                  <p className="text-xs text-dim">{o.summary} Published at {o.published_at.join(", ")} (checked {o.published_checked}).</p>
                  <ul className="text-xs text-dim">{o.scope.map((s) => <li key={s}>· {s}</li>)}</ul>
                  {o.status === "approved" && o.decision && <Json value={o.decision} />}
                  {o.missing_decisions.length > 0 && (
                    <p className="text-xs text-warn">The owner still decides: {o.missing_decisions.map(label).join(", ")}.</p>
                  )}
                  <div className="flex flex-wrap gap-2">
                    {o.status !== "approved" && (
                      <RevenueForm path={`revenue/offers/${o.sku}/decision`} title="Approve with terms" variant="ok"
                        fixed={{ decision: "approve" }}
                        note="Your terms are bound to the offer's exact content. A later change to either needs a new approval."
                        fields={[
                          { name: "exclusions", label: "Not included (one per line)", kind: "list", required: true, group: "terms" },
                          { name: "delivery_capacity_per_week", label: "Audits you can deliver per week", kind: "number", required: true, group: "terms" },
                          { name: "turnaround_business_days", label: "Turnaround (business days)", kind: "number", required: true, group: "terms" },
                          { name: "payment_due_days", label: "Payment due (days after invoice)", kind: "number", required: true, group: "terms" },
                          { name: "tax_basis_points", label: "Sales tax in basis points", kind: "number", required: true, group: "terms",
                            hint: "1300 = 13%. Whether to charge HST depends on your GST/HST registration: your or your accountant's decision." },
                          { name: "terms_ref", label: "Where the engagement terms live", required: true, group: "terms" },
                          ...REASON,
                        ]} />
                    )}
                    {o.status === "candidate" && (
                      <RevenueForm path={`revenue/offers/${o.sku}/decision`} title="Reject" variant="danger" fixed={{ decision: "reject" }} fields={REASON} />
                    )}
                    {o.status === "approved" && (
                      <RevenueForm path={`revenue/offers/${o.sku}/decision`} title="Retire" variant="danger" fixed={{ decision: "retire" }} fields={REASON} />
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </Panel>

          <Panel kicker="CASL s.6(2): who sent it, how to reach them, how to stop" title="Sender identity">
            {settings ? (
              <dl className="space-y-1 text-xs">
                {Object.entries(settings).map(([k, v]) => (
                  <Row key={k} k={label(k)}>{Array.isArray(v) ? v.join(", ") || "none" : String(v)}</Row>
                ))}
                <p className="text-faint">Set by {rev.settings!.updated_by} at {when(rev.settings!.updated_at)}</p>
              </dl>
            ) : <Empty>Not set. No message can be drafted until it is.</Empty>}
            <div className="mt-3">
              <RevenueForm path="revenue/settings" title={settings ? "Change" : "Set sender identity"} variant="ghost"
                note="Changing these makes every unreleased approval stale."
                fields={[
                  { name: "business_name", label: "Business name", required: true, initial: String(settings?.business_name ?? "ClearGlass Inc.") },
                  { name: "mailing_address", label: "Mailing address", required: true, initial: String(settings?.mailing_address ?? "") },
                  { name: "email", label: "Sending email address", required: true, initial: String(settings?.email ?? "") },
                  { name: "website", label: "Website (https://)", initial: String(settings?.website ?? "") },
                  { name: "booking_url", label: "Booking link (https://)", initial: String(settings?.booking_url ?? "") },
                  { name: "email_connector", label: "Mailbox connector", kind: "select", options: ["gmail", "microsoft_365"], required: true,
                    initial: String(settings?.email_connector ?? "") },
                  { name: "own_payer_emails", label: "Your own payer addresses (one per line)", kind: "list" },
                  { name: "rehearsal_recipients", label: "Rehearsal recipients (one per line)", kind: "list" },
                ]} />
            </div>
          </Panel>

          <Panel kicker="Never contacted again" title={`Suppressions · ${rev.suppressions.count}`}>
            {rev.suppressions.recent.length > 0 && (
              <ul className="mb-3 space-y-1 text-xs text-dim">
                {rev.suppressions.recent.map((s) => <li key={s.seq}><span className="mono">{s.address}</span> · {s.reason} · {when(s.recorded_at)}</li>)}
              </ul>
            )}
            <RevenueForm path="revenue/suppressions" title="Add a suppression" variant="ghost"
              fields={[
                { name: "address", label: "Email or @domain", required: true },
                { name: "reason", label: "Reason", required: true },
                { name: "source_ref", label: "Where the request came from", required: true },
              ]} />
          </Panel>

          <Panel kicker="Direct operating costs" title="Record a cost">
            <RevenueForm path="revenue/costs" title="Record a cost" variant="ghost"
              fields={[
                { name: "description", label: "What it was", required: true },
                { name: "amount_cents", label: "Amount in cents", kind: "number", required: true },
                { name: "currency", label: "Currency", initial: "CAD", required: true },
                { name: "evidence_ref", label: "Receipt or invoice reference", required: true },
                { name: "occurred_at", label: "When (ISO time with zone)", kind: "datetime", required: true },
              ]} />
          </Panel>

          <Panel kicker={`Recorded ${rev.connectors.checked_at}`} title="Connectors">
            <p className="mb-2 text-xs text-faint">{rev.connectors.method}</p>
            <ul className="space-y-2">
              {rev.connectors.connectors.map((c) => (
                <li key={c.id} className="text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm">{c.name}</span>
                    <Chip color={c.status === "connected" ? "var(--cg-ok)" : "var(--cg-bad)"}>{label(c.status)}</Chip>
                  </div>
                  {c.used_for.length > 0 && <p className="text-dim">Used for: {c.used_for.map(label).join(", ")}</p>}
                  {c.limits.map((l) => <p key={l} className="text-faint">{l}</p>)}
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>
    </>
  );
}
