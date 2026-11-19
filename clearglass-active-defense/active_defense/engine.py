"""Ingestion, normalization, correlation, and the playbook runner.

This module holds no containment credentials and calls no adapter. The most it
can do is write a proposal; only the executor (executor.py) acts, and only on
an approved, hash-bound proposal.

Event content (paths, user agents, file names, any free text) is stored and
displayed as data. No decision in this module reads free text: rules match
typed attribute values exactly, and policy takes typed values only.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError

from . import honeytokens, signing
from .adapters.base import ISOLATION_STEPS
from .assets import (
    AUTHORIZED_SCANNER,
    RESOLVED,
    SENSOR_REF,
    UNKNOWN,
    UNVERIFIED,
    Identity,
)
from .config import Bundle
from .errors import Rejected
from .evidence import case_manifest, store_artifact
from .models import CATEGORY_SUBJECT, SEVERITY_RANK, DetectionRule, EventIn, Playbook, SensorConfig
from .policy import SignalView, evaluate_isolation
from .store import Store
from .util import Clock, canonical_json, iso, new_id, parse_iso, sha256_hex

SENSITIVE_KEY = re.compile(r"pass|secret|token|authorization|cookie|api_?key|credential|session", re.I)
PROPOSABLE_STATES = frozenset({"enriched", "rejected", "expired", "failed", "partially_completed"})


def redact(attributes: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in attributes.items():
        if key == "honeytoken_fingerprints":
            out[key] = value  # hashes, not secrets
        elif SENSITIVE_KEY.search(key):
            out[key] = "[REDACTED]"
        elif isinstance(value, str):
            out[key] = honeytokens.HONEYTOKEN_RE.sub("[HONEYTOKEN]", value)
        elif isinstance(value, list):
            out[key] = [honeytokens.HONEYTOKEN_RE.sub("[HONEYTOKEN]", v) for v in value]
        else:
            out[key] = value
    return out


def rule_matches(rule: DetectionRule, event: EventIn, derived: Mapping[str, Any]) -> bool:
    if rule.match.category != event.category:
        return False
    for key, allowed in rule.match.attributes.items():
        value = event.attributes.get(key)
        if value is None or isinstance(value, list):
            return False
        if not any(type(value) is type(a) and value == a for a in allowed):
            return False
    for key, allowed in rule.match.derived.items():
        value = derived.get(key)
        if not any(value is a for a in allowed):
            return False
    return True


def isolation_key(kind: str, case_id: str, target: str, plan_hash: str) -> str:
    return sha256_hex(f"{kind}|{case_id}|{target}|{plan_hash}")


def plan_digest(plan: dict) -> str:
    return sha256_hex(canonical_json(plan))


class Engine:
    def __init__(self, store: Store, bundle: Bundle, clock: Clock | None = None) -> None:
        self.store = store
        self.bundle = bundle
        self.clock = clock or Clock()

    # ================================================================== ingestion

    def ingest(self, headers: Mapping[str, str], body: bytes) -> dict:
        now = self.clock.now()
        h = {k.lower(): v for k, v in headers.items()}
        claimed = h.get("x-cg-sensor", "")
        label = claimed if signing.SENSOR_RE.match(claimed) else "<invalid>"
        try:
            return self._ingest(h, body, now, claimed)
        except Rejected as rej:
            self._record_rejection(label, rej, body, now)
            raise

    def _ingest(self, h: dict[str, str], body: bytes, now: datetime, claimed: str) -> dict:
        cfg = self.bundle.config
        if len(body) > cfg.ingest.max_body_bytes:
            raise Rejected(413, "body exceeds max_body_bytes")
        ts, nonce, sig = h.get("x-cg-timestamp", ""), h.get("x-cg-nonce", ""), h.get("x-cg-signature", "")
        if not (
            signing.SENSOR_RE.match(claimed)
            and signing.TIMESTAMP_RE.match(ts)
            and signing.NONCE_RE.match(nonce)
            and signing.SIGNATURE_RE.match(sig)
        ):
            raise Rejected(401, "missing or malformed authentication headers")
        key = self.bundle.sensor_keys.get(claimed)
        if key is None:
            raise Rejected(401, "unknown sensor")
        if not signing.verify(key, claimed, ts, nonce, body, sig):
            raise Rejected(401, "signature verification failed")
        skew = cfg.ingest.clock_skew_seconds
        if abs(now.timestamp() - int(ts)) > skew:
            raise Rejected(401, "request timestamp outside the allowed clock skew")
        try:
            event = EventIn.model_validate_json(body)
        except ValidationError as exc:
            first = exc.errors()[0]
            loc = ".".join(str(p) for p in first["loc"]) or "(root)"
            raise Rejected(422, f"schema: {loc}: {first['msg']}") from None
        sensor = self.bundle.sensors[claimed]
        if event.sensor_id != claimed:
            raise Rejected(403, "event sensor_id does not match the authenticated sensor")
        if event.category not in sensor.allowed_categories:
            raise Rejected(403, f"sensor {claimed} may not report {event.category}")
        if event.environment != cfg.environment:
            raise Rejected(403, "event environment does not match this deployment")
        if event.authorization_scope != cfg.authorization_scope:
            raise Rejected(403, "event authorization scope does not match this deployment")
        occurred = event.occurred_at.astimezone(UTC)
        if (occurred - now).total_seconds() > skew:
            raise Rejected(422, "occurred_at is in the future")
        age = (now - occurred).total_seconds()
        if age > cfg.ingest.max_event_age_seconds:
            raise Rejected(422, "event is older than max_event_age_seconds")

        with self.store.tx() as c:
            cutoff = iso(now - timedelta(seconds=cfg.ingest.nonce_ttl_seconds))
            c.execute("DELETE FROM nonces WHERE seen_at < ?", (cutoff,))
            if c.execute("SELECT 1 FROM nonces WHERE sensor_id=? AND nonce=?", (claimed, nonce)).fetchone():
                raise Rejected(409, "replayed request (nonce already used)")
            c.execute("INSERT INTO nonces (sensor_id, nonce, seen_at) VALUES (?,?,?)", (claimed, nonce, iso(now)))
            dup = c.execute(
                "SELECT event_pk FROM events WHERE sensor_id=? AND event_id=?", (claimed, event.event_id)
            ).fetchone()
            if dup is not None:
                cases = [r["case_id"] for r in c.execute("SELECT case_id FROM case_events WHERE event_pk=?", (dup[0],))]
                Store.audit(
                    c, at=now, actor=f"sensor:{claimed}", action="ingest.duplicate", subject=event.event_id,
                    details={"event_pk": dup[0]},
                )
                return {"status": "duplicate", "event_pk": dup[0], "event_id": event.event_id, "cases": cases}
            return self._accept(c, event, sensor, body, now, late=age > skew)

    def _record_rejection(self, sensor_label: str, rej: Rejected, body: bytes, now: datetime) -> None:
        cfg = self.bundle.config
        with self.store.tx() as c:
            c.execute(
                "INSERT INTO ingest_failures (sensor_id, at, code, reason) VALUES (?,?,?,?)",
                (sensor_label, iso(now), rej.status, rej.reason),
            )
            Store.audit(
                c, at=now, actor=f"sensor:{sensor_label}", action="ingest.rejected", subject=sensor_label,
                details={"status": rej.status, "reason": rej.reason, "body_sha256": sha256_hex(body), "size": len(body)},
            )
            if rej.reason != "signature verification failed" or sensor_label not in self.bundle.sensors:
                return
            since = iso(now - timedelta(seconds=cfg.ingest.signature_failure_window_seconds))
            count = c.execute(
                "SELECT COUNT(*) FROM ingest_failures WHERE sensor_id=? AND reason=? AND at >= ?",
                (sensor_label, rej.reason, since),
            ).fetchone()[0]
            if count == cfg.ingest.signature_failure_burst:
                case_id = self._case_for(c, f"sensor:{sensor_label}", "high", now)
                self.start_playbook(
                    c, case_id, "PB-08-sensor-distrust", trigger="signature_failures", now=now,
                    ctx={"subject_sensor_id": sensor_label, "failures": count},
                )

    # ================================================================== analysis

    def _derive(self, c: sqlite3.Connection, event: EventIn) -> dict[str, Any]:
        fps = event.attributes.get("honeytoken_fingerprints")
        if not isinstance(fps, list):
            return {"honeytoken_match": False}
        ids = honeytokens.match(c, list(fps))
        return {"honeytoken_match": bool(ids), "honeytoken_ids": ids}

    def _identify(self, event: EventIn, sensor: SensorConfig) -> tuple[Identity, str]:
        registry = self.bundle.registry
        kind = CATEGORY_SUBJECT[event.category]
        at = event.occurred_at.astimezone(UTC)
        src = str(event.src_ip) if event.src_ip is not None else None
        if kind == "source":
            if src is None:
                return Identity(UNKNOWN, None, "event has no source address"), f"no-source:{sensor.id}"
            ident = registry.resolve_ip(src, at)
            return ident, (f"asset:{ident.asset_id}" if ident.verified else f"ip:{src}")
        if kind == "sensor_host":
            host = sensor.host_asset_id
            assert host is not None  # enforced by config validation
            return Identity(RESOLVED, host, f"decoy file is on {host} (sensor binding)"), f"asset:{host}"
        if kind == "asserted_asset":
            if not sensor.asserts_asset_identity or event.asset_id is None:
                return (
                    Identity(UNVERIFIED, None, "sensor does not assert identity or sent no asset_id"),
                    f"claimed:{event.asset_id or src or sensor.id}",
                )
            ident = registry.verify_asserted(event.asset_id, src, at)
            return ident, (f"asset:{ident.asset_id}" if ident.verified else f"claimed:{event.asset_id}")
        ref = event.attributes.get("subject_sensor_id")
        if isinstance(ref, str) and ref in self.bundle.sensors:
            return Identity(SENSOR_REF, None, f"report concerns sensor {ref}"), f"sensor:{ref}"
        return Identity(UNKNOWN, None, "subject_sensor_id missing or not a configured sensor"), f"report:{sensor.id}"

    def _accept(
        self, c: sqlite3.Connection, event: EventIn, sensor: SensorConfig, body: bytes, now: datetime, *, late: bool
    ) -> dict:
        trusted = Store.sensor_trusted(c, sensor.id)
        derived = self._derive(c, event)
        identity, subject = self._identify(event, sensor)
        artifact_id, digest = store_artifact(
            c, body, media_type="application/json", collector=sensor.id, received_by="ingest", at=now
        )
        correlation_id = new_id("cor")
        attrs = redact(event.attributes)
        cur = c.execute(
            "INSERT INTO events (event_id, schema_version, sensor_id, sensor_auth, sensor_trusted, occurred_at, "
            "ingested_at, late, category, severity, environment, authorization_scope, src_ip, src_port, dst_ip, "
            "dst_port, asserted_asset_id, subject, identity_status, identity_reason, verified_asset_id, "
            "attributes_json, derived_json, artifact_id, correlation_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                event.event_id, event.schema_version, sensor.id, "hmac-sha256:verified", int(trusted),
                iso(event.occurred_at), iso(now), int(late), event.category, event.severity, event.environment,
                event.authorization_scope, str(event.src_ip) if event.src_ip else None, event.src_port,
                str(event.dst_ip) if event.dst_ip else None, event.dst_port, event.asset_id, subject,
                identity.status, identity.reason, identity.asset_id if identity.verified else None,
                canonical_json(attrs), canonical_json(derived), artifact_id, correlation_id,
            ),
        )
        event_pk = cur.lastrowid
        Store.audit(
            c, at=now, actor=f"sensor:{sensor.id}", action="ingest.accepted", subject=event.event_id,
            details={
                "event_pk": event_pk, "category": event.category, "identity": identity.status, "subject": subject,
                "artifact_sha256": digest, "late": late,
            },
        )
        result: dict[str, Any] = {
            "status": "accepted", "event_pk": event_pk, "event_id": event.event_id, "identity": identity.status,
            "subject": subject, "cases": [], "signals": [],
        }
        if not trusted:
            Store.audit(
                c, at=now, actor="engine", action="ingest.evidence_only", subject=event.event_id,
                details={"reason": f"sensor {sensor.id} is distrusted; event kept as evidence, not as a signal"},
            )
            result["note"] = "sensor distrusted: stored as evidence only"
            return result
        if identity.status == AUTHORIZED_SCANNER:
            Store.audit(
                c, at=now, actor="engine", action="ingest.suppressed", subject=event.event_id,
                details={"reason": identity.reason},
            )
            result["note"] = "authorized scanner: stored, no signal raised"
            return result
        matched = [r for r in self.bundle.ruleset.rules if rule_matches(r, event, derived)]
        if not matched:
            result["note"] = "no detection rule matched"
            return result
        occurred = event.occurred_at.astimezone(UTC)
        for rule in matched:
            case_id = self._case_for(c, subject, event.severity, now, correlation_id)
            c.execute("INSERT OR IGNORE INTO case_events (case_id, event_pk) VALUES (?,?)", (case_id, event_pk))
            signal_id = new_id("sig")
            asserting = sensor.asserts_asset_identity and identity.verified
            explanation = f"rule {rule.id} v{rule.version}: category {event.category}" + (
                f", attributes {dict(rule.match.attributes)}" if rule.match.attributes else ""
            ) + (f", derived {dict(rule.match.derived)}" if rule.match.derived else "")
            c.execute(
                "INSERT INTO signals (signal_id, case_id, event_pk, rule_id, rule_version, signal, sensor_id, "
                "occurred_at, identity_asserting, explanation) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (signal_id, case_id, event_pk, rule.id, rule.version, rule.signal, sensor.id, iso(occurred),
                 int(asserting), explanation),
            )
            Store.audit(
                c, at=now, actor="engine", action="signal.raised", subject=case_id,
                details={"signal_id": signal_id, "signal": rule.signal, "rule": rule.id, "rule_version": rule.version,
                         "sensor": sensor.id, "event_pk": event_pk},
            )
            self._raise_severity(c, case_id, event.severity)
            pb_id = self.bundle.ruleset.signal_playbooks.get(rule.signal)
            if pb_id:
                self.start_playbook(
                    c, case_id, pb_id, trigger=f"signal:{rule.signal}", now=now,
                    ctx={"subject_sensor_id": event.attributes.get("subject_sensor_id"), "signal": rule.signal},
                )
            self._evaluate_correlations(c, case_id, occurred, now)
            result["cases"].append(case_id)
            result["signals"].append({"signal_id": signal_id, "signal": rule.signal, "rule": rule.id})
        return result

    def _case_for(
        self, c: sqlite3.Connection, subject: str, severity: str, now: datetime, correlation_id: str | None = None
    ) -> str:
        row = c.execute(
            "SELECT case_id FROM cases WHERE subject=? AND state != 'closed' ORDER BY opened_at DESC LIMIT 1",
            (subject,),
        ).fetchone()
        if row is not None:
            return row["case_id"]
        case_id = new_id("case")
        c.execute(
            "INSERT INTO cases (case_id, subject, state, severity, opened_at, updated_at, correlation_id) "
            "VALUES (?,?,?,?,?,?,?)",
            (case_id, subject, "received", severity, iso(now), iso(now), correlation_id or new_id("cor")),
        )
        c.execute(
            "INSERT INTO case_transitions (case_id, from_state, to_state, at, actor, reason) VALUES (?,?,?,?,?,?)",
            (case_id, None, "received", iso(now), "engine", "first signal for subject"),
        )
        Store.audit(c, at=now, actor="engine", action="case.opened", subject=case_id, details={"subject": subject})
        self.store.transition(c, case_id, "validated", at=now, actor="engine", reason="authenticated, schema-valid")
        self.store.transition(c, case_id, "enriched", at=now, actor="engine", reason="identity resolved, rules applied")
        return case_id

    @staticmethod
    def _raise_severity(c: sqlite3.Connection, case_id: str, severity: str) -> None:
        row = c.execute("SELECT severity FROM cases WHERE case_id=?", (case_id,)).fetchone()
        if SEVERITY_RANK[severity] > SEVERITY_RANK[row["severity"]]:
            c.execute("UPDATE cases SET severity=? WHERE case_id=?", (severity, case_id))

    def signal_views(self, c: sqlite3.Connection, signal_ids: list[str]) -> list[SignalView]:
        views = []
        for sid in signal_ids:
            r = c.execute("SELECT * FROM signals WHERE signal_id=?", (sid,)).fetchone()
            if r is None:
                continue
            views.append(
                SignalView(r["signal_id"], r["signal"], r["sensor_id"], bool(r["identity_asserting"]),
                           Store.sensor_trusted(c, r["sensor_id"]))
            )
        return views

    def _evaluate_correlations(self, c: sqlite3.Connection, case_id: str, occurred: datetime, now: datetime) -> None:
        case = c.execute("SELECT subject FROM cases WHERE case_id=?", (case_id,)).fetchone()
        rows = c.execute("SELECT * FROM signals WHERE case_id=? ORDER BY occurred_at", (case_id,)).fetchall()
        for cor in self.bundle.ruleset.correlations:
            if c.execute(
                "SELECT 1 FROM case_correlations WHERE case_id=? AND correlation_id=?", (case_id, cor.id)
            ).fetchone():
                continue
            wanted = set(cor.all_of) | set(cor.any_of)
            window = [
                r for r in rows
                if r["signal"] in wanted
                and abs((parse_iso(r["occurred_at"]) - occurred).total_seconds()) <= cor.window_seconds
                and Store.sensor_trusted(c, r["sensor_id"])
            ]
            present = {r["signal"] for r in window}
            if any(s not in present for s in cor.all_of):
                continue
            if cor.any_of and not present & set(cor.any_of):
                continue
            if len({r["sensor_id"] for r in window}) < cor.min_distinct_sensors:
                continue
            if cor.requires_verified_asset and not case["subject"].startswith("asset:"):
                Store.audit(
                    c, at=now, actor="engine", action="correlation.blocked", subject=case_id,
                    details={"correlation": cor.id, "reason": f"subject {case['subject']} is not a verified asset"},
                )
                continue
            signal_ids = [r["signal_id"] for r in window]
            c.execute(
                "INSERT INTO case_correlations (case_id, correlation_id, correlation_version, fired_at, signal_ids_json)"
                " VALUES (?,?,?,?,?)",
                (case_id, cor.id, cor.version, iso(now), json.dumps(signal_ids)),
            )
            Store.audit(
                c, at=now, actor="engine", action="correlation.fired", subject=case_id,
                details={"correlation": cor.id, "version": cor.version, "signal_ids": signal_ids,
                         "sensors": sorted({r["sensor_id"] for r in window})},
            )
            self.start_playbook(
                c, case_id, cor.playbook, trigger=f"correlation:{cor.id}", now=now,
                ctx={"signal_ids": signal_ids, "correlation": {"id": cor.id, "version": cor.version}},
            )

    # ================================================================== playbooks

    def start_playbook(
        self, c: sqlite3.Connection, case_id: str, pb_id: str, *, trigger: str, now: datetime, ctx: dict
    ) -> None:
        pb = self.bundle.playbooks[pb_id]
        exists = c.execute(
            "SELECT 1 FROM case_playbooks WHERE case_id=? AND playbook_id=?", (case_id, pb_id)
        ).fetchone()
        if exists and pb.trigger.kind != "operator":
            return
        c.execute(
            "INSERT OR IGNORE INTO case_playbooks (case_id, playbook_id, playbook_version, started_at, trigger) "
            "VALUES (?,?,?,?,?)",
            (case_id, pb_id, pb.version, iso(now), trigger),
        )
        c.execute("UPDATE cases SET playbook_id=?, playbook_version=? WHERE case_id=?", (pb_id, pb.version, case_id))
        Store.audit(
            c, at=now, actor="engine", action="playbook.started", subject=case_id,
            details={"playbook": pb_id, "version": pb.version, "trigger": trigger},
        )
        for action in pb.actions:
            self._run_action(c, case_id, pb, action.type, action.id, trigger, now, ctx)

    def _run_action(
        self, c: sqlite3.Connection, case_id: str, pb: Playbook, kind: str, action_id: str, trigger: str,
        now: datetime, ctx: dict,
    ) -> None:
        actor = f"playbook:{pb.id}"

        def record(action: str, details: dict) -> None:
            Store.audit(c, at=now, actor=actor, action=action, subject=case_id,
                        details={"step": action_id, **details})

        if kind == "record_alert":
            case = c.execute("SELECT severity, subject FROM cases WHERE case_id=?", (case_id,)).fetchone()
            record("alert.recorded", {"severity": case["severity"], "subject": case["subject"], "trigger": trigger})
        elif kind == "notify":
            record("notification.recorded", {
                "channels": list(pb.notifications), "delivered": False,
                "reason": "no outbound notification channel is configured in this build",
            })
        elif kind == "escalate":
            c.execute("UPDATE cases SET escalated=1 WHERE case_id=?", (case_id,))
            record("case.escalated", {"to": list(pb.escalation)})
        elif kind == "preserve_evidence":
            manifest = case_manifest(c, case_id, at=now)
            record("evidence.preserved", {"manifest_sha256": manifest["manifest_sha256"],
                                          "artifacts": len(manifest["artifacts"])})
        elif kind == "scope_assets":
            ctx["scope"] = self._scope(c, case_id, now)
            record("scope.assessed", {"related_assets": ctx["scope"],
                                      "note": "listed for analyst review; only the case subject can be proposed"})
        elif kind == "propose_isolation":
            self._propose_isolation(c, case_id, pb, ctx, now)
        elif kind == "distrust_sensor":
            target = ctx.get("subject_sensor_id")
            if trigger == "signal:sensor_integrity" and isinstance(target, str) and target in self.bundle.sensors:
                self.set_sensor_trust(c, target, trusted=False, actor=actor, now=now,
                                      reason="integrity monitor reported suspected tampering")
            else:
                record("sensor.distrust_recommended", {
                    "sensor": target,
                    "reason": "not automatic for this trigger: forged requests can name any sensor; an admin decides",
                })
        elif kind == "cancel_pending":
            self.cancel_pending(c, case_id, now=now, actor=ctx.get("principal", actor),
                                reason=ctx.get("reason", "playbook cancel"))
        elif kind == "propose_release":
            self._propose_release(c, case_id, pb, ctx, now)
        else:  # pragma: no cover - the model forbids other values
            raise AssertionError(kind)

    def _scope(self, c: sqlite3.Connection, case_id: str, now: datetime) -> list[str]:
        since = iso(now - timedelta(hours=1))
        rows = c.execute(
            "SELECT DISTINCT k.subject FROM cases k JOIN signals s ON s.case_id=k.case_id "
            "WHERE k.case_id != ? AND k.state != 'closed' AND s.occurred_at >= ? AND k.subject LIKE 'asset:%'",
            (case_id, since),
        ).fetchall()
        return sorted(r["subject"][6:] for r in rows)

    # ================================================================== proposals

    def _propose_isolation(self, c: sqlite3.Connection, case_id: str, pb: Playbook, ctx: dict, now: datetime) -> None:
        cfg = self.bundle.config
        case = c.execute("SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone()
        subject = case["subject"]
        asset = self.bundle.registry.get(subject[6:]) if subject.startswith("asset:") else None
        identity = (
            Identity(RESOLVED, asset.asset_id, "case subject is a verified inventoried asset")
            if asset else Identity(UNKNOWN, None, f"case subject {subject} is not a verified asset")
        )
        signal_ids = list(ctx.get("signal_ids", []))
        views = self.signal_views(c, signal_ids)
        decision = evaluate_isolation(
            c, self.bundle, now=now, case_id=case_id, identity=identity, asset=asset, playbook=pb, signals=views
        )
        if cfg.mode == "observe":
            Store.audit(
                c, at=now, actor="policy", action="policy.observe_only", subject=case_id,
                details={"playbook": pb.id, "would_be": decision.outcome, "decision": decision.to_dict()},
            )
            return
        if case["state"] not in PROPOSABLE_STATES:
            Store.audit(
                c, at=now, actor="policy", action="proposal.skipped", subject=case_id,
                details={"reason": f"case is {case['state']}", "playbook": pb.id},
            )
            return
        self.store.transition(c, case_id, "proposed", at=now, actor="policy", reason=f"{pb.id} evaluated")
        target = asset.asset_id if asset else subject
        plan = self._isolation_plan(c, case_id, pb, ctx, asset, target, signal_ids)
        digest = plan_digest(plan)
        ttl = pb.approval.ttl_seconds or cfg.response.approval_ttl_seconds
        status = {"deny": "denied", "require_approval": "awaiting_approval", "preauthorized": "approved"}[
            decision.outcome
        ]
        proposal_id = new_id("prop")
        c.execute(
            "INSERT INTO proposals (proposal_id, case_id, kind, target_asset_id, playbook_id, playbook_version, "
            "plan_json, plan_hash, policy_version, decision_json, status, created_at, expires_at, requested_by) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (proposal_id, case_id, "isolate", target, pb.id, pb.version, canonical_json(plan), digest,
             cfg.policy_version, canonical_json(decision.to_dict()), status, iso(now),
             iso(now + timedelta(seconds=ttl)), f"playbook:{pb.id}"),
        )
        Store.audit(
            c, at=now, actor="policy", action="proposal.created", subject=case_id,
            details={"proposal_id": proposal_id, "kind": "isolate", "target": target, "status": status,
                     "plan_hash": digest, "decision": decision.to_dict()},
        )
        if decision.outcome == "deny":
            failed = ", ".join(ch.name for ch in decision.failed)
            self.store.transition(c, case_id, "rejected", at=now, actor="policy", reason=f"policy denied: {failed}")
            c.execute("UPDATE cases SET escalated=1 WHERE case_id=?", (case_id,))
            Store.audit(c, at=now, actor="policy", action="case.escalated", subject=case_id,
                        details={"reason": "containment denied by policy; human review required", "failed": failed})
        elif decision.outcome == "require_approval":
            self.store.transition(c, case_id, "awaiting_approval", at=now, actor="policy",
                                  reason=f"proposal {proposal_id} needs approval")
        else:
            c.execute(
                "INSERT INTO approvals (proposal_id, decision, principal, plan_hash, policy_version, at, reason) "
                "VALUES (?,?,?,?,?,?,?)",
                (proposal_id, "approved", f"policy:{cfg.policy_version}", digest, cfg.policy_version, iso(now),
                 "preauthorized playbook in enforce mode"),
            )
            c.execute("UPDATE proposals SET decided_by=?, decided_at=?, decision_reason=? WHERE proposal_id=?",
                      (f"policy:{cfg.policy_version}", iso(now), "preauthorized", proposal_id))
            self.enqueue_action(c, proposal_id, now=now)
            self.store.transition(c, case_id, "executing", at=now, actor="policy",
                                  reason=f"preauthorized by policy {cfg.policy_version}")

    def _isolation_plan(
        self, c: sqlite3.Connection, case_id: str, pb: Playbook, ctx: dict, asset, target: str, signal_ids: list[str]
    ) -> dict:
        cfg = self.bundle.config
        arts = c.execute(
            "SELECT DISTINCT e.artifact_id, a.sha256 FROM signals s JOIN events e ON e.event_pk=s.event_pk "
            "JOIN artifacts a ON a.artifact_id=e.artifact_id WHERE s.signal_id IN (%s) ORDER BY e.artifact_id"
            % ",".join("?" * len(signal_ids)),
            signal_ids,
        ).fetchall() if signal_ids else []
        preserve = sorted(asset.management_paths) if asset else []
        dependents = sorted(asset.dependents) if asset else []
        return {
            "plan_schema": 1,
            "action": "isolate_host",
            "target_asset_id": target,
            "target_hostname": asset.hostname if asset else None,
            "environment": asset.environment if asset else None,
            "criticality": asset.criticality if asset else None,
            "adapter": asset.adapter if asset else None,
            "parameters": {"steps": list(ISOLATION_STEPS), "preserve": preserve},
            "case_id": case_id,
            "playbook": {"id": pb.id, "version": pb.version},
            "correlation": ctx.get("correlation"),
            "policy_version": cfg.policy_version,
            "inventory_version": self.bundle.registry.version,
            "ruleset_version": self.bundle.ruleset.ruleset_version,
            "evidence": {
                "signal_ids": sorted(signal_ids),
                "artifacts": [{"artifact_id": a["artifact_id"], "sha256": a["sha256"]} for a in arts],
            },
            "expected_impact": [
                f"{target} loses inbound and outbound network access except its management paths",
                f"dependent assets affected: {dependents or 'none listed in inventory'}",
                "running sessions to the host, other than management, will drop",
            ],
            "preserved_access_paths": preserve,
            "reversal_procedure": [
                "an analyst submits a PB-07 recovery request with every recovery criterion evidenced",
                "a different approver approves the exact release plan",
                "the adapter removes only the rules tagged with this action's idempotency key",
                "the executor verifies no tagged rule remains, then the case closes",
            ],
            "related_assets_for_review": ctx.get("scope", []),
            "blast_radius": "single asset",
        }

    def enqueue_action(self, c: sqlite3.Connection, proposal_id: str, *, now: datetime) -> str:
        p = c.execute("SELECT * FROM proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
        action_id = new_id("act")
        key = isolation_key(p["kind"], p["case_id"], p["target_asset_id"], p["plan_hash"])
        execute_by = now + timedelta(seconds=self.bundle.config.response.execute_within_seconds)
        c.execute(
            "INSERT INTO actions (action_id, proposal_id, case_id, kind, target_asset_id, idempotency_key, plan_hash, "
            "status, created_at, updated_at, execute_by) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (action_id, proposal_id, p["case_id"], p["kind"], p["target_asset_id"], key, p["plan_hash"], "queued",
             iso(now), iso(now), iso(execute_by)),
        )
        Store.audit(c, at=now, actor="engine", action="action.queued", subject=p["case_id"],
                    details={"action_id": action_id, "proposal_id": proposal_id, "kind": p["kind"],
                             "idempotency_key": key, "execute_by": iso(execute_by)})
        return action_id

    def _propose_release(self, c: sqlite3.Connection, case_id: str, pb: Playbook, ctx: dict, now: datetime) -> None:
        cfg = self.bundle.config
        cont = c.execute(
            "SELECT * FROM containments WHERE case_id=? AND state='active'", (case_id,)
        ).fetchone()
        assert cont is not None  # checked by the operator entry point
        plan = {
            "plan_schema": 1,
            "action": "release_isolation",
            "target_asset_id": cont["target_asset_id"],
            "case_id": case_id,
            "isolation_action_id": cont["action_id"],
            "isolation_idempotency_key": cont["idempotency_key"],
            "partial_isolation": bool(cont["partial"]),
            "playbook": {"id": pb.id, "version": pb.version},
            "policy_version": cfg.policy_version,
            "recovery_criteria": ctx["criteria"],
            "requested_by": ctx["principal"],
            "request_reason": ctx["reason"],
            "verification": list(pb.verification),
        }
        digest = plan_digest(plan)
        ttl = pb.approval.ttl_seconds or cfg.response.approval_ttl_seconds
        proposal_id = new_id("prop")
        c.execute(
            "INSERT INTO proposals (proposal_id, case_id, kind, target_asset_id, playbook_id, playbook_version, "
            "plan_json, plan_hash, policy_version, decision_json, status, created_at, expires_at, requested_by) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (proposal_id, case_id, "release", cont["target_asset_id"], pb.id, pb.version, canonical_json(plan),
             digest, cfg.policy_version, canonical_json({"outcome": "require_approval", "checks": []}),
             "awaiting_approval", iso(now), iso(now + timedelta(seconds=ttl)), ctx["principal"]),
        )
        Store.audit(c, at=now, actor=ctx["principal"], action="proposal.created", subject=case_id,
                    details={"proposal_id": proposal_id, "kind": "release", "target": cont["target_asset_id"],
                             "plan_hash": digest})
        self.store.transition(c, case_id, "recovery_pending", at=now, actor=ctx["principal"],
                              reason=f"release proposal {proposal_id} needs approval")
        ctx["proposal_id"] = proposal_id

    # ================================================================== shared operations

    def cancel_pending(self, c: sqlite3.Connection, case_id: str, *, now: datetime, actor: str, reason: str) -> dict:
        # Isolation only. A pending release stays: cancelling it would strand a contained host.
        props = c.execute(
            "SELECT proposal_id FROM proposals WHERE case_id=? AND kind='isolate' AND status='awaiting_approval'",
            (case_id,),
        ).fetchall()
        for p in props:
            c.execute("UPDATE proposals SET status='cancelled', decided_by=?, decided_at=?, decision_reason=? "
                      "WHERE proposal_id=?", (actor, iso(now), reason, p["proposal_id"]))
        acts = c.execute(
            "SELECT action_id FROM actions WHERE case_id=? AND kind='isolate' AND status='queued'", (case_id,)
        ).fetchall()
        for a in acts:
            c.execute("UPDATE actions SET status='cancelled', updated_at=?, last_error=? WHERE action_id=?",
                      (iso(now), reason, a["action_id"]))
        Store.audit(c, at=now, actor=actor, action="pending.cancelled", subject=case_id,
                    details={"proposals": [p["proposal_id"] for p in props],
                             "actions": [a["action_id"] for a in acts], "reason": reason})
        return {"proposals": len(props), "actions": len(acts)}

    def set_sensor_trust(
        self, c: sqlite3.Connection, sensor_id: str, *, trusted: bool, actor: str, reason: str, now: datetime
    ) -> dict:
        c.execute(
            "INSERT INTO sensor_trust (sensor_id, trusted, reason, updated_at, updated_by) VALUES (?,?,?,?,?) "
            "ON CONFLICT(sensor_id) DO UPDATE SET trusted=excluded.trusted, reason=excluded.reason, "
            "updated_at=excluded.updated_at, updated_by=excluded.updated_by",
            (sensor_id, int(trusted), reason, iso(now), actor),
        )
        Store.audit(c, at=now, actor=actor, action="sensor.trust_changed", subject=sensor_id,
                    details={"trusted": trusted, "reason": reason})
        invalidated: list[str] = []
        if trusted:
            return {"sensor_id": sensor_id, "trusted": True, "invalidated": invalidated}
        # Evidence from this sensor stops authorizing anything already in flight.
        rows = c.execute(
            "SELECT p.proposal_id, p.case_id, p.plan_json, p.status, a.action_id, a.status AS astatus "
            "FROM proposals p LEFT JOIN actions a ON a.proposal_id=p.proposal_id "
            "WHERE p.kind='isolate' AND (p.status='awaiting_approval' OR a.status='queued')"
        ).fetchall()
        for r in rows:
            sids = json.loads(r["plan_json"])["evidence"]["signal_ids"]
            if not sids:
                continue
            hit = c.execute(
                "SELECT 1 FROM signals WHERE sensor_id=? AND signal_id IN (%s)" % ",".join("?" * len(sids)),
                [sensor_id, *sids],
            ).fetchone()
            if not hit:
                continue
            why = f"evidence from distrusted sensor {sensor_id}"
            if r["status"] == "awaiting_approval":
                c.execute("UPDATE proposals SET status='invalidated', decision_reason=?, decided_at=? "
                          "WHERE proposal_id=?", (why, iso(now), r["proposal_id"]))
                self.store.transition(c, r["case_id"], "rejected", at=now, actor=actor, reason=why)
            if r["astatus"] == "queued":
                c.execute("UPDATE actions SET status='cancelled', last_error=?, updated_at=? WHERE action_id=?",
                          (why, iso(now), r["action_id"]))
                self.store.transition(c, r["case_id"], "failed", at=now, actor=actor, reason=why)
            invalidated.append(r["proposal_id"])
            Store.audit(c, at=now, actor=actor, action="proposal.invalidated", subject=r["case_id"],
                        details={"proposal_id": r["proposal_id"], "reason": why})
        return {"sensor_id": sensor_id, "trusted": False, "invalidated": invalidated}
