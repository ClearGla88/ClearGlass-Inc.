"""The Revenue Floor: one governed sales path, from an authorized lead to a verified payment.

existing lead -> qualification -> approved offer -> approved email -> reply or meeting
-> proposal -> recorded acceptance -> invoice -> verified payment -> delivery handoff

How work moves:

- Agents do the internal steps (record, qualify, match, draft, reconcile, hand off)
  through ``Office.perform``, so each one passes the nine-step policy pipeline and is
  sealed into the audit chain. The Revenue Director's ``advance`` runs one step per
  opportunity per call and stops at every external boundary.
- External steps (an email, a proposal, an invoice) are requested by an agent, held
  at the Approval Desk bound to their exact payload, and released by the operator as
  a ticket immediately after the state is checked again. A person then executes the
  ticket through the connector's own interface (PayPal's invoice form, the mailbox)
  and records the provider's reference. The office never calls a provider.
- Customer facts (a reply, a meeting, an acceptance) and provider records (a payment)
  are recorded by the operator with their external reference. Money is called
  received only on a provider record whose status says so.

Nothing here guesses: an unknown status, a stale record, a missing consent basis, or a
reference recorded twice is refused with the reason.
"""

from __future__ import annotations

import sqlite3
import statistics
import threading
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from agent_core.approvals import ApprovalError, Principal
from agent_core.models import Agent, ExternalAction, MoneyEvent, Opportunity
from audit_ledger.canonical import digest
from policy_engine.engine import ActionRequest
from revenue_ops import compose, rules
from revenue_ops.catalog import load_revenue_config

if TYPE_CHECKING:
    from agent_core.governance import PerformResult
    from agent_core.office import Office


class RevenueError(ValueError):
    """A request the Revenue Floor refuses. The message says why and what to change."""


class RevenueConflict(RevenueError):
    """The request is valid but the current state does not allow it."""


class RevenueNotFound(RevenueError):
    pass


TEAM: tuple[tuple[str, str, str], ...] = (
    ("director", "revenue.director", "Revenue Director"),
    ("opportunity", "revenue.opportunity", "Opportunity Agent"),
    ("research", "revenue.lead-research", "Research Agent"),
    ("qualification", "revenue.qualification", "Qualification Agent"),
    ("outreach", "revenue.sales-strategist", "Outreach Agent"),
    ("proposal", "revenue.proposal-writer", "Proposal Agent"),
    ("delivery", "revenue.delivery", "Revenue and Delivery Agent"),
)
ROLE_AGENT = {role: agent for role, agent, _ in TEAM}

# external action kind -> (action type, role that requests it, label)
ACTION_KINDS: dict[str, tuple[str, str, str]] = {
    "outreach_email": ("outreach.send", "outreach", "first email"),
    "proposal_email": ("proposal.send", "outreach", "proposal email"),
    "invoice": ("invoice.send", "delivery", "invoice"),
}
OPEN_ACTION_STATUSES = frozenset({"awaiting_approval", "approved", "released"})
EVENT_KINDS = ("reply_received", "meeting_booked", "quote_requested", "opt_out")
CUSTOMER_EVENTS = frozenset({"reply_received", "meeting_booked", "quote_requested"})
DESK_STATES = (
    "idle",
    "queued",
    "working",
    "awaiting_approval",
    "waiting_for_customer",
    "waiting_for_payment",
    "blocked",
    "completed",
    "failed",
    "paused",
)
EXECUTION_MODEL = (
    "The office never contacts a provider. An approved action is released as a ticket; a person executes it"
    " through the connector's own interface and records the provider's reference, which is then checked"
    " against the provider's record."
)
USAGE_NOTE = "Not measured. The office does not meter model, connector, or provider usage or cost."


