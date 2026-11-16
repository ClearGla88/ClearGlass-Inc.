import pytest

from guardian_core.audit import AuditLog
from guardian_core.errors import AuditError
from gs_testlib import KEY, NOW


@pytest.mark.parametrize("key", [None, KEY])
def test_chain_verifies_and_detects_edits_and_reordering(key):
    log = AuditLog(key)
    for i in range(3):
        log.record("command", {"command": "status", "n": i}, NOW + i)
    log.verify()
    log.records[1]["data"]["n"] = 99
    with pytest.raises(AuditError, match="tag mismatch"):
        log.verify()
    log2 = AuditLog(key)
    for i in range(3):
        log2.record("command", {"n": i}, NOW + i)
    log2.records.pop(1)
    with pytest.raises(AuditError, match="chain link"):
        log2.verify()


@pytest.mark.parametrize("data", [{"location": "x"}, {"nested": {"lat": 1}}, {"items": [{"raw_audio": "b"}]},
                                  {"recipient_ref": "r"}])
def test_location_media_and_recipients_never_reach_the_log(data):
    with pytest.raises(AuditError, match="not allowed"):
        AuditLog().record("event", data, NOW)
