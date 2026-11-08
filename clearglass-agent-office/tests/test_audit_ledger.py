import sqlite3

import pytest

from audit_ledger import GENESIS_HASH, AuditLedger


def _ledger(n: int = 5) -> tuple[AuditLedger, sqlite3.Connection]:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    ledger = AuditLedger(conn, clock=lambda: "2026-11-09T13:00:00+00:00")
    for i in range(n):
        ledger.append(actor="agent.x", actor_type="agent", event_type="test", subject=f"s{i}", payload={"i": i})
    return ledger, conn


def test_chain_links_and_verifies():
    ledger, _ = _ledger()
    events = ledger.events(newest_first=False)
    assert events[0]["prev_hash"] == GENESIS_HASH
    for prev, cur in zip(events, events[1:], strict=False):
        assert cur["prev_hash"] == prev["hash"]
    result = ledger.verify()
    assert result.ok and result.count == 5 and result.head == events[-1]["hash"]


def test_database_refuses_update_and_delete():
    _, conn = _ledger()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE audit_events SET subject = 'x' WHERE seq = 2")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM audit_events WHERE seq = 2")


def test_tampering_is_detected_at_the_first_bad_record():
    ledger, conn = _ledger()
    # Simulate an attacker with raw database access who drops the guard first.
    conn.execute("DROP TRIGGER audit_events_no_update")
    conn.execute("UPDATE audit_events SET payload = '{\"i\":99}' WHERE seq = 3")
    result = ledger.verify()
    assert not result.ok and result.broken_at == 3 and result.reason == "hash mismatch"


def test_deleted_record_breaks_the_chain():
    ledger, conn = _ledger()
    conn.execute("DROP TRIGGER audit_events_no_delete")
    conn.execute("DELETE FROM audit_events WHERE seq = 2")
    result = ledger.verify()
    assert not result.ok and result.broken_at == 3 and result.reason == "sequence gap"


def test_credentials_are_redacted_before_hashing():
    ledger, _ = _ledger(0)
    key = "sk-ant-" + "a" * 30
    ev = ledger.append(actor="a", actor_type="agent", event_type="t", subject="s", payload={"note": f"token {key}"})
    assert key not in str(ev["payload"])
    assert ev["payload"]["_redacted_rules"] == ["anthropic-key"]
    assert ledger.verify().ok


def test_actor_type_is_a_closed_set():
    ledger, _ = _ledger(0)
    with pytest.raises(sqlite3.IntegrityError):
        ledger.append(actor="a", actor_type="robot", event_type="t", subject="s")