class RevenueDesk:
    def __init__(self, office: Office) -> None:
        self.office = office
        self.cfg = load_revenue_config(office.base_dir / "config" / "revenue.json")
        self.lock = threading.RLock()
        configured = {a.id for a in office.config.agents}
        missing = [a for _, a, _ in TEAM if a not in configured]
        if missing:
            raise RevenueError(f"config/org.json is missing the revenue team: {missing}")

    # -- small helpers ----------------------------------------------------------------------------

    def _now(self) -> datetime:
        return self.office.clock.now()

    def _iso(self) -> str:
        return self.office.clock.iso()

    def _human(self, principal: Principal) -> None:
        if principal.kind != "human" or principal.role not in self.office.policy.approver_roles:
            actor_type = principal.kind if principal.kind in ("agent", "human") else "system"
            self.office.log(
                principal.id, actor_type, "revenue.refused_principal", "revenue", {"reason": "operator only"}, "high"
            )
            raise ApprovalError("only a human operator can do this on the Revenue Floor")

    def _reason(self, reason: str | None) -> str:
        reason = (reason or "").strip()
        if len(reason) < self.office.policy.min_reason_chars:
            raise RevenueError(f"a reason of at least {self.office.policy.min_reason_chars} characters is required")
        return reason

    def paused_state(self) -> dict[str, Any]:
        return self.office.store.get_state("revenue.paused", {"paused": False})

    def _running(self) -> None:
        if self.office.halted:
            raise RevenueConflict("the emergency stop is engaged: the Revenue Floor is frozen")
        paused = self.paused_state()
        if paused.get("paused"):
            raise RevenueConflict(f"the Revenue Floor is paused: {paused.get('reason')}")

    def settings(self) -> dict[str, Any] | None:
        stored = self.office.store.get_state("revenue.settings")
        return dict(stored["values"]) if stored else None

    def settings_digest(self) -> str | None:
        s = self.settings()
        return digest(s) if s else None

    def _text(self, value: Any, name: str, lo: int = 2, hi: int = 300) -> str:
        try:
            return rules.validate_fields({name: value}, {name: rules.Field("str", True, lo, hi)}, name)[name]
        except rules.RuleError as exc:
            raise RevenueError(str(exc)) from exc

    def _when(self, value: Any, name: str) -> datetime:
        dt = rules.parse_datetime(value)
        if dt is None:
            raise RevenueError(f"{name} must be an ISO 8601 time with a zone, for example 2026-11-19T14:05:00Z")
        if dt > self._now() + timedelta(minutes=5):
            raise RevenueError(f"{name} is in the future")
        return dt

    def _perform(
        self,
        agent_id: str,
        action_type: str,
        params: dict[str, Any],
        *,
        opp_id: str,
        approval_id: str | None = None,
        key: str | None = None,
    ) -> PerformResult:
        result = self.office.perform(
            ActionRequest(
                agent_id=agent_id,
                action_type=action_type,
                params=params,
                approval_id=approval_id,
                idempotency_key=key,
            )
        )
        activity = self.office.store.get_state("revenue.activity", {})
        activity[agent_id] = {
            "at": self._iso(),
            "action_type": action_type,
            "opportunity_id": opp_id,
            "status": result.status,
            "detail": (result.output or {}).get("summary") if result.status == "completed" else result.error,
            "tier": result.decision.tier,
            "approval_id": result.approval.id if result.approval else approval_id,
            "replayed": result.replayed,
        }
        self.office.store.set_state("revenue.activity", activity)
        return result

    @staticmethod
    def _completed(result: PerformResult, what: str) -> dict[str, Any]:
        if result.status != "completed" or result.output is None:
            raise RevenueConflict(f"{what} did not complete ({result.status}): {result.error or 'no output'}")
        return result.output

    # -- records -----------------------------------------------------------------------------------

    def get(self, opp_id: str) -> Opportunity:
        opp = self.office.store.get(Opportunity, opp_id)
        if opp is None:
            raise RevenueNotFound(f"unknown opportunity {opp_id!r}")
        return opp

    def opportunities(self) -> list[Opportunity]:
        return self.office.store.list(Opportunity)

    def actions(self, opp_id: str | None = None) -> list[ExternalAction]:
        items = self.office.store.list(ExternalAction, lambda a: opp_id is None or a.opportunity_id == opp_id)
        return [self._sync_action(a) for a in items]

    def action(self, action_id: str) -> ExternalAction:
        action = self.office.store.get(ExternalAction, action_id)
        if action is None:
            raise RevenueNotFound(f"unknown action {action_id!r}")
        return self._sync_action(action)

    def _save_action(self, action: ExternalAction) -> None:
        action.updated_at = self._iso()
        self.office.store.put(action, action.updated_at)

    def _save(self, opp: Opportunity, *, material: bool = False) -> None:
        if material:
            opp.content_version += 1
        opp.updated_at = self._iso()
        self.office.store.put(opp, opp.updated_at)

    def _event(
        self, opp: Opportunity, kind: str, detail: str, *, by: str, ref: str | None = None, at: str | None = None
    ) -> None:
        opp.timeline.append({"at": at or self._iso(), "kind": kind, "detail": detail, "by": by, "ref": ref})
        actor_type = "human" if by.startswith("operator") else "agent" if "." in by else "system"
        self.office.log(by, actor_type, f"revenue.{kind}", opp.id, {"stage": opp.stage, "ref": ref})

    def _sync_action(self, action: ExternalAction) -> ExternalAction:
        """Mirror the Approval Desk's decision onto an action that is still waiting for one."""
        if action.status not in ("awaiting_approval", "approved") or not action.approval_id:
            return action
        approval = self.office.desk.get(action.approval_id)
        if approval is None:
            return action
        status = {
            "pending": "awaiting_approval",
            "approved": "approved",
            "rejected": "rejected",
            "changes_requested": "rejected",
            "expired": "expired",
            "cancelled": "cancelled",
        }.get(approval.status, action.status)
        if status != action.status:
            action.status = status
            self._save_action(action)
        return action

    def _cancel_open(self, opp: Opportunity, principal_id: str, reason: str) -> list[str]:
        """Cancel every approval that could still lead to a send for ``opp``."""
        cancelled = []
        now = self._iso()
        for a in self.actions(opp.id):
            if a.status in ("awaiting_approval", "approved", "stale", "blocked") and a.approval_id:
                approval = self.office.desk.get(a.approval_id)
                if approval is not None and approval.status in ("pending", "approved"):
                    self.office.store.append_decision(
                        approval_id=approval.id,
                        decision="cancelled",
                        reason=reason,
                        decided_by=principal_id,
                        decided_at=now,
                        modifications=None,
                        resulting_digest=None,
                    )
                    approval.status = "cancelled"
                    approval.updated_at = now
                    approval.decisions = []
                    self.office.store.put(approval, now)
                    self.office.log(
                        principal_id, "human", "approval.cancelled", approval.id, {"reason": reason}, "high"
                    )
                if a.status in ("awaiting_approval", "approved"):
                    a.status = "cancelled"
                    a.error = reason
                    self._save_action(a)
                    cancelled.append(a.id)
            elif a.status == "released":
                a.error = (
                    f"{reason}. This ticket was already released: do not execute it;"
                    " if it was executed, record the receipt."
                )
                self._save_action(a)
        return cancelled

    # -- offers and settings ------------------------------------------------------------------------

    def offer_state(self, sku: str) -> dict[str, Any]:
        published = self.cfg.offers.get(sku)
        if published is None:
            raise RevenueNotFound(f"unknown offer {sku!r}")
        decisions = self.office.store.offer_decisions(sku)
        last = decisions[-1] if decisions else None
        status, approved_digest, decision = "candidate", None, None
        if last is not None:
            if last.decision == "approve":
                decision = last.offer.get("decision")
                current = rules.offer_digest(rules.offer_content(published, decision))
                status = "approved" if current == last.offer_digest else "changed_since_approval"
                approved_digest = last.offer_digest if status == "approved" else None
            else:
                status = {"reject": "rejected", "retire": "retired"}[last.decision]
        bp = (decision or {}).get("tax_basis_points", 0)
        return {
            **{k: published[k] for k in (*rules.PUBLISHED_OFFER_KEYS, "published_checked")},
            "price_text": rules.money_text(published["price_cents"], published["currency"]),
            "status": status,
            "approved_digest": approved_digest,
            "decision": decision,
            "total_cents": rules.invoice_total_cents(published["price_cents"], bp) if decision else None,
            "missing_decisions": [] if status == "approved" else list(rules.OFFER_DECISION_SCHEMA),
            "last_decision": (
                {k: getattr(last, k) for k in ("seq", "decision", "reason", "decided_by", "decided_at", "offer_digest")}
                if last
                else None
            ),
            "content": rules.offer_content(published, decision),
        }

    def offers(self) -> list[dict[str, Any]]:
        return [self.offer_state(sku) for sku in self.cfg.offers]

    def approved_offers(self) -> list[dict[str, Any]]:
        return [o for o in self.offers() if o["status"] == "approved"]

    def decide_offer(
        self, principal: Principal, sku: str, decision: str, reason: str, terms: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        with self.lock:
            self._human(principal)
            reason = self._reason(reason)
            state = self.offer_state(sku)
            published = self.cfg.offers[sku]
            if decision == "approve":
                if terms is None:
                    raise RevenueError(
                        "approving an offer needs the owner's terms: " + ", ".join(rules.OFFER_DECISION_SCHEMA)
                    )
                try:
                    fields = rules.validate_fields(terms, rules.OFFER_DECISION_SCHEMA, "offer terms")
                except rules.RuleError as exc:
                    raise RevenueError(str(exc)) from exc
                if rules.credential_rules(fields):
                    raise RevenueError("credential-shaped text in the offer terms")
                content = rules.offer_content(published, fields)
                if state["status"] == "approved" and state["approved_digest"] == rules.offer_digest(content):
                    raise RevenueConflict("the offer is already approved with exactly this content")
            elif decision == "reject":
                if terms:
                    raise RevenueError("a rejection takes no terms")
                content = rules.offer_content(published, None)
            elif decision == "retire":
                if state["status"] != "approved":
                    raise RevenueConflict("only an approved offer can be retired")
                content = state["content"]
            else:
                raise RevenueError("decision must be approve, reject, or retire")
            dig = rules.offer_digest(content)
            rec = self.office.store.append_offer_decision(
                sku=sku,
                decision=decision,
                offer=content,
                offer_digest=dig,
                reason=reason,
                decided_by=principal.id,
                decided_at=self._iso(),
            )
            self.office.log(
                principal.id,
                "human",
                f"revenue.offer_{decision}",
                sku,
                {"offer_digest": dig, "reason": reason, "decision_seq": rec.seq},
                "high",
            )
            self.office.record_decision(
                made_by=principal.id,
                kind="operator",
                summary=f"Offer {decision}: {published['name']}",
                rationale=reason,
                outcome=decision,
                refs=[sku, dig],
            )
            return self.offer_state(sku)

    def set_settings(self, principal: Principal, raw: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            self._human(principal)
            try:
                clean = rules.validate_fields(raw, rules.SETTINGS_SCHEMA, "Revenue settings")
            except rules.RuleError as exc:
                raise RevenueError(str(exc)) from exc
            if rules.credential_rules(clean):
                raise RevenueError("credential-shaped text in the settings")
            hits = rules.instruction_markers(
                " ".join(str(v) for v in clean.values()), self.office.policy.injection_markers
            )
            if hits:
                raise RevenueError(f"instruction-like text in the settings ({', '.join(hits)})")
            clean.setdefault("rehearsal_recipients", [])
            # Money from the business's own mailbox address is a transfer, never a sale.
            clean["own_payer_emails"] = sorted({*clean.get("own_payer_emails", []), clean["email"]})
            previous = self.settings_digest()
            stored = {"values": clean, "updated_by": principal.id, "updated_at": self._iso()}
            self.office.store.set_state("revenue.settings", stored)
            self.office.log(
                principal.id,
                "human",
                "revenue.settings_updated",
                "revenue",
                {"digest": digest(clean), "previous_digest": previous, "fields": sorted(clean)},
                "high",
            )
            return self.settings_view()

    def settings_view(self) -> dict[str, Any] | None:
        stored = self.office.store.get_state("revenue.settings")
        if not stored:
            return None
        return {**stored, "digest": digest(stored["values"])}

    def pause(self, principal: Principal, reason: str) -> dict[str, Any]:
        with self.lock:
            self._human(principal)
            reason = self._reason(reason)
            state = {"paused": True, "reason": reason, "by": principal.id, "at": self._iso()}
            self.office.store.set_state("revenue.paused", state)
            self.office.log(principal.id, "human", "revenue.paused", "revenue", {"reason": reason}, "high")
            return state

    def resume(self, principal: Principal, reason: str) -> dict[str, Any]:
        with self.lock:
            self._human(principal)
            reason = self._reason(reason)
            state = {"paused": False, "resumed_by": principal.id, "at": self._iso(), "reason": reason}
            self.office.store.set_state("revenue.paused", state)
            self.office.log(principal.id, "human", "revenue.resumed", "revenue", {"reason": reason}, "high")
            return state

    def readiness(self) -> dict[str, Any]:
        """What stands between this system and its first live send, each with the owner's next action."""
        items: list[dict[str, str]] = []

        def add(item_id: str, severity: str, title: str, detail: str, action: str) -> None:
            items.append(
                {"id": item_id, "severity": severity, "title": title, "detail": detail, "owner_action": action}
            )

        if self.office.halted:
            add(
                "emergency_stop",
                "blocker",
                "Emergency stop engaged",
                "Nothing can run.",
                "Investigate, then release the stop.",
            )
        paused = self.paused_state()
        if paused.get("paused"):
            add("paused", "blocker", "Revenue Floor paused", str(paused.get("reason")), "Resume it with a reason.")
        if not self.approved_offers():
            for o in self.offers():
                add(
                    f"offer:{o['sku']}",
                    "blocker",
                    f"Offer not approved: {o['name']} ({o['price_text']})",
                    f"Status: {o['status'].replace('_', ' ')}. The owner still has to decide: "
                    + ", ".join(d.replace("_", " ") for d in o["missing_decisions"])
                    + ".",
                    "Approve the offer with its exclusions, weekly capacity, turnaround, payment terms, sales tax"
                    " and engagement-terms reference, or reject it.",
                )
        inventory = {c["id"]: c for c in self.cfg.connector_inventory.get("connectors", [])}
        s = self.settings()
        if not s:
            add(
                "settings",
                "blocker",
                "Sender identity not set",
                "CASL s.6(2) requires every commercial email to identify the sender, give contact information,"
                " and carry an unsubscribe mechanism.",
                "Set the business name, mailing address, sending email and email connector in Revenue settings.",
            )
        else:
            conn = inventory.get(s["email_connector"], {})
            if conn.get("status") != "connected":
                add(
                    "email_channel",
                    "blocker",
                    f"{conn.get('name', s['email_connector'])} is not connected",
                    "The chosen mailbox cannot send through a connector.",
                    "Connect it in claude.ai connector settings, or choose a connected mailbox.",
                )
            if s["email_connector"] == "gmail":
                add(
                    "mailbox_identity",
                    "check",
                    "Confirm the sending mailbox",
                    "At the 2026-11-19 check, the connected Gmail account held no mail for the business address"
                    " published on the website.",
                    "Send only from the address in Revenue settings: connect that mailbox, or change the setting.",
                )
        add(
            "counsel_review",
            "check",
            "Counsel review before the first live send",
            self.cfg.consent_note + " The engagement terms and the client authorization wording need the same review.",
            "Have counsel confirm the consent rules, the engagement terms and the authorization wording.",
        )
        stripe = inventory.get("stripe")
        if stripe and stripe.get("status") != "connected":
            add(
                "stripe",
                "check",
                "Website Payment Links cannot be verified",
                (stripe.get("limits") or [""])[0],
                "Reconnect Stripe, then add a Stripe import path before relying on website checkouts.",
            )
        add(
            "operator_identity",
            "check",
            "Operator sign-in is a shared token",
            "Approvals record whoever holds the operator token, not a named person. OIDC sign-in is on the roadmap.",
            "Keep the operator token with one person until OIDC sign-in exists.",
        )
        blockers = [i for i in items if i["severity"] == "blocker"]
        return {"ready_for_first_send": not blockers, "blockers": len(blockers), "items": items}

    # -- suppression ----------------------------------------------------------------------------------

    def suppressed(self, email: str) -> bool:
        email = email.lower()
        domain = "@" + email.rsplit("@", 1)[-1]
        return any(s.address in (email, domain) for s in self.office.store.suppressions())

    def add_suppression(self, principal: Principal, address: str, reason: str, source_ref: str) -> dict[str, Any]:
        with self.lock:
            self._human(principal)
            raw = str(address or "").strip().lower()
            if raw.startswith("@"):
                if not rules.normalize_email("x" + raw):
                    raise RevenueError("a domain suppression must look like @example.ca")
                clean = raw
            else:
                clean = rules.normalize_email(raw) or ""
                if not clean:
                    raise RevenueError("address must be an email address or an @domain")
            reason = self._text(reason, "reason", 3, 300)
            source_ref = self._text(source_ref, "source_ref", 2, 300)
            existing = [s for s in self.office.store.suppressions() if s.address == clean]
            if existing:
                return {"suppression": existing[0].to_dict(), "duplicate": True, "cancelled": []}
            rec = self.office.store.append_suppression(
                address=clean, reason=reason, source_ref=source_ref, recorded_by=principal.id, recorded_at=self._iso()
            )
            self.office.log(
                principal.id, "human", "revenue.suppression_added", "revenue", {"address_digest": digest(clean)}, "high"
            )
            cancelled: list[str] = []
            for opp in self.opportunities():
                if self.suppressed(opp.contact["email"]):
                    cancelled += self._cancel_open(opp, principal.id, "the contact is on the suppression list")
            return {"suppression": rec.to_dict(), "duplicate": False, "cancelled": cancelled}

    # -- intake, facts, research ----------------------------------------------------------------------

    def intake(self, principal: Principal, raw: dict[str, Any]) -> Opportunity:
        with self.lock:
            self._human(principal)
            self._running()
            try:
                clean = rules.validate_fields(
                    raw, rules.lead_schema(self.cfg.lead_sources, self.cfg.consent_bases), "lead"
                )
            except rules.RuleError as exc:
                raise RevenueError(str(exc)) from exc
            if rules.credential_rules(raw):
                raise RevenueError("credential-shaped text in the lead; it was not recorded")
            basis = clean["consent_basis"]
            if basis != "none" and not (clean.get("consent_evidence") and clean.get("consent_date")):
                raise RevenueError(f"consent basis '{basis}' needs consent_evidence and consent_date")
            markers = self.office.policy.injection_markers
            structured = " ".join(str(v) for k, v in clean.items() if k != "stated_need" and isinstance(v, str))
            hits = rules.instruction_markers(structured, markers)
            if hits:
                raise RevenueError(
                    f"instruction-like text in the lead's fields ({', '.join(hits)});"
                    " remove it and record the lead again"
                )
            email = clean["contact_email"]
            rehearsal = bool(clean.get("rehearsal", False))
            s = self.settings() or {}
            if rehearsal and not (rules.is_reserved_test_address(email) or email in s.get("rehearsal_recipients", [])):
                raise RevenueError(
                    "a rehearsal lead must use a reserved test address (example.com, .test) or one listed in"
                    " rehearsal_recipients"
                )
            for o in self.opportunities():
                if o.source == clean["source"] and o.source_ref == clean["source_ref"]:
                    raise RevenueConflict(f"this lead is already recorded as {o.id}")
                if o.contact["email"] == email and o.stage in rules.OPEN_STAGES:
                    raise RevenueConflict(f"{email} already has an open opportunity, {o.id}")
            need = clean.get("stated_need", "")
            need_hits = rules.instruction_markers(need, markers)
            flags = []
            if need_hits:
                flags.append(
                    f"The stated need holds instruction-like text ({', '.join(need_hits)}). It is kept as data,"
                    " ignored for qualification, and never used in a message."
                )
            if self.suppressed(email):
                flags.append("The contact is on the suppression list: no message can be sent.")
            opp_id = self.office.ids("opp")
            params = {
                "opportunity_id": opp_id,
                "source": clean["source"],
                "source_ref": clean["source_ref"],
                "consent_basis": basis,
                "consent_date": clean.get("consent_date"),
                "consent_evidence": clean.get("consent_evidence"),
                "contact_name": clean["contact_name"],
                "contact_email": email,
                "contact_role": clean.get("contact_role"),
                "organization": clean["organization"],
                "region": clean.get("region"),
                "city": clean.get("city"),
                "sector": clean.get("sector"),
                "employees": clean.get("employees"),
                "stated_need_present": bool(need) and not need_hits,
                "stated_need_digest": digest(need) if need else None,
                "rehearsal": rehearsal,
            }
            result = self._perform(
                "revenue.opportunity",
                "crm.record_lead",
                params,
                opp_id=opp_id,
                key=f"rev:intake:{digest([clean['source'], clean['source_ref']])[:24]}",
            )
            self._completed(result, "recording the lead")
            now = self._iso()
            opp = Opportunity(
                id=opp_id,
                stage="new",
                rehearsal=rehearsal,
                source=clean["source"],
                source_ref=clean["source_ref"],
                contact={
                    "name": clean["contact_name"],
                    "email": email,
                    "role": clean.get("contact_role"),
                    "organization": clean["organization"],
                },
                consent={
                    "basis": basis,
                    "evidence": clean.get("consent_evidence"),
                    "date": clean.get("consent_date"),
                    "recorded_by": principal.id,
                    "recorded_at": now,
                },
                lead_facts={
                    "region": clean.get("region"),
                    "city": clean.get("city"),
                    "sector": clean.get("sector"),
                    "employees": clean.get("employees"),
                    "stated_need": need or None,
                    "stated_need_present": params["stated_need_present"],
                    "stated_need_quarantined": bool(need_hits),
                },
                flags=flags,
                created_by=principal.id,
                created_at=now,
                updated_at=now,
            )
            self._event(
                opp,
                "lead_recorded",
                f"Recorded from {clean['source']} by the Opportunity Agent",
                by="revenue.opportunity",
                ref=clean["source_ref"],
            )
            self._save(opp)
            return opp

    FACT_FIELDS = ("contact_role", "region", "city", "sector", "employees", "stated_need")

    def update_facts(self, principal: Principal, opp_id: str, raw: dict[str, Any]) -> Opportunity:
        with self.lock:
            self._human(principal)
            self._running()
            opp = self.get(opp_id)
            if opp.stage not in ("new", "qualified", "disqualified"):
                raise RevenueConflict(f"facts can change only before first contact; the opportunity is {opp.stage}")
            schema = {
                k: v
                for k, v in rules.lead_schema(self.cfg.lead_sources, self.cfg.consent_bases).items()
                if k in self.FACT_FIELDS
            }
            try:
                clean = rules.validate_fields(
                    raw, {k: rules.Field(v.kind, False, v.lo, v.hi, v.choices) for k, v in schema.items()}, "facts"
                )
            except rules.RuleError as exc:
                raise RevenueError(str(exc)) from exc
            if not clean:
                raise RevenueError("no facts given")
            markers = self.office.policy.injection_markers
            structured = " ".join(str(v) for k, v in clean.items() if k != "stated_need")
            if rules.instruction_markers(structured, markers) or rules.credential_rules(clean):
                raise RevenueError("instruction-like or credential-shaped text in the facts")
            if "contact_role" in clean:
                opp.contact["role"] = clean.pop("contact_role")
            if "stated_need" in clean:
                need = clean.pop("stated_need")
                hits = rules.instruction_markers(need, markers)
                opp.lead_facts.update(
                    {"stated_need": need, "stated_need_present": not hits, "stated_need_quarantined": bool(hits)}
                )
            opp.lead_facts.update(clean)
            self._cancel_open(opp, principal.id, "the opportunity's facts changed")
            if opp.stage in ("qualified", "disqualified"):
                opp.stage = "new"
            self._event(opp, "facts_updated", "Facts updated; qualification runs again", by=principal.id)
            self._save(opp, material=True)
            return opp

    def add_research(self, principal: Principal, opp_id: str, facts: list[dict[str, Any]]) -> Opportunity:
        with self.lock:
            self._human(principal)
            self._running()
            opp = self.get(opp_id)
            if not isinstance(facts, list) or not 1 <= len(facts) <= 20:
                raise RevenueError("facts must be a list of 1 to 20 items")
            markers = self.office.policy.injection_markers
            clean, quarantined = [], []
            for i, f in enumerate(facts):
                try:
                    item = rules.validate_fields(
                        f,
                        {"text": rules.Field("text", True, 3, 500), "source": rules.Field("str", False, 3, 300)},
                        f"facts[{i}]",
                    )
                except rules.RuleError as exc:
                    raise RevenueError(str(exc)) from exc
                if rules.credential_rules(item):
                    raise RevenueError(f"facts[{i}] holds credential-shaped text")
                hits = rules.instruction_markers(item["text"], markers)
                if hits:
                    quarantined.append({**item, "markers": hits, "action": "kept out of the brief"})
                else:
                    clean.append({"text": item["text"], "source": item.get("source")})
            artifact: dict[str, Any] = {"items": []}
            if clean:
                result = self._perform(
                    "revenue.lead-research",
                    "research.collect",
                    {"sources": clean},
                    opp_id=opp.id,
                    key=f"rev:research:{opp.id}:{digest(clean)[:16]}",
                )
                artifact = self._completed(result, "the research brief")["artifact"]
            opp.research = {
                "items": [*opp.research.get("items", []), *artifact.get("items", [])],
                "quarantined": [*opp.research.get("quarantined", []), *quarantined],
                "collected_by": "revenue.lead-research",
                "updated_at": self._iso(),
                "method": "Facts supplied with their sources; the agent does not browse. Items without a source are"
                " marked unverified.",
            }
            self._event(
                opp,
                "research_added",
                f"{len(clean)} sourced fact(s) added, {len(quarantined)} quarantined",
                by="revenue.lead-research",
            )
            self._save(opp)
            return opp

    # -- the Director's plan ----------------------------------------------------------------------------

    def _draft_inputs(self, opp: Opportunity, kind: str) -> dict[str, Any]:
        inputs = {
            "record_version": opp.content_version,
            "offer_digest": opp.offer_digest,
            "settings_digest": self.settings_digest(),
        }
        if kind == "proposal":
            inputs["proposal_digest"] = (opp.drafts.get("proposal_document") or {}).get("digest")
        return inputs

    def _draft_valid(self, opp: Opportunity, kind: str) -> bool:
        draft = opp.drafts.get(kind)
        return bool(draft) and draft.get("inputs") == self._draft_inputs(opp, kind)

    def _proposal_doc_valid(self, opp: Opportunity) -> bool:
        doc = opp.drafts.get("proposal_document")
        return bool(doc) and doc.get("inputs") == {
            "record_version": opp.content_version,
            "offer_digest": opp.offer_digest,
        }

    def _offer_current(self, opp: Opportunity) -> dict[str, Any] | None:
        if not opp.offer_sku:
            return None
        offer = self.offer_state(opp.offer_sku)
        return offer if offer["status"] == "approved" and offer["approved_digest"] == opp.offer_digest else None

    def _consent(self, opp: Opportunity) -> dict[str, Any]:
        return {
            "basis": opp.consent.get("basis"),
            "evidence": opp.consent.get("evidence"),
            "date": opp.consent.get("date"),
        }

    def _last_customer_event(self, opp: Opportunity) -> datetime | None:
        times = [rules.parse_datetime(e["at"]) for e in opp.timeline if e["kind"] in CUSTOMER_EVENTS]
        times = [t for t in times if t]
        return max(times) if times else None

    def _frequency_problem(self, opp: Opportunity, acts: list[ExternalAction]) -> str:
        now = self._now()
        times = []
        for a in acts:
            if a.kind in ("outreach_email", "proposal_email") and a.status in (
                "released",
                "executed",
                "verified",
                "verification_failed",
            ):
                when = (a.receipt or {}).get("executed_at") or (a.ticket or {}).get("released_at")
                t = rules.parse_datetime(when)
                if t:
                    times.append(t)
        cap = self.cfg.contact_rules["max_messages_per_contact_per_30_days"]
        recent = [t for t in times if now - t <= timedelta(days=30)]
        if len(recent) >= cap:
            return f"contact cap reached: {len(recent)} messages to this contact in 30 days (limit {cap})"
        gap = self.cfg.contact_rules["min_hours_between_messages"]
        if times:
            last = max(times)
            replied = self._last_customer_event(opp)
            hours = (now - last).total_seconds() / 3600
            if hours < gap and not (replied and replied >= last):
                return (
                    f"the last message went out {hours:.0f} hours ago; the minimum gap is {gap} hours"
                    " unless the client replies"
                )
        return ""

    def _send_problems(self, opp: Opportunity, kind: str, acts: list[ExternalAction]) -> list[str]:
        problems = []
        if self.settings() is None:
            problems.append("the sender identity is not set (CASL s.6(2))")
        if self._offer_current(opp) is None:
            problems.append("the matched offer is not approved with its current content")
        need = {"outreach_email": ("qualified",), "proposal_email": ("contacted", "engaged"), "invoice": ("accepted",)}
        if opp.stage not in need[kind]:
            problems.append(f"a {ACTION_KINDS[kind][2]} cannot go out while the opportunity is {opp.stage}")
        if kind == "proposal_email" and opp.stage == "contacted" and not opp.consent.get("quote_requested_at"):
            problems.append("a proposal goes out after the client replies, books a meeting, or asks for a quote")
        if self.suppressed(opp.contact["email"]):
            problems.append(f"{opp.contact['email']} is on the suppression list")
        consent = rules.consent_problem(
            self._consent(opp),
            kind,
            bases=self.cfg.consent_bases,
            today=self._now().date(),
            quote_requested=bool(opp.consent.get("quote_requested_at")),
            terms_accepted=bool(opp.terms.get("accepted_at")),
        )
        if consent:
            problems.append(consent)
        if kind != "invoice":
            freq = self._frequency_problem(opp, acts)
            if freq:
                problems.append(freq)
        if opp.rehearsal:
            s = self.settings() or {}
            email = opp.contact["email"]
            if not (rules.is_reserved_test_address(email) or email in s.get("rehearsal_recipients", [])):
                problems.append("a rehearsal may only reach a reserved test address or a listed rehearsal recipient")
        return problems

    def plan(self, opp: Opportunity, acts: list[ExternalAction] | None = None) -> dict[str, Any]:
        """The next step for ``opp``: who does it, or what the opportunity is waiting for."""
        acts = self.actions(opp.id) if acts is None else acts

        def do(role: str, step: str, label: str) -> dict[str, Any]:
            return {"kind": "do", "role": role, "step": step, "label": label, "state": "queued"}

        def wait(role: str | None, label: str, state: str, operator_step: str = "") -> dict[str, Any]:
            return {
                "kind": "wait",
                "role": role,
                "step": None,
                "label": label,
                "state": state,
                "operator_step": operator_step,
            }

        def blocked(role: str, label: str, detail: str) -> dict[str, Any]:
            return {"kind": "blocked", "role": role, "step": None, "label": label, "state": "blocked", "detail": detail}

        st = opp.stage
        if st == "lost":
            return {
                "kind": "done",
                "role": None,
                "step": None,
                "label": f"Closed as lost: {opp.lost_reason}",
                "state": "completed",
            }
        if st == "in_fulfillment":
            return {"kind": "done", "role": None, "step": None, "label": "Handed to delivery", "state": "completed"}
        for kind, (_, role, label) in ACTION_KINDS.items():
            a = next((x for x in acts if x.kind == kind and x.status in OPEN_ACTION_STATUSES), None)
            if a is None:
                continue
            if a.status == "awaiting_approval":
                return wait(
                    role,
                    f"The {label} is waiting for approval {a.approval_id}",
                    "awaiting_approval",
                    "Decide it in the Approval Desk.",
                )
            if a.status == "approved":
                return wait(
                    role,
                    f"The {label} is approved and waiting to be released",
                    "awaiting_approval",
                    f"Release ticket {a.id}.",
                )
            return wait(
                role,
                f"The {label} ticket is released and not yet recorded as sent",
                "awaiting_approval",
                f"Execute ticket {a.id} and record its receipt, or reconcile and abandon it.",
            )
        if st == "disqualified":
            return wait(
                "qualification",
                f"Disqualified: {opp.qualification.get('why', '')}",
                "idle",
                "Update the facts to re-qualify, or close it.",
            )
        if st == "new":
            q = opp.qualification
            if (
                q
                and q.get("record_version") == opp.content_version
                and q.get("outcome") in ("needs_evidence", "below_threshold")
            ):
                return blocked("qualification", "Not qualified yet", q.get("why", ""))
            return do("qualification", "qualify", "Score the lead against the criteria")
        if st in ("qualified", "contacted", "engaged") and self._offer_current(opp) is None:
            approved = self.approved_offers()
            if not approved:
                return blocked("director", "No approved offer to match", "The owner has not approved an offer.")
            return do("director", "match_offer", "Match the approved offer")
        sending = {
            "qualified": "outreach_email",
            "contacted": "proposal_email",
            "engaged": "proposal_email",
            "accepted": "invoice",
        }
        kind = sending.get(st)
        if st == "contacted" and not opp.consent.get("quote_requested_at"):
            return wait(
                "outreach",
                "Waiting for the client to reply or book a meeting",
                "waiting_for_customer",
                "Record their reply, booking or quote request.",
            )
        if kind:
            role = ACTION_KINDS[kind][1]
            problems = self._send_problems(opp, kind, acts)
            if problems:
                return blocked(role, f"The {ACTION_KINDS[kind][2]} cannot be requested", "; ".join(problems))
            if kind == "outreach_email" and not self._draft_valid(opp, "outreach"):
                return do("outreach", "compose_outreach", "Draft the first email")
            if kind == "proposal_email":
                if not self._proposal_doc_valid(opp):
                    return do("proposal", "draft_proposal", "Write the proposal from the approved offer")
                if not self._draft_valid(opp, "proposal"):
                    return do("outreach", "compose_proposal", "Draft the proposal email")
            return do(role, f"request_{kind}", f"Request approval for the {ACTION_KINDS[kind][2]}")
        if st == "proposal_sent":
            return wait(
                "outreach",
                "Waiting for the client's decision on the proposal",
                "waiting_for_customer",
                "Record the acceptance with its evidence when it arrives.",
            )
        if st == "invoiced":
            inv = self._invoice_action(acts)
            if inv is not None and inv.status == "executed":
                return wait(
                    "delivery",
                    "Invoice sent; check it against PayPal",
                    "waiting_for_payment",
                    f"Verify ticket {inv.id} with the PayPal invoice record.",
                )
            return wait(
                "delivery", "Waiting for payment", "waiting_for_payment", "Import the PayPal record when it is paid."
            )
        if st == "paid":
            return blocked(
                "delivery",
                "Paid: waiting for the client's written authorization",
                "The handoff needs the reference of the client's written authorization.",
            )
        return wait(None, f"No step defined for stage {st}", "idle")

    @staticmethod
    def _invoice_action(acts: list[ExternalAction]) -> ExternalAction | None:
        done = [a for a in acts if a.kind == "invoice" and a.status in ("executed", "verified", "verification_failed")]
        return done[-1] if done else None

    def advance(self, principal: Principal, opp_id: str, offer_sku: str | None = None) -> dict[str, Any]:
        """Run exactly one internal step for one opportunity, then stop."""
        with self.lock:
            self._human(principal)
            self._running()
            opp = self.get(opp_id)
            plan = self.plan(opp)
            if plan["kind"] != "do":
                return {"opportunity_id": opp.id, "ran": None, "stage": opp.stage, "plan": plan}
            self.office.log(
                principal.id, "human", "revenue.step_requested", opp.id, {"step": plan["step"], "role": plan["role"]}
            )
            handler = {
                "qualify": self._step_qualify,
                "match_offer": self._step_match_offer,
                "compose_outreach": lambda o, s: self._step_compose(o, "outreach"),
                "draft_proposal": self._step_draft_proposal,
                "compose_proposal": lambda o, s: self._step_compose(o, "proposal"),
                "request_outreach_email": lambda o, s: self._request(o, "outreach_email"),
                "request_proposal_email": lambda o, s: self._request(o, "proposal_email"),
                "request_invoice": lambda o, s: self._request(o, "invoice"),
            }[plan["step"]]
            result = handler(opp, offer_sku)
            opp = self.get(opp_id)
            return {
                "opportunity_id": opp.id,
                "ran": plan["step"],
                "result": result,
                "stage": opp.stage,
                "plan": self.plan(opp),
            }

    def cycle(self, principal: Principal) -> dict[str, Any]:
        """The Director's bounded loop: at most one step for each of at most N open opportunities."""
        with self.lock:
            self._human(principal)
            self._running()
            candidates = sorted(
                (o for o in self.opportunities() if o.stage in rules.OPEN_STAGES),
                key=lambda o: (o.priority, o.created_at),
            )
            limit = self.cfg.max_per_cycle
            ran, waiting, errors = [], [], []
            for opp in candidates[:limit]:
                try:
                    r = self.advance(principal, opp.id)
                except (RevenueError, ApprovalError, rules.RuleError) as exc:
                    errors.append({"opportunity_id": opp.id, "error": str(exc)})
                    continue
                (ran if r["ran"] else waiting).append(
                    {"opportunity_id": opp.id, "step": r["ran"], "plan": r["plan"]["label"]}
                )
            self.office.log(
                principal.id,
                "human",
                "revenue.cycle",
                "revenue",
                {"ran": len(ran), "waiting": len(waiting), "errors": len(errors)},
            )
            return {
                "limit": limit,
                "considered": min(limit, len(candidates)),
                "deferred": max(0, len(candidates) - limit),
                "ran": ran,
                "waiting": waiting,
                "errors": errors,
            }

    # -- internal steps ------------------------------------------------------------------------------------

    def _step_qualify(self, opp: Opportunity, _offer: str | None) -> dict[str, Any]:
        facts = {
            "contact_email": opp.contact["email"],
            "organization": opp.contact["organization"],
            "contact_role": opp.contact.get("role"),
            "region": opp.lead_facts.get("region"),
            "sector": opp.lead_facts.get("sector"),
            "employees": opp.lead_facts.get("employees"),
            "stated_need_present": bool(opp.lead_facts.get("stated_need_present")),
            "source_ref": opp.source_ref,
        }
        params = {
            "opportunity_id": opp.id,
            "record_version": opp.content_version,
            "facts": facts,
            "criteria": self.cfg.criteria,
            "threshold": self.cfg.threshold,
        }
        result = self._perform(
            "revenue.qualification",
            "leads.qualify",
            params,
            opp_id=opp.id,
            key=f"rev:qualify:{opp.id}:{opp.content_version}",
        )
        art = self._completed(result, "qualification")["artifact"]
        opp.qualification = {**art, "assessed_at": self._iso(), "agent": "revenue.qualification"}
        if art["outcome"] in ("qualified", "disqualified"):
            opp.stage = rules.next_stage(opp.stage, art["outcome"])
            kind = art["outcome"]
        else:
            kind = "qualification_incomplete"
        self._event(
            opp, kind, f"{art['outcome'].replace('_', ' ').capitalize()}: {art['why']}", by="revenue.qualification"
        )
        self._save(opp)
        return {"outcome": art["outcome"], "score": art["score"], "missing_evidence": art["missing_evidence"]}

    def _step_match_offer(self, opp: Opportunity, offer_sku: str | None) -> dict[str, Any]:
        approved = self.approved_offers()
        if offer_sku:
            chosen = next((o for o in approved if o["sku"] == offer_sku), None)
            if chosen is None:
                raise RevenueConflict(f"offer {offer_sku!r} is not approved")
        elif len(approved) == 1:
            chosen = approved[0]
        else:
            raise RevenueConflict("more than one offer is approved: name the one to match")
        params = {
            "opportunity_id": opp.id,
            "change": "match_offer",
            "offer_sku": chosen["sku"],
            "offer_digest": chosen["approved_digest"],
            "record_version": opp.content_version,
        }
        result = self._perform(
            "revenue.director",
            "crm.update_opportunity",
            params,
            opp_id=opp.id,
            key=f"rev:match:{opp.id}:{opp.content_version}:{chosen['approved_digest'][:12]}",
        )
        self._completed(result, "matching the offer")
        opp.offer_sku, opp.offer_digest = chosen["sku"], chosen["approved_digest"]
        self._event(opp, "offer_matched", f"Matched to the approved {chosen['name']}", by="revenue.director")
        self._save(opp, material=True)
        return {"offer_sku": chosen["sku"]}

    def _opp_view(self, opp: Opportunity) -> dict[str, Any]:
        return {"id": opp.id, "contact": opp.contact, "consent": opp.consent, "source": opp.source}

    def compose_draft(self, params: dict[str, Any]) -> dict[str, Any]:
        """Called by the Outreach Agent's ``outreach.compose`` skill.

        Raises on stale inputs or a failed content check.
        """
        opp = self.get(str(params.get("opportunity_id")))
        kind = params.get("kind")
        if kind not in ("outreach", "proposal"):
            raise ValueError("kind must be outreach or proposal")
        if params.get("channel") != "email":
            raise ValueError("the only channel is email")
        current = self._draft_inputs(opp, kind)
        given = {k: params.get(k) for k in current}
        if given != current:
            raise ValueError("stale: the opportunity, offer, settings or proposal changed; draft again")
        offer = self._offer_current(opp)
        settings = self.settings()
        if offer is None or settings is None:
            raise ValueError("an approved offer and the Revenue settings are required")
        view = self._opp_view(opp)
        if kind == "outreach":
            msg = compose.outreach_email(view, offer["content"], settings)
        else:
            sections = opp.drafts["proposal_document"]["sections"]
            msg = compose.proposal_email(view, offer["content"], settings, sections)
        problems = rules.content_problems(
            msg["subject"],
            msg["body"],
            allowed_figures=compose.allowed_figures(view, offer["content"], settings),
            allowed_urls=compose.allowed_urls(settings, offer["content"]),
            prohibited=self.cfg.prohibited_phrases,
            required_text=compose.required_text(settings),
        )
        if problems:
            raise ValueError("content check failed: " + "; ".join(problems))
        return {
            "kind": kind,
            "to": [opp.contact["email"]],
            "subject": msg["subject"],
            "body": msg["body"],
            "content_check": "passed",
            "template": f"revenue_ops.compose.{kind}_email",
        }

    def _step_compose(self, opp: Opportunity, kind: str) -> dict[str, Any]:
        params = {"opportunity_id": opp.id, "kind": kind, "channel": "email", **self._draft_inputs(opp, kind)}
        result = self._perform(
            "revenue.sales-strategist",
            "outreach.compose",
            params,
            opp_id=opp.id,
            key=f"rev:compose:{opp.id}:{digest(params)[:20]}",
        )
        art = self._completed(result, f"drafting the {kind} email")["artifact"]
        opp.drafts[kind] = {
            "subject": art["subject"],
            "body": art["body"],
            "to": art["to"],
            "content_check": art["content_check"],
            "inputs": self._draft_inputs(opp, kind),
            "composed_at": self._iso(),
            "agent": "revenue.sales-strategist",
        }
        self._event(
            opp,
            "draft_ready",
            f"The {kind} email is drafted and passed the content check",
            by="revenue.sales-strategist",
        )
        self._save(opp)
        return {"draft": kind}

    def _step_draft_proposal(self, opp: Opportunity, _offer: str | None) -> dict[str, Any]:
        offer = self._offer_current(opp)
        if offer is None:
            raise RevenueConflict("the matched offer is not approved with its current content")
        sections = compose.proposal_sections(self._opp_view(opp), offer["content"])
        result = self._perform(
            "revenue.proposal-writer",
            "proposal.draft",
            sections,
            opp_id=opp.id,
            key=f"rev:proposal:{opp.id}:{digest(sections)[:20]}",
        )
        art = self._completed(result, "writing the proposal")["artifact"]
        opp.drafts["proposal_document"] = {
            "sections": sections,
            "document": art.get("body"),
            "provenance": art.get("provenance"),
            "digest": digest(sections),
            "inputs": {"record_version": opp.content_version, "offer_digest": opp.offer_digest},
            "drafted_at": self._iso(),
            "agent": "revenue.proposal-writer",
        }
        self._event(
            opp, "proposal_drafted", "The proposal is written from the approved offer", by="revenue.proposal-writer"
        )
        self._save(opp)
        return {"draft": "proposal_document"}

    def _request(self, opp: Opportunity, kind: str) -> dict[str, Any]:
        action_type, role, label = ACTION_KINDS[kind]
        agent_id = ROLE_AGENT[role]
        acts = self.actions(opp.id)
        if any(a.kind == kind and a.status in OPEN_ACTION_STATUSES for a in acts):
            raise RevenueConflict(f"a {label} for this opportunity is already in progress")
        problems = self._send_problems(opp, kind, acts)
        if problems:
            raise RevenueConflict("; ".join(problems))
        s = self.settings() or {}
        offer = self._offer_current(opp)
        assert offer is not None  # _send_problems checked it
        base = {
            "opportunity_id": opp.id,
            "purpose": kind,
            "record_version": opp.content_version,
            "offer_sku": opp.offer_sku,
            "offer_digest": opp.offer_digest,
            "settings_digest": self.settings_digest(),
            "rehearsal": opp.rehearsal,
        }
        if kind in ("outreach_email", "proposal_email"):
            draft = opp.drafts["outreach" if kind == "outreach_email" else "proposal"]
            params = {
                **base,
                "channel": "email",
                "connector": s["email_connector"],
                "recipients": [opp.contact["email"]],
                "subject": draft["subject"],
                "body": draft["body"],
                "consent_basis": opp.consent["basis"],
            }
            if kind == "proposal_email":
                params["quoted_total_cents"] = offer["total_cents"]
                params["currency"] = offer["currency"]
        else:
            total = offer["total_cents"]
            fields = compose.invoice_fields(self._opp_view(opp), offer["content"], s, self._now().date())
            evidence = opp.terms["evidence_ref"]
            params = {
                **base,
                "provider": "paypal",
                "currency": offer["currency"],
                "recipient_email": opp.contact["email"],
                "invoice_amount_cents": total,
                "price_cents": offer["price_cents"],
                "tax_basis_points": offer["decision"]["tax_basis_points"],
                "due_date": fields["due_date"],
                "paypal_fields": fields,
                "terms_evidence": evidence,
                "change_plan": f"Create and send one PayPal invoice for {rules.money_text(total, offer['currency'])} to"
                f" {opp.contact['email']} for the proposal accepted under {evidence} (reference {opp.id}).",
                "rollback_plan": "If the invoice is wrong or sent in error, cancel it in PayPal before it is paid and"
                " record the cancellation here. If it was already paid, refund only after a separate"
                " operator decision.",
                "verification_plan": "Run PayPal list_invoices (status SENT); confirm the invoice id, total,"
                " currency and"
                " recipient match this ticket; record them with the verify step.",
            }
        for a in acts:
            if a.kind == kind and a.status == "rejected" and a.payload == params:
                raise RevenueConflict(
                    "the operator rejected this exact payload: change the record or close the opportunity"
                )
        result = self._perform(agent_id, action_type, params, opp_id=opp.id)
        if result.status == "denied":
            raise RevenueConflict("policy refused the request: " + (result.error or ""))
        if result.status != "waiting_approval" or result.approval is None:
            raise RevenueConflict(f"expected an approval request, got {result.status}: {result.error}")
        approval = result.approval
        now = self._iso()
        action = ExternalAction(
            id=self.office.ids("ext"),
            opportunity_id=opp.id,
            kind=kind,
            action_type=action_type,
            agent_id=agent_id,
            connector=params.get("connector") or "paypal",
            payload=params,
            payload_digest=approval.action_digest,
            record_version=opp.content_version,
            approval_id=approval.id,
            rehearsal=opp.rehearsal,
            created_at=now,
            updated_at=now,
        )
        self.office.store.put(action, now)
        self._event(
            opp,
            "approval_requested",
            f"The {label} is waiting for approval {approval.id}",
            by=agent_id,
            ref=approval.id,
        )
        self._save(opp)
        self.office.post_message(
            sender=agent_id,
            recipient="operator",
            kind="escalation",
            subject=f"Approval needed: {label} for {opp.contact['organization']}",
            body=f"Approval {approval.id} ({approval.risk_tier}). The exact payload is in the Approval Desk;"
            f" after approving, release ticket {action.id} from the Revenue Floor.",
            thread_id="revenue",
            refs=[approval.id, action.id],
        )
        return {"action_id": action.id, "approval_id": approval.id, "tier": approval.risk_tier}

    # -- release, receipt, verification ------------------------------------------------------------------

    def _release_problems(
        self, opp: Opportunity, action: ExternalAction, params: dict[str, Any]
    ) -> tuple[list[str], list[str]]:
        binding, other = [], []
        if params.get("record_version") != opp.content_version:
            binding.append(
                f"the opportunity changed after approval"
                f" (version {params.get('record_version')} -> {opp.content_version})"
            )
        offer = self.offer_state(str(params.get("offer_sku")))
        if offer["status"] != "approved" or offer["approved_digest"] != params.get("offer_digest"):
            binding.append("the offer changed or is no longer approved")
        if params.get("settings_digest") != self.settings_digest():
            binding.append("the Revenue settings changed after approval")
        acts = [a for a in self.actions(opp.id) if a.id != action.id]
        other += self._send_problems(opp, action.kind, acts)
        email = opp.contact["email"]
        if action.kind in ("outreach_email", "proposal_email"):
            if params.get("recipients") != [email]:
                other.append("the recipients must be exactly the opportunity's contact")
            s = self.settings()
            if offer["decision"] and s:
                view = self._opp_view(opp)
                other += rules.content_problems(
                    str(params.get("subject", "")),
                    str(params.get("body", "")),
                    allowed_figures=compose.allowed_figures(view, offer["content"], s),
                    allowed_urls=compose.allowed_urls(s, offer["content"]),
                    prohibited=self.cfg.prohibited_phrases,
                    required_text=compose.required_text(s),
                )
        else:
            fields = params.get("paypal_fields") or {}
            if params.get("recipient_email") != email or fields.get("recipient_email") != email:
                other.append("the invoice must go to the opportunity's contact")
            if (
                offer["total_cents"] != params.get("invoice_amount_cents")
                or fields.get("amount_value") != offer["price_cents"] / 100
            ):
                other.append("the invoice amount differs from the approved offer")
        return binding, other

    def release(self, principal: Principal, action_id: str) -> ExternalAction:
        """Re-check everything, consume the approval once, and hand back the exact ticket to execute."""
        with self.lock:
            self._human(principal)
            self._running()
            action = self.action(action_id)
            if action.status != "approved":
                raise RevenueConflict(f"only an approved action can be released; this one is {action.status}")
            approval = self.office.desk.get(str(action.approval_id))
            if approval is None or not approval.approved_action:
                raise RevenueConflict("the approval record is missing")
            params = dict(approval.approved_action["params"])
            opp = self.get(action.opportunity_id)
            binding, other = self._release_problems(opp, action, params)
            if binding or other:
                action.error = "; ".join(binding + other)
                self._cancel_open(opp, principal.id, f"not released: {action.error}")
                action = self.office.store.get(ExternalAction, action.id) or action
                action.status = "stale" if binding else "blocked"
                action.error = "; ".join(binding + other)
                self._save_action(action)
                self._event(opp, "release_refused", action.error, by=principal.id, ref=action.id)
                self._save(opp)
                raise RevenueConflict(f"not released: {action.error}")
            result = self._perform(
                action.agent_id,
                action.action_type,
                params,
                opp_id=opp.id,
                approval_id=approval.id,
                key=f"rev:release:{action.id}",
            )
            if result.status != "completed":
                action.error = result.error
                self._save_action(action)
                raise RevenueConflict(f"not released: {result.error}")
            receipt = (result.output or {}).get("receipt") or {}
            now = self._iso()
            action.payload = params
            action.payload_digest = str(approval.approved_digest)
            action.ticket = compose.ticket(
                action.kind,
                params,
                approval_id=approval.id,
                payload_digest=action.payload_digest,
                office_receipt=receipt.get("receipt_id"),
                released_by=principal.id,
                released_at=now,
            )
            action.status = "released"
            action.error = None
            self._save_action(action)
            self._event(
                opp, "released", f"Ticket {action.id} released for a person to execute", by=principal.id, ref=action.id
            )
            self._save(opp)
            return action

    def record_receipt(
        self, principal: Principal, action_id: str, external_ref: str, executed_at: str, payload_digest: str
    ) -> ExternalAction:
        """Record that a person executed a released ticket exactly as approved, with the provider's reference."""
        with self.lock:
            self._human(principal)
            action = self.action(action_id)
            if action.status != "released":
                raise RevenueConflict(f"only a released ticket takes a receipt; this one is {action.status}")
            if payload_digest != action.payload_digest:
                raise RevenueError(
                    "payload_digest does not match the released ticket:"
                    " record a receipt only for exactly what was approved"
                )
            ref = self._text(external_ref, "external_ref", 4, 200)
            when = self._when(executed_at, "executed_at")
            released = rules.parse_datetime((action.ticket or {}).get("released_at"))
            if released and when < released - timedelta(minutes=5):
                raise RevenueError("executed_at is before the ticket was released")
            opp = self.get(action.opportunity_id)
            event = {"outreach_email": "outreach_sent", "proposal_email": "proposal_sent", "invoice": "invoice_sent"}[
                action.kind
            ]
            try:
                new_stage = rules.next_stage(opp.stage, event)
            except rules.RuleError:
                if opp.stage != "lost":
                    raise RevenueConflict(f"the opportunity is {opp.stage}; this receipt does not fit it") from None
                new_stage = opp.stage
                opp.flags.append(
                    f"{ACTION_KINDS[action.kind][2].capitalize()} {ref} was executed after the opportunity was closed."
                )
            try:
                self.office.store.record_receipt(
                    connector=action.connector, external_ref=ref, action_id=action.id, recorded_at=self._iso()
                )
            except sqlite3.IntegrityError:
                owner = self.office.store.receipt_owner(action.connector, ref)
                raise RevenueConflict(f"reference {ref} is already recorded for {owner}") from None
            action.receipt = {
                "external_ref": ref,
                "executed_at": when.isoformat(timespec="seconds"),
                "connector": action.connector,
                "recorded_by": principal.id,
                "recorded_at": self._iso(),
            }
            action.status = "executed"
            self._save_action(action)
            opp.stage = new_stage
            label = ACTION_KINDS[action.kind][2]
            self._event(
                opp,
                event,
                f"The {label} was sent ({action.connector} {ref})",
                by=principal.id,
                ref=ref,
                at=action.receipt["executed_at"],
            )
            if action.kind == "proposal_email":
                self._money(
                    opp,
                    kind="proposal_issued",
                    amount=int(action.payload["quoted_total_cents"]),
                    currency=str(action.payload["currency"]),
                    provider=action.connector,
                    record_type="message",
                    external_ref=ref,
                    status="sent",
                    verification="operator_receipt",
                    evidence=f"approval {action.approval_id}, ticket {action.id}",
                    raw_digest=None,
                    occurred_at=action.receipt["executed_at"],
                    by=principal.id,
                )
            self._save(opp)
            return action

    def verify(self, principal: Principal, action_id: str, record: dict[str, Any]) -> ExternalAction:
        """Compare an executed action with the provider's own record of it."""
        with self.lock:
            self._human(principal)
            action = self.action(action_id)
            if action.status not in ("executed", "verification_failed"):
                raise RevenueConflict(f"only an executed action can be verified; this one is {action.status}")
            p = action.payload
            ref = (action.receipt or {}).get("external_ref")
            mismatches: list[str] = []
            try:
                if action.kind == "invoice":
                    clean = rules.validate_fields(record, rules.INVOICE_RECEIPT_SCHEMA, "invoice record")
                    tolerance = 1 if p.get("tax_basis_points") else 0
                    if clean["invoice_id"] != ref:
                        mismatches.append("invoice_id differs from the recorded receipt")
                    if clean["currency"] != p["currency"]:
                        mismatches.append(f"currency {clean['currency']} differs from {p['currency']}")
                    if clean["recipient_email"] != p["recipient_email"]:
                        mismatches.append("recipient differs from the approved invoice")
                    if abs(clean["total_cents"] - int(p["invoice_amount_cents"])) > tolerance:
                        mismatches.append(
                            f"total {clean['total_cents']} differs from the approved {p['invoice_amount_cents']}"
                        )
                else:
                    clean = rules.validate_fields(record, rules.EMAIL_RECEIPT_SCHEMA, "message record")
                    if clean["message_id"] != ref:
                        mismatches.append("message_id differs from the recorded receipt")
                    if sorted(clean["to"]) != sorted(p["recipients"]):
                        mismatches.append("recipients differ from the approved message")
                    if clean["subject"] != p["subject"]:
                        mismatches.append("subject differs from the approved message")
            except rules.RuleError as exc:
                raise RevenueError(str(exc)) from exc
            opp = self.get(action.opportunity_id)
            action.verification = {
                "method": "provider_record",
                "record": clean,
                "record_digest": digest(record),
                "mismatches": mismatches,
                "checked_by": principal.id,
                "checked_at": self._iso(),
            }
            if mismatches:
                action.status = "verification_failed"
                self._save_action(action)
                self._event(opp, "verification_failed", "; ".join(mismatches), by=principal.id, ref=ref)
                self._save(opp)
                self.office.post_message(
                    sender="system.office",
                    recipient="operator",
                    kind="escalation",
                    subject=f"Verification failed: {ACTION_KINDS[action.kind][2]} {ref}",
                    body="; ".join(mismatches),
                    thread_id="revenue",
                    refs=[action.id],
                )
                raise RevenueConflict("verification failed: " + "; ".join(mismatches))
            action.status = "verified"
            self._save_action(action)
            if action.kind == "invoice":
                self._money(
                    opp,
                    kind="invoice_issued",
                    amount=clean["total_cents"],
                    currency=clean["currency"],
                    provider="paypal",
                    record_type="invoice",
                    external_ref=clean["invoice_id"],
                    status=clean["status"],
                    verification="provider_record",
                    evidence="PayPal list_invoices record",
                    raw_digest=digest(record),
                    occurred_at=(action.receipt or {}).get("executed_at") or self._iso(),
                    by=principal.id,
                )
            self._event(
                opp,
                "verified",
                f"The {ACTION_KINDS[action.kind][2]} matches the provider's record",
                by=principal.id,
                ref=ref,
            )
            self._save(opp)
            return action

    def abandon(self, principal: Principal, action_id: str, reason: str, reconciliation: str = "") -> ExternalAction:
        """Close an action that will not be executed. A released ticket needs a destination check first."""
        with self.lock:
            self._human(principal)
            reason = self._reason(reason)
            action = self.action(action_id)
            if action.status not in ("approved", "released", "stale", "blocked", "awaiting_approval"):
                raise RevenueConflict(f"an action that is {action.status} cannot be abandoned")
            if action.status == "released" and len(reconciliation.strip()) < self.office.policy.min_reason_chars:
                raise RevenueError(
                    "a released ticket may already have been executed: say where you checked (the mailbox's sent"
                    " folder, PayPal's invoice list) and what you found"
                )
            opp = self.get(action.opportunity_id)
            if action.approval_id:
                self._cancel_open(opp, principal.id, f"abandoned: {reason}")
                action = self.office.store.get(ExternalAction, action.id) or action
            action.status = "abandoned"
            action.error = reason
            action.verification = {
                "method": "destination_check",
                "checked": reconciliation.strip() or None,
                "checked_by": principal.id,
                "checked_at": self._iso(),
            }
            self._save_action(action)
            self._event(opp, "abandoned", f"Ticket {action.id} abandoned: {reason}", by=principal.id, ref=action.id)
            self._save(opp)
            return action

    # -- customer facts and money ---------------------------------------------------------------------------

    def record_event(
        self, principal: Principal, opp_id: str, kind: str, external_ref: str, occurred_at: str, note: str = ""
    ) -> Opportunity:
        with self.lock:
            self._human(principal)
            if kind not in EVENT_KINDS:
                raise RevenueError(f"kind must be one of {list(EVENT_KINDS)}")
            ref = self._text(external_ref, "external_ref", 2, 300)
            when = self._when(occurred_at, "occurred_at").isoformat(timespec="seconds")
            note = (note or "").strip()
            if len(note) > 500:
                raise RevenueError("note must be at most 500 characters")
            opp = self.get(opp_id)
            if any(e["kind"] == kind and e.get("ref") == ref for e in opp.timeline):
                return opp
            if note and rules.instruction_markers(note, self.office.policy.injection_markers):
                opp.flags.append(
                    f"A {kind.replace('_', ' ')} note holds instruction-like text; it is kept as data only."
                )
            detail = kind.replace("_", " ").capitalize() + (f": {note}" if note else "")
            if kind == "opt_out":
                self.add_suppression(principal, opp.contact["email"], "opt-out by the contact", ref)
                opp = self.get(opp_id)
                self._event(
                    opp,
                    "opt_out",
                    "The contact opted out; no further message can be sent",
                    by=principal.id,
                    ref=ref,
                    at=when,
                )
                self._save(opp)
                return opp
            material = False
            if kind == "quote_requested" and not opp.consent.get("quote_requested_at"):
                opp.consent["quote_requested_at"] = when
                material = True
            try:
                opp.stage = rules.next_stage(opp.stage, "customer_engaged")
            except rules.RuleError as exc:
                raise RevenueConflict(str(exc)) from exc
            self._event(opp, kind, detail, by=principal.id, ref=ref, at=when)
            self._save(opp, material=material)
            return opp

    def record_acceptance(
        self, principal: Principal, opp_id: str, evidence_ref: str, accepted_at: str, quoted_total_cents: int
    ) -> Opportunity:
        """Record the client's acceptance. Only a person can, and only with the evidence of it."""
        with self.lock:
            self._human(principal)
            opp = self.get(opp_id)
            if opp.stage != "proposal_sent":
                raise RevenueConflict(f"an acceptance needs a sent proposal; the opportunity is {opp.stage}")
            proposal = [
                a for a in self.actions(opp.id) if a.kind == "proposal_email" and a.status in ("executed", "verified")
            ]
            if not proposal:
                raise RevenueConflict("no sent proposal is on record")
            quoted = int(proposal[-1].payload["quoted_total_cents"])
            if quoted_total_cents != quoted:
                raise RevenueError(f"the accepted amount must equal the proposal's {quoted}")
            evidence = self._text(evidence_ref, "evidence_ref", 3, 300)
            when = self._when(accepted_at, "accepted_at").isoformat(timespec="seconds")
            sent = rules.parse_datetime((proposal[-1].receipt or {}).get("executed_at"))
            if sent and rules.parse_datetime(when) < sent:  # type: ignore[operator]
                raise RevenueError("accepted_at is before the proposal was sent")
            currency = str(proposal[-1].payload["currency"])
            opp.terms = {
                "accepted_at": when,
                "evidence_ref": evidence,
                "quoted_total_cents": quoted,
                "currency": currency,
                "proposal_action_id": proposal[-1].id,
                "recorded_by": principal.id,
            }
            opp.stage = rules.next_stage(opp.stage, "terms_accepted")
            self._money(
                opp,
                kind="terms_accepted",
                amount=quoted,
                currency=currency,
                provider="operator",
                record_type="acceptance",
                external_ref=evidence,
                status="accepted",
                verification="operator_attested",
                evidence=evidence,
                raw_digest=None,
                occurred_at=when,
                by=principal.id,
            )
            self._event(
                opp,
                "terms_accepted",
                f"Accepted at {rules.money_text(quoted, currency)}",
                by=principal.id,
                ref=evidence,
                at=when,
            )
            self._save(opp, material=True)
            return opp

    def _money(self, opp: Opportunity, *, kind: str, amount: int, currency: str, provider: str, record_type: str,
               external_ref: str, status: str, verification: str, evidence: str, raw_digest: str | None,
               occurred_at: str, by: str, opportunity_id: str | None = None) -> tuple[MoneyEvent, bool]:  # fmt: skip
        event, created = self.office.store.append_money_event(
            MoneyEvent(
                seq=0,
                event_id=self.office.ids("mon"),
                opportunity_id=opportunity_id or opp.id,
                kind=kind,
                amount_cents=amount,
                currency=currency,
                provider=provider,
                record_type=record_type,
                external_ref=external_ref,
                provider_status=status,
                verification=verification,
                evidence=evidence,
                raw_digest=raw_digest,
                rehearsal=opp.rehearsal,
                occurred_at=occurred_at,
                recorded_by=by,
                recorded_at=self._iso(),
            )
        )
        if created:
            self.office.log(
                by,
                "human" if by.startswith("operator") else "agent",
                "revenue.money_recorded",
                event.opportunity_id,
                {
                    "kind": kind,
                    "amount_cents": amount,
                    "currency": currency,
                    "verification": verification,
                    "seq": event.seq,
                },
                "high",
            )
        return event, created

    def _received_cents(self, opp_id: str) -> int:
        events = self.office.store.money_events(opp_id)
        got = sum(
            e.amount_cents for e in events if e.kind == "payment_received" and e.verification == "provider_record"
        )
        back = sum(e.amount_cents for e in events if e.kind == "refund")
        return got - back

    def import_payment(
        self, principal: Principal, opp_id: str, record: dict[str, Any], raw_record: Any
    ) -> dict[str, Any]:
        """Import one PayPal record (invoice, transaction or dispute) as returned by the connector."""
        with self.lock:
            self._human(principal)
            try:
                clean = rules.validate_fields(record, rules.PAYMENT_RECORD_SCHEMA, "payment record")
                clean["status"] = clean["status"].upper()
                kind, _ = rules.classify_payment_record(clean)
            except rules.RuleError as exc:
                raise RevenueError(str(exc)) from exc
            problem = rules.raw_record_consistent(raw_record, clean)
            if problem:
                raise RevenueError(problem)
            if rules.credential_rules(raw_record):
                raise RevenueError("the raw record holds credential-shaped text; it was not imported")
            opp = self.get(opp_id)
            key = ("paypal", clean["record_type"], clean["external_ref"], kind)
            already = [
                e
                for e in self.office.store.money_events()
                if (e.provider, e.record_type, e.external_ref, e.kind) == key
            ]
            if already:
                if already[0].opportunity_id != opp.id:
                    raise RevenueConflict(f"this PayPal record is already recorded for {already[0].opportunity_id}")
                return {"event": already[0].to_dict(), "duplicate": True, "stage": opp.stage}
            inv = self._invoice_action(self.actions(opp.id))
            if inv is None:
                raise RevenueConflict("no sent invoice is on record for this opportunity")
            s = self.settings() or {}
            params = {
                "opportunity_id": opp.id,
                "record": clean,
                "currency": inv.payload["currency"],
                "invoice_ref": (inv.receipt or {}).get("external_ref"),
                "expected_total_cents": int(inv.payload["invoice_amount_cents"]),
                "received_so_far_cents": self._received_cents(opp.id),
                "own_payer_emails": s.get("own_payer_emails", []),
            }
            result = self._perform(
                "revenue.delivery",
                "payment.reconcile",
                params,
                opp_id=opp.id,
                key="rev:reconcile:"
                + digest([clean[k] for k in ("record_type", "external_ref", "status", "gross_amount_cents")])[:24],
            )
            art = self._completed(result, "reconciling the record")["artifact"]
            raw_dig = digest(raw_record)
            event, created = self._money(
                opp,
                kind=art["kind"],
                amount=clean["gross_amount_cents"],
                currency=clean["currency"],
                provider="paypal",
                record_type=clean["record_type"],
                external_ref=clean["external_ref"],
                status=clean["status"],
                verification=art["verification"],
                evidence=f"PayPal {clean['record_type']} record imported by {principal.id}",
                raw_digest=raw_dig,
                occurred_at=clean["occurred_at"],
                by=principal.id,
            )
            if clean.get("fee_cents"):
                self._money(
                    opp,
                    kind="fee",
                    amount=clean["fee_cents"],
                    currency=clean["currency"],
                    provider="paypal",
                    record_type=clean["record_type"],
                    external_ref=clean["external_ref"],
                    status=clean["status"],
                    verification="provider_record",
                    evidence="processor fee on the imported record",
                    raw_digest=raw_dig,
                    occurred_at=clean["occurred_at"],
                    by=principal.id,
                )
            if created:
                label = art["kind"].replace("_", " ")
                money = rules.money_text(clean["gross_amount_cents"], clean["currency"])
                self._event(
                    opp,
                    art["kind"],
                    f"{label.capitalize()}: {money} ({art['verification'].replace('_', ' ')})",
                    by=principal.id,
                    ref=clean["external_ref"],
                    at=clean["occurred_at"],
                )
                if art["kind"] == "payment_received" and self._received_cents(opp.id) >= params["expected_total_cents"]:
                    opp.stage = rules.next_stage(opp.stage, "paid")
                    self._event(opp, "paid", "Paid in full on provider records", by="revenue.delivery")
                self._save(opp)
            return {"event": event.to_dict(), "duplicate": not created, "stage": opp.stage}

    def record_cost(
        self,
        principal: Principal,
        description: str,
        amount_cents: int,
        currency: str,
        evidence_ref: str,
        occurred_at: str,
    ) -> dict[str, Any]:
        with self.lock:
            self._human(principal)
            description = self._text(description, "description", 3, 200)
            evidence = self._text(evidence_ref, "evidence_ref", 3, 300)
            if (
                not isinstance(amount_cents, int)
                or isinstance(amount_cents, bool)
                or not 1 <= amount_cents <= 100_000_000
            ):
                raise RevenueError("amount_cents must be a positive whole number")
            if currency != self.cfg.currency:
                raise RevenueError(f"currency must be {self.cfg.currency}")
            when = self._when(occurred_at, "occurred_at").isoformat(timespec="seconds")
            holder = Opportunity(
                id="company", stage="new", rehearsal=False, source="", source_ref="", contact={}, consent={}
            )
            event, created = self._money(
                holder,
                kind="operating_cost",
                amount=amount_cents,
                currency=currency,
                provider="operator",
                record_type="cost",
                external_ref=evidence,
                status="recorded",
                verification="operator_attested",
                evidence=description,
                raw_digest=None,
                occurred_at=when,
                by=principal.id,
            )
            return {"event": event.to_dict(), "duplicate": not created}

    def handoff(self, principal: Principal, opp_id: str, authorization_ref: str) -> Opportunity:
        with self.lock:
            self._human(principal)
            self._running()
            opp = self.get(opp_id)
            if opp.stage != "paid":
                raise RevenueConflict(f"delivery starts after a verified payment; the opportunity is {opp.stage}")
            if opp.offer_sku not in self.cfg.offers:
                raise RevenueConflict("the opportunity's offer is no longer in the catalog")
            published = self.cfg.offers[str(opp.offer_sku)]
            auth = self._text(authorization_ref, "authorization_ref", 3, 300)
            params = {
                "opportunity_id": opp.id,
                "offer_sku": opp.offer_sku,
                "offer_name": published["name"],
                "organization": opp.contact["organization"],
                "authorization_ref": auth,
                "requirements": list(published["fulfillment_requirements"]),
            }
            result = self._perform(
                "revenue.delivery", "fulfillment.handoff", params, opp_id=opp.id, key=f"rev:handoff:{opp.id}"
            )
            art = self._completed(result, "the delivery handoff")["artifact"]
            opp.fulfillment = {
                "handoff_at": self._iso(),
                "authorization_ref": auth,
                "checklist": art["checklist"],
                "agent": "revenue.delivery",
                "requested_by": principal.id,
            }
            opp.stage = rules.next_stage(opp.stage, "handoff")
            self._event(
                opp,
                "handoff",
                "Handed to delivery with the client's authorization on record",
                by="revenue.delivery",
                ref=auth,
            )
            self._save(opp)
            return opp

    def close(self, principal: Principal, opp_id: str, reason: str) -> Opportunity:
        with self.lock:
            self._human(principal)
            reason = self._reason(reason)
            opp = self.get(opp_id)
            opp.stage = rules.next_stage(opp.stage, "lost") if opp.stage in rules.OPEN_STAGES else opp.stage
            if opp.stage != "lost":
                raise RevenueConflict(f"an opportunity that is {opp.stage} cannot be closed as lost")
            self._cancel_open(opp, principal.id, f"opportunity closed: {reason}")
            opp.lost_reason = reason
            self._event(opp, "lost", f"Closed as lost: {reason}", by=principal.id)
            self._save(opp)
            return opp

    # -- reads -------------------------------------------------------------------------------------------------

    def money(self) -> dict[str, Any]:
        """Money by category. Each category is separate; none is derived from another."""
        events = [e for e in self.office.store.money_events() if not e.rehearsal]

        def total(kind: str, verification: str | None = None) -> int:
            return sum(
                e.amount_cents
                for e in events
                if e.kind == kind and (verification is None or e.verification == verification)
            )

        def count(kind: str) -> int:
            return sum(1 for e in events if e.kind == kind)

        potential = 0
        potential_n = 0
        outstanding = 0
        for opp in self.opportunities():
            if opp.rehearsal:
                continue
            offer = self._offer_current(opp) if opp.stage in ("qualified", "contacted", "engaged") else None
            if offer:
                potential += int(offer["total_cents"])
                potential_n += 1
            mine = [e for e in events if e.opportunity_id == opp.id]
            invoiced = sum(e.amount_cents for e in mine if e.kind == "invoice_issued") - sum(
                e.amount_cents for e in mine if e.kind == "invoice_cancelled"
            )
            received = sum(
                e.amount_cents for e in mine if e.kind == "payment_received" and e.verification == "provider_record"
            )
            outstanding += max(0, invoiced - received)
        settled = {e.external_ref for e in events if e.kind in ("payment_received", "payment_failed", "refund")}
        processor_pending = sum(
            e.amount_cents for e in events if e.kind == "payment_pending" and e.external_ref not in settled
        )
        closed_disputes = {e.external_ref for e in events if e.kind == "dispute_closed"}
        open_disputes = sum(
            e.amount_cents for e in events if e.kind == "dispute_opened" and e.external_ref not in closed_disputes
        )
        has_fees = any(e.kind == "fee" for e in events)
        has_costs = any(e.kind == "operating_cost" for e in events)
        received = total("payment_received", "provider_record")
        refunds = total("refund")
        fees = total("fee") if has_fees else None
        cur = self.cfg.currency

        def cat(cid: str, label: str, value: int | None, n: int | None, definition: str) -> dict[str, Any]:
            return {
                "id": cid,
                "label": label,
                "value_cents": value,
                "count": n,
                "currency": cur,
                "definition": definition,
            }

        return {
            "currency": cur,
            "categories": [
                cat(
                    "potential",
                    "Potential pipeline value",
                    potential,
                    potential_n,
                    "List price, including tax, of open opportunities matched to an approved offer that have no"
                    " proposal yet. Not a forecast.",
                ),
                cat(
                    "proposed",
                    "Proposed",
                    total("proposal_issued"),
                    count("proposal_issued"),
                    "Totals of proposals a person recorded as sent.",
                ),
                cat(
                    "accepted",
                    "Accepted (contracted)",
                    total("terms_accepted"),
                    count("terms_accepted"),
                    "Totals the client accepted, recorded by the operator with the evidence of acceptance.",
                ),
                cat(
                    "invoiced",
                    "Invoiced",
                    total("invoice_issued") - total("invoice_cancelled"),
                    count("invoice_issued"),
                    "Invoices confirmed on PayPal's own record, less cancellations. An invoice is not a payment.",
                ),
                cat(
                    "outstanding",
                    "Payment pending (invoiced, not received)",
                    outstanding,
                    None,
                    "For each opportunity, its confirmed invoices less the payments PayPal records as received.",
                ),
                cat(
                    "processor_pending",
                    "Pending at the processor",
                    processor_pending,
                    None,
                    "PayPal records with a pending status and no later settlement. A pending payment is not received.",
                ),
                cat(
                    "received",
                    "Payments received",
                    received,
                    count("payment_received"),
                    "Payments whose PayPal record says paid or successful. Gross, including any sales tax charged.",
                ),
                cat(
                    "reported",
                    "Reported, not verified",
                    total("payment_reported"),
                    count("payment_reported"),
                    "Invoices marked as paid by hand in PayPal. No processor record backs them, so they are"
                    " never counted as received.",
                ),
                cat(
                    "refunds",
                    "Refunds and reversals",
                    refunds,
                    count("refund"),
                    "Refunds and reversals on PayPal records.",
                ),
                cat("disputes", "Open disputes", open_disputes, None, "Amounts under an open PayPal dispute."),
                cat(
                    "fees",
                    "Processor fees",
                    fees,
                    count("fee") if has_fees else None,
                    "Fees on imported PayPal records. Not available until a record carries one.",
                ),
                cat(
                    "costs",
                    "Direct operating costs",
                    total("operating_cost") if has_costs else None,
                    count("operating_cost") if has_costs else None,
                    "Costs the operator recorded with evidence. Not available until one is recorded.",
                ),
                cat(
                    "net_cash",
                    "Cash received less refunds and fees",
                    received - refunds - (fees or 0),
                    None,
                    "Payments received less refunds and known fees. Cash, not revenue and not profit.",
                ),
            ],
            "revenue_recognition": {
                "available": False,
                "reason": "No accounting rules exist in this repository, so no amount is reported as"
                " recognized revenue.",
            },
            "rehearsal_events_excluded": sum(1 for e in self.office.store.money_events() if e.rehearsal),
        }

    def metrics(self, window_days: int = 30) -> dict[str, Any]:
        """Measured results for the window. A rate with no valid denominator is not available, never zero."""
        now = self._now()
        start = now - timedelta(days=window_days)

        def inside(ts: Any) -> bool:
            t = rules.parse_datetime(ts)
            return bool(t and start <= t <= now)

        opps = [o for o in self.opportunities() if not o.rehearsal]
        acts = [a for a in self.actions() if not a.rehearsal]
        events = [e for e in self.office.store.money_events() if not e.rehearsal]

        def timeline(kind: str) -> list[tuple[Opportunity, dict[str, Any]]]:
            return [(o, e) for o in opps for e in o.timeline if e["kind"] == kind and inside(e["at"])]

        def sent(kind: str) -> list[ExternalAction]:
            return [a for a in acts if a.kind == kind and a.receipt and inside(a.receipt["executed_at"])]

        def rate(num: int, den: int) -> float | None:
            return round(num / den, 4) if den else None

        qualified = {o.id for o, _ in timeline("qualified")}
        outreach = sent("outreach_email")
        proposals = sent("proposal_email")
        messages = outreach + proposals
        replied = 0
        for a in outreach:
            opp = next((o for o in opps if o.id == a.opportunity_id), None)
            sent_at = rules.parse_datetime(a.receipt["executed_at"]) if a.receipt else None
            if (
                opp
                and sent_at
                and any(
                    e["kind"] in CUSTOMER_EVENTS and (rules.parse_datetime(e["at"]) or sent_at) > sent_at
                    for e in opp.timeline
                )
            ):
                replied += 1
        accepted_after = sum(
            1 for a in proposals if any(o.id == a.opportunity_id and o.terms.get("accepted_at") for o in opps)
        )
        received = [
            e
            for e in events
            if e.kind == "payment_received" and e.verification == "provider_record" and inside(e.occurred_at)
        ]
        refunds = [e for e in events if e.kind == "refund" and inside(e.occurred_at)]
        costs_known = any(e.kind in ("fee", "operating_cost") for e in events)
        costs = sum(e.amount_cents for e in events if e.kind in ("fee", "operating_cost") and inside(e.occurred_at))
        leads = [o for o in opps if inside(o.created_at)]
        paid_leads = [o for o in leads if any(e["kind"] == "paid" for e in o.timeline)]
        durations = []
        for o in opps:
            paid = next((e for e in o.timeline if e["kind"] == "paid" and inside(e["at"])), None)
            if paid:
                t0, t1 = rules.parse_datetime(o.created_at), rules.parse_datetime(paid["at"])
                if t0 and t1:
                    durations.append((t1 - t0).total_seconds() / 86400)

        def m(
            mid: str, label: str, value: Any, unit: str, definition: str, num: int | None = None, den: int | None = None
        ) -> dict[str, Any]:
            return {
                "id": mid,
                "label": label,
                "value": value,
                "unit": unit,
                "definition": definition,
                "numerator": num,
                "denominator": den,
            }

        return {
            "window_days": window_days,
            "from": start.isoformat(timespec="seconds"),
            "to": now.isoformat(timespec="seconds"),
            "excludes": "Rehearsal opportunities and their money events.",
            "items": [
                m("leads", "Leads recorded", len(leads), "count", "Opportunities recorded in the window."),
                m(
                    "qualified",
                    "Qualified opportunities",
                    len(qualified),
                    "count",
                    "Opportunities scored as qualified in the window.",
                ),
                m(
                    "messages_sent",
                    "Approved messages sent",
                    len(messages),
                    "count",
                    "Approved emails (first contact and proposals) a person recorded as sent in the window.",
                ),
                m(
                    "replies",
                    "Replies",
                    len(timeline("reply_received")),
                    "count",
                    "Client replies recorded in the window.",
                ),
                m(
                    "meetings",
                    "Meetings booked",
                    len(timeline("meeting_booked")),
                    "count",
                    "Bookings recorded in the window.",
                ),
                m(
                    "proposals_issued",
                    "Proposals issued",
                    len(proposals),
                    "count",
                    "Proposal emails recorded as sent in the window.",
                ),
                m(
                    "proposals_accepted",
                    "Proposals accepted",
                    len(timeline("terms_accepted")),
                    "count",
                    "Acceptances recorded in the window.",
                ),
                m(
                    "payments_received",
                    "Payments received",
                    sum(e.amount_cents for e in received),
                    "cents",
                    "Sum of payments with a PayPal paid or successful record in the window.",
                    len(received),
                ),
                m(
                    "refunds",
                    "Refunds",
                    sum(e.amount_cents for e in refunds),
                    "cents",
                    "Refunds and reversals in the window.",
                    len(refunds),
                ),
                m(
                    "direct_costs",
                    "Direct operating costs",
                    costs if costs_known else None,
                    "cents",
                    "Processor fees and recorded operating costs in the window. Not available until one is recorded.",
                ),
                m(
                    "reply_rate",
                    "Reply rate",
                    rate(replied, len(outreach)),
                    "ratio",
                    "Of first emails sent in the window, the share whose client later replied, booked or asked"
                    " for a quote.",
                    replied,
                    len(outreach),
                ),
                m(
                    "acceptance_rate",
                    "Proposal acceptance rate",
                    rate(accepted_after, len(proposals)),
                    "ratio",
                    "Of proposals sent in the window, the share accepted.",
                    accepted_after,
                    len(proposals),
                ),
                m(
                    "lead_to_paid",
                    "Lead-to-payment rate",
                    rate(len(paid_leads), len(leads)),
                    "ratio",
                    "Of leads recorded in the window, the share now paid in full.",
                    len(paid_leads),
                    len(leads),
                ),
                m(
                    "days_to_payment",
                    "Median days from lead to payment",
                    round(statistics.median(durations), 1) if durations else None,
                    "days",
                    "For opportunities paid in full in the window: days from recording the lead to full payment.",
                    len(durations),
                ),
                m(
                    "roi",
                    "Return on investment",
                    None,
                    "ratio",
                    "Not computed. Costs are incomplete and no attribution model exists, so any figure would"
                    " be invented.",
                ),
            ],
        }

    def team(self) -> list[dict[str, Any]]:
        """Each revenue desk: its state, derived only from recorded work."""
        opps = self.opportunities()
        acts = self.actions()
        plans = {o.id: self.plan(o, [a for a in acts if a.opportunity_id == o.id]) for o in opps}
        activity = self.office.store.get_state("revenue.activity", {})
        paused = self.paused_state().get("paused") or self.office.halted
        desks = []
        for role, agent_id, title in TEAM:
            agent = self.office.store.get(Agent, agent_id)
            mine = [(o, plans[o.id]) for o in opps if plans[o.id].get("role") == role]
            open_acts = [a for a in acts if a.agent_id == agent_id and a.status in OPEN_ACTION_STATUSES]
            last = activity.get(agent_id)
            counts: dict[str, int] = {}
            for _, p in mine:
                counts[p["state"]] = counts.get(p["state"], 0) + 1
            if paused or (agent is not None and agent.status == "paused"):
                state = "paused"
            elif agent is not None and agent.status == "working":
                state = "working"
            elif counts.get("blocked"):
                state = "blocked"
            elif open_acts or counts.get("awaiting_approval"):
                state = "awaiting_approval"
            elif counts.get("queued"):
                state = "queued"
            elif counts.get("waiting_for_customer"):
                state = "waiting_for_customer"
            elif counts.get("waiting_for_payment"):
                state = "waiting_for_payment"
            elif last and last.get("status") in ("failed", "denied"):
                state = "failed"
            else:
                state = "idle"
            focus = next(((o, p) for o, p in mine if p["state"] == state), mine[0] if mine else None)
            my_acts = [a for a in acts if a.agent_id == agent_id]
            executed = [a for a in my_acts if a.receipt]
            last_exec = max(executed, key=lambda a: a.receipt["executed_at"]) if executed else None  # type: ignore[index]
            pending_approvals = [
                {"action_id": a.id, "approval_id": a.approval_id, "status": a.status, "kind": a.kind} for a in open_acts
            ]
            desks.append(
                {
                    "role": role,
                    "agent_id": agent_id,
                    "title": title,
                    "callsign": agent.callsign if agent else "",
                    "state": state,
                    "counts": counts,
                    "current": (
                        {
                            "opportunity_id": focus[0].id,
                            "organization": focus[0].contact.get("organization"),
                            "stage": focus[0].stage,
                            "step": focus[1]["label"],
                            "detail": focus[1].get("detail") or focus[1].get("operator_step") or "",
                        }
                        if focus
                        else None
                    ),
                    "approvals": pending_approvals,
                    "last_activity": last,
                    "last_connector_execution": (
                        {
                            "action_id": last_exec.id,
                            "kind": last_exec.kind,
                            "connector": last_exec.connector,
                            "external_ref": last_exec.receipt["external_ref"],  # type: ignore[index]
                            "executed_at": last_exec.receipt["executed_at"],  # type: ignore[index]
                            "status": last_exec.status,
                        }
                        if last_exec
                        else None
                    ),
                    "errors": [
                        a.error
                        for a in my_acts
                        if a.error and a.status in ("stale", "blocked", "verification_failed", "released")
                    ],
                    "usage": {"measured": False, "note": USAGE_NOTE},
                }
            )
        return desks

    def opp_view(self, opp: Opportunity, acts: list[ExternalAction]) -> dict[str, Any]:
        events = self.office.store.money_events(opp.id)
        sums: dict[str, int] = {}
        for e in events:
            sums[e.kind] = sums.get(e.kind, 0) + e.amount_cents
        return {
            **opp.to_dict(),
            "plan": self.plan(opp, acts),
            "offer_name": self.cfg.offers[opp.offer_sku]["name"] if opp.offer_sku in self.cfg.offers else None,
            "actions": [a.id for a in acts],
            "money": sums,
        }

    def detail(self, opp_id: str) -> dict[str, Any]:
        opp = self.get(opp_id)
        acts = self.actions(opp.id)
        return {
            "opportunity": self.opp_view(opp, acts),
            "actions": [a.to_dict() for a in acts],
            "money_events": [e.to_dict() for e in self.office.store.money_events(opp.id)],
            "audit": self.office.audit.events(subject=opp.id, limit=200),
        }

    def snapshot(self) -> dict[str, Any]:
        opps = self.opportunities()
        acts = self.actions()
        suppressions = self.office.store.suppressions()
        return {
            "config_version": self.cfg.version,
            "execution_model": EXECUTION_MODEL,
            "paused": self.paused_state(),
            "readiness": self.readiness(),
            "settings": self.settings_view(),
            "offers": self.offers(),
            "team": self.team(),
            "opportunities": [self.opp_view(o, [a for a in acts if a.opportunity_id == o.id]) for o in opps],
            "actions": [a.to_dict() for a in acts],
            "money": self.money(),
            "metrics": self.metrics(30),
            "suppressions": {"count": len(suppressions), "recent": [s.to_dict() for s in suppressions[-20:]]},
            "lead_sources": self.cfg.lead_sources,
            "consent_bases": self.cfg.consent_bases,
            "consent_note": self.cfg.consent_note,
            "contact_rules": self.cfg.contact_rules,
            "connectors": self.cfg.connector_inventory,
            "desk_states": list(DESK_STATES),
        }


__all__ = ["TEAM", "RevenueConflict", "RevenueDesk", "RevenueError", "RevenueNotFound"]
