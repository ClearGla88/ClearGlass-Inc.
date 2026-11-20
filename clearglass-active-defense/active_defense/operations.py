"""Human operations: approvals, false positives, recovery, emergency stop, sensor trust, queries.

Every entry point takes an authenticated Principal and checks the role itself,
so a caller that skips the API layer still cannot approve as an analyst.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from .config import Principal
from .engine import Engine, plan_digest
from .errors import Conflict, Forbidden, Invalid, NotFound
from .evidence import case_manifest, verify_case
from .policy import capacity, emergency_stop_engaged
from .store import CONTAINED_STATES, Store
from .util import iso, parse_iso

READ_ROLES = frozenset({"analyst", "approver", "admin"})
MAX_TEXT = 1000


def _need(principal: Principal, *roles: str) -> None:
    if principal.role not in roles:
        raise Forbidden(f"role {principal.role} may not perform this action")


def _text(value: str, what: str) -> str:
    value = (value or "").strip()
    if not value:
        raise Invalid(f"{what} is required")
    if len(value) > MAX_TEXT:
        raise Invalid(f"{what} is longer than {MAX_TEXT} characters")
    return value


class Operations:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.store = engine.store
        self.bundle = engine.bundle
        self.clock = engine.clock

    # ================================================================== approvals

    def decide(
        self, principal: Principal, proposal_id: str, *, decision: str, plan_hash: str, policy_version: str,
        reason: str,
    ) -> dict:
        _need(principal, "approver")
        reason = _text(reason, "reason")
        if decision not in ("approved", "rejected"):
            raise Invalid("decision must be 'approved' or 'rejected'")
        now = self.clock.now()
        cfg = self.bundle.config
        refusal: tuple[type, str, bool] | None = None
        with self.store.tx() as c:
            p = c.execute("SELECT * FROM proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
            if p is None:
                raise NotFound("no such proposal")
            book = self.bundle.playbooks[p["playbook_id"]]

            def refuse(exc: type, why: str, expire: bool = False) -> None:
                nonlocal refusal
                refusal = (exc, why, expire)

            if p["status"] != "awaiting_approval":
                refuse(Conflict, f"proposal is {p['status']}; one decision is recorded per proposal")
            elif now >= parse_iso(p["expires_at"]):
                refuse(Conflict, "proposal expired before a decision", expire=True)
            elif plan_digest(json.loads(p["plan_json"])) != p["plan_hash"]:
                refuse(Conflict, "stored plan no longer matches its hash; refusing (possible tampering)")
            elif plan_hash != p["plan_hash"]:
                refuse(Conflict, "submitted plan hash does not match the proposal; review the current plan")
            elif policy_version != cfg.policy_version or p["policy_version"] != cfg.policy_version:
                refuse(Conflict, f"policy version is now {cfg.policy_version}; the proposal must be re-evaluated")
            elif book.approval.distinct_from_requester and principal.principal == p["requested_by"]:
                refuse(Forbidden, "the requester cannot approve their own request")
            elif decision == "approved":
                why = self._approval_blockers(c, p, now)
                if why:
                    refuse(Conflict, why)
            if refusal is None:
                self._record_decision(c, p, principal, decision, reason, now)
        if refusal is not None:
            exc, why, expire = refusal
            self._record_refusal(proposal_id, principal, why, expire, now)
            raise exc(why)
        return self.proposal(principal, proposal_id)

    def _approval_blockers(self, c, p, now) -> str | None:
        stopped, why = emergency_stop_engaged(c, self.bundle.emergency_stop_file)
        if stopped:
            return f"emergency stop is engaged ({why})"
        if p["kind"] == "release":
            return None
        asset = self.bundle.registry.get(p["target_asset_id"])
        if asset is None or asset.protected_class is not None or not asset.authorized_for_containment:
            return "target is no longer an inventoried, unprotected, containment-authorized asset"
        sids = json.loads(p["plan_json"])["evidence"]["signal_ids"]
        views = self.engine.signal_views(c, sids)
        if not views or any(not v.trusted for v in views):
            return "authorizing evidence includes a distrusted sensor"
        ok, why = capacity(c, self.bundle, now=now, case_id=p["case_id"])
        if not ok:
            return f"rate or concurrency limit: {why}"
        return None

    def _record_decision(self, c, p, principal: Principal, decision: str, reason: str, now) -> None:
        cfg = self.bundle.config
        c.execute(
            "INSERT INTO approvals (proposal_id, decision, principal, plan_hash, policy_version, at, reason) "
            "VALUES (?,?,?,?,?,?,?)",
            (p["proposal_id"], decision, principal.principal, p["plan_hash"], cfg.policy_version, iso(now), reason),
        )
        c.execute("UPDATE proposals SET status=?, decided_by=?, decided_at=?, decision_reason=? WHERE proposal_id=?",
                  (decision, principal.principal, iso(now), reason, p["proposal_id"]))
        Store.audit(c, at=now, actor=principal.principal, action=f"proposal.{decision}", subject=p["case_id"],
                    details={"proposal_id": p["proposal_id"], "plan_hash": p["plan_hash"], "reason": reason})
        if decision == "approved":
            self.engine.enqueue_action(c, p["proposal_id"], now=now)
            if p["kind"] == "isolate":
                self.store.transition(c, p["case_id"], "executing", at=now, actor=principal.principal,
                                      reason=f"approved {p['proposal_id']}")
        elif p["kind"] == "isolate":
            self.store.transition(c, p["case_id"], "rejected", at=now, actor=principal.principal,
                                  reason=f"approver rejected: {reason}")
        else:
            self.store.transition(c, p["case_id"], "verified", at=now, actor=principal.principal,
                                  reason="release rejected; containment remains")

    def _record_refusal(self, proposal_id: str, principal: Principal, why: str, expire: bool, now) -> None:
        with self.store.tx() as c:
            p = c.execute("SELECT * FROM proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
            if expire and p["status"] == "awaiting_approval":
                self.expire_proposal(c, p, now)
            Store.audit(c, at=now, actor=principal.principal, action="proposal.decision_refused",
                        subject=p["case_id"], details={"proposal_id": proposal_id, "reason": why})

    def expire_proposal(self, c, p, now) -> None:
        c.execute("UPDATE proposals SET status='expired', decided_at=?, decision_reason=? WHERE proposal_id=?",
                  (iso(now), "approval window passed", p["proposal_id"]))
        target = "expired" if p["kind"] == "isolate" else "verified"
        self.store.transition(c, p["case_id"], target, at=now, actor="system",
                              reason=f"proposal {p['proposal_id']} expired without a decision")

    # ================================================================== analyst actions

    def false_positive(self, principal: Principal, case_id: str, *, rationale: str) -> dict:
        _need(principal, "analyst")
        rationale = _text(rationale, "rationale")
        now = self.clock.now()
        with self.store.tx() as c:
            case = c.execute("SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone()
            if case is None:
                raise NotFound("no such case")
            if case["state"] in ("closed", "executing", "proposed"):
                raise Conflict(f"case is {case['state']}; mark it after execution finishes, or it is already closed")
            self.engine.start_playbook(
                c, case_id, "PB-06-false-positive", trigger=f"operator:{principal.principal}", now=now,
                ctx={"principal": principal.principal, "reason": f"false positive: {rationale}"},
            )
            c.execute("UPDATE cases SET false_positive=1, finding=? WHERE case_id=?", (rationale, case_id))
            if case["state"] in CONTAINED_STATES:
                Store.audit(c, at=now, actor=principal.principal, action="case.false_positive", subject=case_id,
                            details={"rationale": rationale, "containment": "remains until a PB-07 release is approved"})
                note = "containment remains; submit a recovery request for an approved release"
            else:
                self.store.transition(c, case_id, "closed", at=now, actor=principal.principal,
                                      reason=f"false positive: {rationale}")
                note = "closed"
        return {"case_id": case_id, "result": note}

    def request_recovery(self, principal: Principal, case_id: str, *, criteria: dict[str, str], reason: str) -> dict:
        _need(principal, "analyst")
        reason = _text(reason, "reason")
        book = self.bundle.playbooks["PB-07-recovery"]
        required = [c.id for c in book.recovery_criteria]
        clean = {k: _text(v, f"criterion {k}") for k, v in (criteria or {}).items() if k in required}
        missing = [k for k in required if k not in clean]
        unknown = sorted(set(criteria or {}) - set(required))
        if missing or unknown:
            raise Invalid(f"recovery criteria missing {missing}; unknown {unknown}")
        now = self.clock.now()
        with self.store.tx() as c:
            case = c.execute("SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone()
            if case is None:
                raise NotFound("no such case")
            if case["state"] not in ("verified", "partially_completed"):
                raise Conflict(f"case is {case['state']}; recovery needs a verified or partial containment")
            if c.execute("SELECT 1 FROM containments WHERE case_id=? AND state='active'", (case_id,)).fetchone() is None:
                raise Conflict("case has no active containment")
            stopped, why = emergency_stop_engaged(c, self.bundle.emergency_stop_file)
            if stopped:
                raise Conflict(f"emergency stop is engaged ({why}); no containment change is proposed")
            ctx: dict[str, Any] = {"principal": principal.principal, "criteria": clean, "reason": reason}
            self.engine.start_playbook(c, case_id, "PB-07-recovery", trigger=f"operator:{principal.principal}",
                                       now=now, ctx=ctx)
        return self.proposal(principal, ctx["proposal_id"])

    # ================================================================== admin controls

    def set_emergency_stop(self, principal: Principal, *, engaged: bool, reason: str) -> dict:
        _need(principal, "admin")
        reason = _text(reason, "reason")
        now = self.clock.now()
        with self.store.tx() as c:
            Store.set_control(c, "emergency_stop", {"engaged": engaged, "by": principal.principal, "reason": reason,
                                                    "at": iso(now)}, at=now, by=principal.principal)
            cancelled = []
            if engaged:
                for a in c.execute("SELECT action_id, case_id, kind FROM actions WHERE status='queued'").fetchall():
                    c.execute("UPDATE actions SET status='cancelled', last_error=?, updated_at=? WHERE action_id=?",
                              ("cancelled by emergency stop", iso(now), a["action_id"]))
                    if a["kind"] == "isolate":
                        self.store.transition(c, a["case_id"], "failed", at=now, actor=principal.principal,
                                              reason="queued isolation cancelled by emergency stop")
                    else:
                        self.store.transition(c, a["case_id"], "verified", at=now, actor=principal.principal,
                                              reason="queued release cancelled by emergency stop; containment remains")
                    cancelled.append(a["action_id"])
            Store.audit(c, at=now, actor=principal.principal, action="control.emergency_stop", subject="controls",
                        details={"engaged": engaged, "reason": reason, "cancelled_actions": cancelled,
                                 "existing_containment": "unchanged"})
        return {"engaged": engaged, "cancelled_actions": cancelled,
                "note": "existing containment is not removed by an emergency stop"}

    def reset_circuit(self, principal: Principal, *, reason: str) -> dict:
        _need(principal, "admin")
        reason = _text(reason, "reason")
        now = self.clock.now()
        with self.store.tx() as c:
            Store.set_control(c, "circuit_breaker", {"open": False, "failures": 0}, at=now, by=principal.principal)
            Store.audit(c, at=now, actor=principal.principal, action="control.circuit_reset", subject="controls",
                        details={"reason": reason})
        return {"open": False}

    def set_sensor_trust(self, principal: Principal, sensor_id: str, *, trusted: bool, reason: str) -> dict:
        _need(principal, "admin")
        reason = _text(reason, "reason")
        if sensor_id not in self.bundle.sensors:
            raise NotFound("no such sensor")
        now = self.clock.now()
        with self.store.tx() as c:
            result = self.engine.set_sensor_trust(c, sensor_id, trusted=trusted, actor=principal.principal,
                                                  reason=reason, now=now)
            if not trusted:
                case_id = self.engine._case_for(c, f"sensor:{sensor_id}", "high", now)
                self.engine.start_playbook(c, case_id, "PB-08-sensor-distrust",
                                           trigger=f"operator:{principal.principal}", now=now,
                                           ctx={"subject_sensor_id": sensor_id})
        return result

    # ================================================================== queries

    def list_cases(self, principal: Principal, *, state: str | None = None, limit: int = 100) -> list[dict]:
        _need(principal, *READ_ROLES)
        q = "SELECT * FROM cases" + (" WHERE state=?" if state else "") + " ORDER BY opened_at DESC LIMIT ?"
        args = (state, limit) if state else (limit,)
        return [dict(r) for r in self.store.connect().execute(q, args)]

    def case(self, principal: Principal, case_id: str) -> dict:
        _need(principal, *READ_ROLES)
        c = self.store.connect()
        row = c.execute("SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone()
        if row is None:
            raise NotFound("no such case")
        events = [
            {k: r[k] for k in ("event_pk", "event_id", "sensor_id", "category", "severity", "occurred_at",
                               "ingested_at", "late", "src_ip", "subject", "identity_status", "identity_reason",
                               "artifact_id")}
            | {"attributes": json.loads(r["attributes_json"]), "derived": json.loads(r["derived_json"])}
            for r in c.execute(
                "SELECT e.* FROM events e JOIN case_events ce ON ce.event_pk=e.event_pk WHERE ce.case_id=? "
                "ORDER BY e.occurred_at", (case_id,))
        ]
        return {
            "case": dict(row),
            "events": events,
            "signals": [dict(r) | {"sensor_trusted": Store.sensor_trusted(c, r["sensor_id"])}
                        for r in c.execute("SELECT * FROM signals WHERE case_id=? ORDER BY occurred_at", (case_id,))],
            "transitions": [dict(r) for r in c.execute(
                "SELECT from_state, to_state, at, actor, reason FROM case_transitions WHERE case_id=? ORDER BY seq",
                (case_id,))],
            "playbooks": [dict(r) for r in c.execute("SELECT * FROM case_playbooks WHERE case_id=?", (case_id,))],
            "correlations": [dict(r) for r in c.execute(
                "SELECT * FROM case_correlations WHERE case_id=?", (case_id,))],
            "proposals": [self._proposal_view(r) for r in c.execute(
                "SELECT * FROM proposals WHERE case_id=? ORDER BY created_at", (case_id,))],
            "actions": [dict(r) for r in c.execute("SELECT * FROM actions WHERE case_id=? ORDER BY created_at",
                                                   (case_id,))],
        }

    @staticmethod
    def _proposal_view(r) -> dict:
        d = dict(r)
        d["plan"] = json.loads(d.pop("plan_json"))
        d["decision"] = json.loads(d.pop("decision_json"))
        return d

    def proposal(self, principal: Principal, proposal_id: str) -> dict:
        _need(principal, *READ_ROLES)
        r = self.store.connect().execute("SELECT * FROM proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
        if r is None:
            raise NotFound("no such proposal")
        return self._proposal_view(r)

    def list_proposals(self, principal: Principal, *, status: str | None = None) -> list[dict]:
        _need(principal, *READ_ROLES)
        q = "SELECT * FROM proposals" + (" WHERE status=?" if status else "") + " ORDER BY created_at DESC LIMIT 200"
        return [self._proposal_view(r) for r in self.store.connect().execute(q, (status,) if status else ())]

    def evidence(self, principal: Principal, case_id: str) -> dict:
        _need(principal, *READ_ROLES)
        c = self.store.connect()
        if c.execute("SELECT 1 FROM cases WHERE case_id=?", (case_id,)).fetchone() is None:
            raise NotFound("no such case")
        return {"manifest": case_manifest(c, case_id, at=self.clock.now()), "verification": verify_case(c, case_id)}

    def verify_audit(self, principal: Principal) -> dict:
        _need(principal, "admin")
        return self.store.verify_audit()

    def metrics(self, principal: Principal) -> dict:
        _need(principal, *READ_ROLES)
        c = self.store.connect()

        def one(q: str, *a) -> Any:
            return c.execute(q, a).fetchone()[0]

        def avg_seconds(rows) -> float | None:
            vals = [(parse_iso(b) - parse_iso(a)).total_seconds() for a, b in rows if a and b]
            return round(sum(vals) / len(vals), 3) if vals else None

        return {
            "label": {
                "environment": self.bundle.config.environment,
                "mode": self.bundle.config.mode,
                "limitations": "Counts from this database only. Lab and synthetic workloads say nothing about "
                               "production precision or latency.",
            },
            "events_accepted": one("SELECT COUNT(*) FROM events"),
            "events_rejected": one("SELECT COUNT(*) FROM ingest_failures"),
            "cases_opened": one("SELECT COUNT(*) FROM cases"),
            "cases_false_positive": one("SELECT COUNT(*) FROM cases WHERE false_positive=1"),
            "alert_precision": (
                None if one("SELECT COUNT(*) FROM cases WHERE state='closed'") == 0 else round(
                    1 - one("SELECT COUNT(*) FROM cases WHERE false_positive=1 AND state='closed'")
                    / one("SELECT COUNT(*) FROM cases WHERE state='closed'"), 3)
            ),
            "event_to_case_seconds_avg": avg_seconds(c.execute(
                "SELECT e.occurred_at, k.opened_at FROM cases k JOIN case_events ce ON ce.case_id=k.case_id "
                "JOIN events e ON e.event_pk=ce.event_pk WHERE e.event_pk=(SELECT MIN(event_pk) FROM case_events "
                "WHERE case_id=k.case_id)").fetchall()),
            "approval_seconds_avg": avg_seconds(c.execute(
                "SELECT created_at, decided_at FROM proposals WHERE status IN ('approved','rejected') "
                "AND decided_by NOT LIKE 'policy:%'").fetchall()),
            "action_verification_seconds_avg": avg_seconds(c.execute(
                "SELECT created_at, updated_at FROM actions WHERE status='verified'").fetchall()),
            "false_containment_count": one(
                "SELECT COUNT(DISTINCT x.case_id) FROM containments x JOIN cases k ON k.case_id=x.case_id "
                "WHERE k.false_positive=1"),
            "recoveries_verified": one("SELECT COUNT(*) FROM actions WHERE kind='release' AND status='verified'"),
            "recoveries_failed": one("SELECT COUNT(*) FROM actions WHERE kind='release' AND status='failed'"),
            "active_containments": one("SELECT COUNT(*) FROM containments WHERE state='active'"),
        }


def review_due(now, hours: int) -> str:
    return iso(now + timedelta(hours=hours))
