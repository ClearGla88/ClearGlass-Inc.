"""Analyst assistance: case timelines and draft summaries, as advisory text only.

No model is wired in. These functions are deterministic templates over case
data. If a model is added later, it plugs in here, under the same rules:

- it receives read-only case data and returns text;
- nothing in engine, policy, operations or executor imports this module, so no
  decision can read its output (a test enforces the import boundary);
- captured attacker text is quoted as data, never followed as instructions;
- it never invents evidence: every line below cites a stored record.
"""

from __future__ import annotations

import json

ADVISORY = "Advisory text generated from stored records. It is not evidence and no decision reads it."


def _quote(value: object, limit: int = 120) -> str:
    text = json.dumps(value, ensure_ascii=True)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def timeline(case_view: dict) -> list[str]:
    lines = []
    for e in case_view["events"]:
        lines.append(
            f"{e['occurred_at']} event {e['event_id']} from {e['sensor_id']}: {e['category']} "
            f"(identity {e['identity_status']}; attributes {_quote(e['attributes'])})"
        )
    for s in case_view["signals"]:
        lines.append(f"{s['occurred_at']} signal {s['signal']} via {s['rule_id']} v{s['rule_version']}")
    for t in case_view["transitions"]:
        lines.append(f"{t['at']} state {t['from_state']} -> {t['to_state']} by {t['actor']}: {t['reason']}")
    return sorted(lines)


def draft_summary(case_view: dict) -> str:
    c = case_view["case"]
    signals = sorted({s["signal"] for s in case_view["signals"]})
    proposals = [f"{p['kind']} {p['target_asset_id']} ({p['status']})" for p in case_view["proposals"]]
    return "\n".join([
        ADVISORY,
        f"Case {c['case_id']} on {c['subject']}: state {c['state']}, severity {c['severity']}.",
        f"Signals: {', '.join(signals) or 'none'}.",
        f"Proposals: {'; '.join(proposals) or 'none'}.",
        f"Events: {len(case_view['events'])}. Unknowns: identity behind NAT or proxies, intent, and anything "
        "the sensors cannot observe (see each sensor's documented limits).",
    ])
