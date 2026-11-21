"""The response executor: the only component that calls an isolation adapter.

It runs as its own process (``defense.py worker``) and never loads sensor keys.
Each action it runs is a row in the ``actions`` table with a lease, so a
crashed worker's action is picked up and reconciled against the adapter's
actual state instead of being applied twice or forgotten.

Before every call it re-checks, inside a transaction: the emergency stop, the
circuit breaker, the approval and its hash binding, the policy version, the
execution deadline, the target's inventory status, evidence trust, and the
rate and concurrency limits. Any failure blocks the action. Nothing here
removes containment except an approved release.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from datetime import datetime, timedelta
from typing import Any

from .adapters.base import AdapterResult, IsolationAdapter
from .config import Bundle
from .engine import Engine, plan_digest
from .policy import capacity, circuit_open, emergency_stop_engaged
from .store import Store
from .util import Clock, canonical_json, iso, parse_iso

TIMEOUT = AdapterResult("timeout", detail="adapter call exceeded adapter_timeout_seconds")


class Executor:
    def __init__(
        self,
        store: Store,
        bundle: Bundle,
        adapter: IsolationAdapter,
        clock: Clock | None = None,
        *,
        worker_id: str = "worker-1",
        batch: int = 10,
    ) -> None:
        self.store = store
        self.bundle = bundle
        self.adapter = adapter
        self.clock = clock or Clock()
        self.worker_id = worker_id
        self.batch = batch
        self.engine = Engine(store, bundle, self.clock)
        self.r = bundle.config.response

    # ================================================================== loop

    def run_once(self) -> list[dict]:
        self.sweep()
        halted = self._halt_reason()
        if halted:
            return [halted]
        results = self.reconcile()
        attempted: set[str] = {r["action_id"] for r in results if "action_id" in r}
        for _ in range(self.batch):
            if self._halt_reason():
                break
            job = self._claim(exclude=attempted)
            if job is None:
                break
            attempted.add(job["action_id"])  # one attempt per action per pass; retries wait for the next pass
            results.append(self._execute(job))
        return results

    def _halt_reason(self) -> dict | None:
        with self.store.tx() as c:
            stopped, why = emergency_stop_engaged(c, self.bundle.emergency_stop_file)
            if stopped:
                return {"status": "halted", "reason": f"emergency stop: {why}"}
            is_open, why = circuit_open(c)
            if is_open:
                return {"status": "circuit_open", "reason": why}
        return None

    def _call(self, fn, *args) -> AdapterResult:
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(fn, *args)
        try:
            result = future.result(timeout=self.r.adapter_timeout_seconds)
            return result if isinstance(result, AdapterResult) else AdapterResult("ok", detail=str(result),
                                                                                   extra={"value": result})
        except FuturesTimeout:
            return TIMEOUT
        except Exception as exc:  # noqa: BLE001 - every adapter failure is handled as a failed attempt
            return AdapterResult("error", detail=f"{type(exc).__name__}: {exc}")
        finally:
            pool.shutdown(wait=False)

    def _state(self, asset: str, key: str) -> set[str] | None:
        res = self._call(self.adapter.state, asset, key)
        return set(res.extra["value"]) if res.status == "ok" else None

    # ================================================================== sweeps

    def sweep(self) -> None:
        now = self.clock.now()
        with self.store.tx() as c:
            for p in c.execute(
                "SELECT * FROM proposals WHERE status='awaiting_approval' AND expires_at <= ?", (iso(now),)
            ).fetchall():
                c.execute("UPDATE proposals SET status='expired', decided_at=?, decision_reason=? WHERE proposal_id=?",
                          (iso(now), "approval window passed", p["proposal_id"]))
                self.store.transition(c, p["case_id"], "expired" if p["kind"] == "isolate" else "verified",
                                      at=now, actor="system", reason=f"proposal {p['proposal_id']} expired")
            for a in c.execute(
                "SELECT * FROM actions WHERE status='queued' AND execute_by < ?", (iso(now),)
            ).fetchall():
                c.execute("UPDATE actions SET status='expired', updated_at=?, last_error=? WHERE action_id=?",
                          (iso(now), "approved action not started before its deadline", a["action_id"]))
                if a["kind"] == "isolate":
                    self.store.transition(c, a["case_id"], "failed", at=now, actor="system",
                                          reason="approved isolation passed its execution deadline; re-approval needed")
                else:
                    self.store.transition(c, a["case_id"], "verified", at=now, actor="system",
                                          reason="approved release passed its execution deadline; containment remains")
            for k in c.execute(
                "SELECT case_id FROM cases WHERE state='verified' AND review_overdue=0 AND review_due_at <= ?",
                (iso(now),),
            ).fetchall():
                c.execute("UPDATE cases SET review_overdue=1 WHERE case_id=?", (k["case_id"],))
                Store.audit(c, at=now, actor="system", action="review.overdue", subject=k["case_id"],
                            details={"note": "review deadline passed; a timer never removes containment"})

    # ================================================================== claim and preflight

    def _claim(self, exclude: set[str] | None = None) -> Any:
        now = self.clock.now()
        skip = sorted(exclude or ())
        with self.store.tx() as c:
            row = c.execute(
                "SELECT * FROM actions WHERE status='queued' AND (next_attempt_at IS NULL OR next_attempt_at <= ?) "
                f"AND action_id NOT IN ({','.join('?' * len(skip))}) ORDER BY created_at LIMIT 1",
                (iso(now), *skip),
            ).fetchone()
            if row is None:
                return None
            c.execute(
                "UPDATE actions SET status='executing', lease_owner=?, lease_expires=?, attempts=attempts+1, "
                "updated_at=? WHERE action_id=? AND status='queued'",
                (self.worker_id, iso(now + timedelta(seconds=self.r.lease_seconds)), iso(now), row["action_id"]),
            )
            Store.audit(c, at=now, actor=self.worker_id, action="action.claimed", subject=row["case_id"],
                        details={"action_id": row["action_id"], "attempt": row["attempts"] + 1})
            return c.execute("SELECT * FROM actions WHERE action_id=?", (row["action_id"],)).fetchone()

    def _preflight(self, c, a, now: datetime) -> str | None:
        stopped, why = emergency_stop_engaged(c, self.bundle.emergency_stop_file)
        if stopped:
            return f"emergency stop: {why}"
        p = c.execute("SELECT * FROM proposals WHERE proposal_id=?", (a["proposal_id"],)).fetchone()
        ap = c.execute("SELECT * FROM approvals WHERE proposal_id=?", (a["proposal_id"],)).fetchone()
        if p is None or ap is None or ap["decision"] != "approved":
            return "no approval recorded for this action"
        recomputed = plan_digest(json.loads(p["plan_json"]))
        if not (recomputed == p["plan_hash"] == a["plan_hash"] == ap["plan_hash"]):
            return "plan hash mismatch between proposal, approval and action (possible tampering)"
        if ap["policy_version"] != self.bundle.config.policy_version:
            return f"approved under policy {ap['policy_version']}; current policy is {self.bundle.config.policy_version}"
        if now > parse_iso(a["execute_by"]):
            return "execution deadline passed"
        plan = json.loads(p["plan_json"])
        if a["kind"] == "release":
            cont = c.execute("SELECT * FROM containments WHERE case_id=? AND state='active'", (a["case_id"],)).fetchone()
            if cont is None or cont["idempotency_key"] != plan["isolation_idempotency_key"]:
                return "no matching active containment to release"
            return None
        asset = self.bundle.registry.get(a["target_asset_id"])
        if asset is None or asset.protected_class is not None or not asset.authorized_for_containment:
            return "target is not an inventoried, unprotected, containment-authorized asset"
        if asset.environment != self.bundle.config.environment:
            return "target is outside this deployment's environment"
        views = self.engine.signal_views(c, plan["evidence"]["signal_ids"])
        if not views or any(not v.trusted for v in views):
            return "authorizing evidence includes a distrusted sensor"
        if c.execute("SELECT 1 FROM containments WHERE target_asset_id=? AND state='active'",
                     (a["target_asset_id"],)).fetchone():
            return "target already has an active containment"
        ok, why = capacity(c, self.bundle, now=now, case_id=a["case_id"], exclude_action=a["action_id"])
        return None if ok else f"rate or concurrency limit: {why}"

    # ================================================================== execution

    def _execute(self, a) -> dict:
        now = self.clock.now()
        with self.store.tx() as c:
            reason = self._preflight(c, a, now)
            plan = json.loads(c.execute("SELECT plan_json FROM proposals WHERE proposal_id=?",
                                        (a["proposal_id"],)).fetchone()["plan_json"])
            if reason:
                c.execute("UPDATE actions SET status='blocked', last_error=?, lease_owner=NULL, updated_at=? "
                          "WHERE action_id=?", (reason, iso(now), a["action_id"]))
                if a["kind"] == "isolate":
                    self.store.transition(c, a["case_id"], "failed", at=now, actor=self.worker_id,
                                          reason=f"blocked before execution: {reason}")
                else:
                    self.store.transition(c, a["case_id"], "verified", at=now, actor=self.worker_id,
                                          reason=f"release blocked before execution: {reason}")
                Store.audit(c, at=now, actor=self.worker_id, action="action.blocked", subject=a["case_id"],
                            details={"action_id": a["action_id"], "reason": reason})
                return {"action_id": a["action_id"], "status": "blocked", "reason": reason}
            Store.audit(c, at=now, actor=self.worker_id, action="action.executing", subject=a["case_id"],
                        details={"action_id": a["action_id"], "kind": a["kind"], "target": a["target_asset_id"],
                                 "idempotency_key": a["idempotency_key"], "adapter": self.adapter.name})
        if a["kind"] == "isolate":
            p = plan["parameters"]
            res = self._call(self.adapter.apply_isolation, a["target_asset_id"], a["idempotency_key"],
                             list(p["steps"]), list(p["preserve"]))
            return self._after_isolate(a, plan, res, reconciling=False)
        res = self._call(self.adapter.release_isolation, a["target_asset_id"], plan["isolation_idempotency_key"])
        return self._after_release(a, plan, res, reconciling=False)

    def _after_isolate(self, a, plan: dict, res: AdapterResult, *, reconciling: bool) -> dict:
        steps, preserve = list(plan["parameters"]["steps"]), list(plan["parameters"]["preserve"])
        if res.status == "partial":
            return self._finish_partial(a, f"adapter reported partial apply: {res.detail}")
        if res.status in ("applied", "timeout", "reconcile"):
            check = self._call(self.adapter.verify_isolation, a["target_asset_id"], a["idempotency_key"], steps,
                               preserve)
            ok, detail = check.extra.get("value", (False, check.detail)) if check.status == "ok" else (False, check.detail)
            if ok:
                return self._finish_isolated(a, detail, res)
            state = self._state(a["target_asset_id"], a["idempotency_key"])
            if state:
                return self._finish_partial(a, f"verification failed with some rules applied: {detail}")
            if state is None:
                return self._failed_attempt(a, f"{res.detail}; adapter state unreadable", count=not reconciling)
            return self._failed_attempt(a, f"{res.detail}; nothing applied", count=not reconciling)
        return self._failed_attempt(a, res.detail, count=not reconciling)

    def _after_release(self, a, plan: dict, res: AdapterResult, *, reconciling: bool) -> dict:
        check = self._call(self.adapter.verify_released, a["target_asset_id"], plan["isolation_idempotency_key"])
        ok, detail = check.extra.get("value", (False, check.detail)) if check.status == "ok" else (False, check.detail)
        if ok:
            return self._finish_released(a, plan, detail)
        return self._failed_attempt(a, f"{res.detail}; {detail}", count=not reconciling)

    # ================================================================== outcomes

    def _breaker(self, c, now: datetime, *, failed: bool, reason: str = "") -> None:
        state = Store.get_control(c, "circuit_breaker", {"open": False, "failures": 0})
        if not failed:
            if state.get("failures"):
                Store.set_control(c, "circuit_breaker", {"open": False, "failures": 0}, at=now, by=self.worker_id)
            return
        failures = int(state.get("failures", 0)) + 1
        opened = failures >= self.r.circuit_breaker_threshold
        Store.set_control(c, "circuit_breaker", {"open": opened or state.get("open", False), "failures": failures,
                                                 "since": iso(now), "reason": reason}, at=now, by=self.worker_id)
        if opened and not state.get("open"):
            Store.audit(c, at=now, actor=self.worker_id, action="control.circuit_opened", subject="controls",
                        details={"failures": failures, "last_reason": reason})

    def _finish_isolated(self, a, detail: str, res: AdapterResult) -> dict:
        now = self.clock.now()
        with self.store.tx() as c:
            c.execute("UPDATE actions SET status='verified', lease_owner=NULL, updated_at=?, result_json=? "
                      "WHERE action_id=?",
                      (iso(now), canonical_json({"adapter": res.status, "verification": detail}), a["action_id"]))
            c.execute("INSERT INTO containments (target_asset_id, action_id, idempotency_key, case_id, state, partial, "
                      "applied_at) VALUES (?,?,?,?,?,?,?)",
                      (a["target_asset_id"], a["action_id"], a["idempotency_key"], a["case_id"], "active", 0, iso(now)))
            due = iso(now + timedelta(hours=self.r.review_deadline_hours))
            c.execute("UPDATE cases SET review_due_at=? WHERE case_id=?", (due, a["case_id"]))
            self._breaker(c, now, failed=False)
            self.store.transition(c, a["case_id"], "verified", at=now, actor=self.worker_id,
                                  reason=f"isolation verified: {detail}")
            Store.audit(c, at=now, actor=self.worker_id, action="action.verified", subject=a["case_id"],
                        details={"action_id": a["action_id"], "verification": detail, "review_due_at": due})
        return {"action_id": a["action_id"], "status": "verified", "detail": detail}

    def _finish_partial(self, a, detail: str) -> dict:
        now = self.clock.now()
        with self.store.tx() as c:
            c.execute("UPDATE actions SET status='partially_completed', lease_owner=NULL, updated_at=?, last_error=? "
                      "WHERE action_id=?", (iso(now), detail, a["action_id"]))
            c.execute("INSERT INTO containments (target_asset_id, action_id, idempotency_key, case_id, state, partial, "
                      "applied_at) VALUES (?,?,?,?,?,?,?)",
                      (a["target_asset_id"], a["action_id"], a["idempotency_key"], a["case_id"], "active", 1, iso(now)))
            c.execute("UPDATE cases SET escalated=1 WHERE case_id=?", (a["case_id"],))
            self._breaker(c, now, failed=True, reason=detail)
            self.store.transition(c, a["case_id"], "partially_completed", at=now, actor=self.worker_id, reason=detail)
            pb = self.bundle.playbooks[c.execute("SELECT playbook_id FROM proposals WHERE proposal_id=?",
                                                 (a["proposal_id"],)).fetchone()["playbook_id"]]
            Store.audit(c, at=now, actor=self.worker_id, action="action.partially_completed", subject=a["case_id"],
                        details={"action_id": a["action_id"], "detail": detail,
                                 "next": pb.failure_paths.on_partial,
                                 "compensating_actions": list(pb.compensating_actions),
                                 "note": "applied rules are left in place; no automatic rollback"})
        return {"action_id": a["action_id"], "status": "partially_completed", "detail": detail}

    def _finish_released(self, a, plan: dict, detail: str) -> dict:
        now = self.clock.now()
        with self.store.tx() as c:
            c.execute("UPDATE actions SET status='verified', lease_owner=NULL, updated_at=?, result_json=? "
                      "WHERE action_id=?", (iso(now), canonical_json({"verification": detail}), a["action_id"]))
            c.execute("UPDATE containments SET state='released', released_at=? WHERE case_id=? AND state='active'",
                      (iso(now), a["case_id"]))
            self._breaker(c, now, failed=False)
            self.store.transition(c, a["case_id"], "closed", at=now, actor=self.worker_id,
                                  reason=f"release verified: {detail}")
            Store.audit(c, at=now, actor=self.worker_id, action="action.verified", subject=a["case_id"],
                        details={"action_id": a["action_id"], "kind": "release", "verification": detail,
                                 "criteria": plan.get("recovery_criteria")})
        return {"action_id": a["action_id"], "status": "verified", "detail": detail}

    def _failed_attempt(self, a, detail: str, *, count: bool) -> dict:
        now = self.clock.now()
        with self.store.tx() as c:
            attempts = c.execute("SELECT attempts FROM actions WHERE action_id=?", (a["action_id"],)).fetchone()[0]
            if count:
                self._breaker(c, now, failed=True, reason=detail)
            if attempts < self.r.max_attempts:
                nxt = now + timedelta(seconds=self.r.retry_backoff_seconds * attempts)
                c.execute("UPDATE actions SET status='queued', lease_owner=NULL, lease_expires=NULL, next_attempt_at=?, "
                          "last_error=?, updated_at=? WHERE action_id=?", (iso(nxt), detail, iso(now), a["action_id"]))
                Store.audit(c, at=now, actor=self.worker_id, action="action.retry_scheduled", subject=a["case_id"],
                            details={"action_id": a["action_id"], "attempt": attempts, "detail": detail,
                                     "next_attempt_at": iso(nxt)})
                return {"action_id": a["action_id"], "status": "retry_scheduled", "detail": detail}
            c.execute("UPDATE actions SET status='failed', lease_owner=NULL, last_error=?, updated_at=? "
                      "WHERE action_id=?", (detail, iso(now), a["action_id"]))
            c.execute("UPDATE cases SET escalated=1 WHERE case_id=?", (a["case_id"],))
            if a["kind"] == "isolate":
                self.store.transition(c, a["case_id"], "failed", at=now, actor=self.worker_id,
                                      reason=f"isolation failed after {attempts} attempts: {detail}")
            else:
                self.store.transition(c, a["case_id"], "partially_completed", at=now, actor=self.worker_id,
                                      reason=f"release not verified after {attempts} attempts; inspect the device")
            Store.audit(c, at=now, actor=self.worker_id, action="action.failed", subject=a["case_id"],
                        details={"action_id": a["action_id"], "attempts": attempts, "detail": detail})
        return {"action_id": a["action_id"], "status": "failed", "detail": detail}

    # ================================================================== reconciliation

    def reconcile(self) -> list[dict]:
        """Resolve actions whose worker lease expired (a crash or a hung call)."""
        now = self.clock.now()
        with self.store.tx() as c:
            rows = c.execute(
                "SELECT * FROM actions WHERE status='executing' AND lease_expires < ?", (iso(now),)
            ).fetchall()
            plans = {r["action_id"]: json.loads(c.execute("SELECT plan_json FROM proposals WHERE proposal_id=?",
                                                          (r["proposal_id"],)).fetchone()["plan_json"]) for r in rows}
            for r in rows:
                c.execute("UPDATE actions SET lease_owner=?, lease_expires=? WHERE action_id=?",
                          (self.worker_id, iso(now + timedelta(seconds=self.r.lease_seconds)), r["action_id"]))
                Store.audit(c, at=now, actor=self.worker_id, action="action.reconciling", subject=r["case_id"],
                            details={"action_id": r["action_id"], "previous_owner": r["lease_owner"]})
        out = []
        for r in rows:
            plan = plans[r["action_id"]]
            marker = AdapterResult("reconcile", detail="reconciled after an expired lease")
            if r["kind"] == "isolate":
                out.append(self._after_isolate(r, plan, marker, reconciling=True))
            else:
                out.append(self._after_release(r, plan, marker, reconciling=True))
        return out
