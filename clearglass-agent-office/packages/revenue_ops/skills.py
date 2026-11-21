"""Revenue Floor skills: the handlers agents run through the governed executor.

Each one runs only after the policy gate allowed the action (steps 1-6), and its
output is verified (step 8) and sealed into the audit chain (step 9) like any
other agent action. Handlers build their output from their parameters and from
recorded office state. They never send, never write outside their return value,
and raise instead of returning a result they cannot stand behind.

The external actions of the sales path (``outreach.send``, ``proposal.send``,
``invoice.send``) have no handler here on purpose: their tools are dry-run, so
releasing one produces a receipt bound to the approved payload and nothing more.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from revenue_ops import rules

if TYPE_CHECKING:
    from agent_core.office import Office

Ctx = dict[str, Any]

LEAD_REQUIRED = (
    "opportunity_id",
    "source",
    "source_ref",
    "consent_basis",
    "contact_email",
    "contact_name",
    "organization",
)


def _office(ctx: Ctx) -> Office:
    return ctx["office"]


def crm_record_lead(ctx: Ctx) -> dict[str, Any]:
    p = ctx["params"]
    missing = [k for k in LEAD_REQUIRED if not p.get(k)]
    if missing:
        raise ValueError(f"lead record is missing {missing}")
    if "stated_need" in p:
        raise ValueError("free text from a lead never enters an action payload")
    return {
        "summary": f"Lead recorded for {p['organization']} from {p['source']}",
        "artifact": {"record": dict(p), "status": "recorded"},
    }


def leads_qualify(ctx: Ctx) -> dict[str, Any]:
    p = ctx["params"]
    icp = _office(ctx).company().ideal_customer_profile
    result = rules.qualify(p["facts"], p["criteria"], int(p["threshold"]), icp)
    return {
        "summary": f"{p['opportunity_id']}: {result['outcome'].replace('_', ' ')} (score {result['score']}"
        f" of {result['threshold']} needed)",
        "artifact": {**result, "opportunity_id": p["opportunity_id"], "record_version": p["record_version"]},
        "decision": {
            "kind": "agent",
            "summary": f"Qualification of {p['opportunity_id']}: {result['outcome'].replace('_', ' ')}",
            "rationale": result["why"],
            "outcome": result["outcome"],
        },
    }


def crm_update_opportunity(ctx: Ctx) -> dict[str, Any]:
    p = ctx["params"]
    if p.get("change") != "match_offer":
        raise ValueError(f"unsupported opportunity change {p.get('change')!r}")
    offer = _office(ctx).revenue.offer_state(str(p.get("offer_sku")))
    if offer["status"] != "approved" or offer["approved_digest"] != p.get("offer_digest"):
        raise PermissionError("the offer is not approved with this exact content")
    return {
        "summary": f"{p['opportunity_id']}: matched to the approved {offer['name']}",
        "artifact": {
            "opportunity_id": p["opportunity_id"],
            "offer_sku": p["offer_sku"],
            "offer_digest": p["offer_digest"],
        },
    }


def outreach_compose(ctx: Ctx) -> dict[str, Any]:
    p = ctx["params"]
    draft = _office(ctx).revenue.compose_draft(p)
    return {
        "summary": f"Drafted the {p['kind']} email for {p['opportunity_id']} (not sent)",
        "artifact": {**draft, "status": "draft: sending needs operator approval"},
    }


def payment_reconcile(ctx: Ctx) -> dict[str, Any]:
    p = ctx["params"]
    record = p["record"]
    kind, verification = rules.classify_payment_record(record)
    problems: list[str] = []
    if record["currency"] != p["currency"]:
        problems.append(f"currency {record['currency']} does not match the invoice currency {p['currency']}")
    target = record["external_ref"] if record["record_type"] == "invoice" else record.get("invoice_ref")
    if record["record_type"] in ("invoice", "transaction") and target != p["invoice_ref"]:
        problems.append("the record does not belong to this opportunity's invoice; an unmatched payment is not a sale")
    payer = record.get("payer_email")
    if payer and payer in p["own_payer_emails"]:
        problems.append("the payer is one of ClearGlass's own accounts: a transfer, not a sale")
    if kind == "payment_received":
        amount = record["gross_amount_cents"]
        if amount <= 0:
            problems.append("a received payment needs an amount above zero")
        elif p["received_so_far_cents"] + amount > p["expected_total_cents"]:
            problems.append(
                f"{rules.money_text(amount, p['currency'])} would take receipts above the invoice total of"
                f" {rules.money_text(p['expected_total_cents'], p['currency'])}; check the record"
            )
    if problems:
        raise ValueError("; ".join(problems))
    return {
        "summary": f"{p['opportunity_id']}: PayPal {record['record_type']} {record['status']} reconciled as {kind}",
        "artifact": {
            "kind": kind,
            "verification": verification,
            "matched_invoice": p["invoice_ref"],
            "amount_cents": record["gross_amount_cents"],
            "currency": record["currency"],
        },
    }


def fulfillment_handoff(ctx: Ctx) -> dict[str, Any]:
    p = ctx["params"]
    if not p.get("authorization_ref"):
        raise ValueError("an authorization reference is required before any assessment work")
    checklist = [
        *p["requirements"],
        f"Authorization on record: {p['authorization_ref']}",
        "Deliver the approved scope and nothing outside it",
        "Record delivery in the Revenue Floor when the readout is done",
    ]
    return {
        "summary": f"{p['opportunity_id']}: handed to delivery",
        "artifact": {"opportunity_id": p["opportunity_id"], "offer_sku": p["offer_sku"], "checklist": checklist},
        "messages": [
            {
                "to": "operator",
                "kind": "handoff",
                "subject": f"Delivery handoff: {p['offer_name']} for {p['organization']}",
                "body": "\n".join(f"- {item}" for item in checklist),
            }
        ],
    }


REVENUE_HANDLERS: dict[str, Any] = {
    "crm.record_lead": crm_record_lead,
    "leads.qualify": leads_qualify,
    "crm.update_opportunity": crm_update_opportunity,
    "outreach.compose": outreach_compose,
    "payment.reconcile": payment_reconcile,
    "fulfillment.handoff": fulfillment_handoff,
}
