import json

import pytest
from clearguard_core.audit import AuditLog, verify


def test_chain_verifies_and_detects_edits_and_removals(now):
    log = AuditLog()
    for i in range(4):
        log.append("decision", {"n": i}, now)
    assert verify(log.records) == []
    edited = [dict(r) for r in log.records]
    edited[1] = dict(edited[1], payload={"n": 99})
    assert any("record 1: content does not match" in p for p in verify(edited))
    removed = log.records[:1] + log.records[2:]
    assert verify(removed)


@pytest.mark.parametrize("payload", [
    {"latitude": 43.3},
    {"nested": {"precise_location": "x"}},
    {"items": [{"audio": "base64"}]},
    {"Transcript": "words"},
])
def test_location_and_raw_media_are_refused(payload, now):
    with pytest.raises(ValueError, match="location or raw media"):
        AuditLog().append("observation", payload, now)


def test_file_round_trip(tmp_path, now):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(str(path))
    log.append("command", {"command": "status"}, now)
    log.append("command", {"command": "pause"}, now)
    assert verify(AuditLog(str(path)).records) == []
    lines = path.read_text().splitlines()
    record = json.loads(lines[0])
    record["payload"]["command"] = "resume"
    lines[0] = json.dumps(record, sort_keys=True)
    path.write_text("\n".join(lines) + "\n")
    assert verify(AuditLog(str(path)).records)
