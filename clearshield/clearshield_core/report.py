"""Output helpers: escaping untrusted text, severity ordering, JSON and text rendering."""

from __future__ import annotations

import json
import sys
import unicodedata
from typing import Any, Iterable

SEVERITY_ORDER = ("high", "medium", "low", "info")


def sanitize(value: Any, limit: int = 256) -> str:
    """Escape control, format (including bidi overrides), private-use and unassigned
    characters so attacker-supplied text cannot drive the terminal. Truncates."""
    text = str(value)
    out = []
    for ch in text[:limit]:
        cat = unicodedata.category(ch)
        if cat[0] == "C" or cat in ("Zl", "Zp"):
            code = ord(ch)
            if code < 0x100:
                out.append(f"\\x{code:02x}")
            elif code < 0x10000:
                out.append(f"\\u{code:04x}")
            else:
                out.append(f"\\U{code:08x}")
        else:
            out.append(ch)
    if len(text) > limit:
        out.append("...")
    return "".join(out)


def severity_counts(findings: Iterable[dict]) -> dict[str, int]:
    counts = {s: 0 for s in SEVERITY_ORDER}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    return counts


def actionable(findings: Iterable[dict]) -> bool:
    """Exit code 1 is reserved for findings above 'info'."""
    return any(f["severity"] != "info" for f in findings)


def sort_findings(findings: list[dict]) -> list[dict]:
    rank = {s: i for i, s in enumerate(SEVERITY_ORDER)}
    return sorted(findings, key=lambda f: (rank.get(f["severity"], 9), f["layer"], f["kind"]))


def _subject(f: dict) -> str:
    for key in ("path", "listener", "source_ip", "file"):
        if f.get(key):
            return sanitize(f[key], 200)
    return ""


def _summary(f: dict) -> str:
    d = f.get("detail") or {}
    kind = f["kind"]
    if kind == "content_changed":
        return f"sha256 {str(d.get('baseline_sha256'))[:12]}... -> {str(d.get('current_sha256'))[:12]}..."
    if kind == "metadata_changed":
        return ", ".join(f"{k} {v['baseline']} -> {v['current']}" for k, v in d.get("fields", {}).items())
    if kind == "symlink_target_changed":
        return f"{sanitize(d.get('baseline'), 120)} -> {sanitize(d.get('current'), 120)}"
    if kind == "new_listener":
        procs = d.get("processes") or []
        who = ", ".join(sanitize(p.get("exe") or p.get("comm") or p.get("pid"), 80) for p in procs)
        return f"scope={d.get('scope')} uid={d.get('uid')} {who or d.get('attribution')}"
    if kind == "repeated_auth_failures":
        return (f"{d.get('failures_in_window')} failures in {d.get('window_seconds')}s "
                f"(threshold {d.get('threshold')}); suspicious, not a confirmed intrusion")
    if kind == "login_success_after_failures":
        return (f"user {sanitize(d.get('user'), 64)} logged in after {d.get('failures_in_window')} "
                "failures; verify with the account owner")
    if kind == "sustained_high_level":
        segs = d.get("segments", [])
        return f"{len(segs)} segment(s) at or above {d.get('threshold_dbfs')} dBFS RMS"
    if kind == "clipping_detected":
        return f"{d.get('runs')} run(s) of >= {d.get('clip_run_samples')} full-scale samples"
    for key in ("status", "error", "note", "reason"):
        if d.get(key):
            return sanitize(d[key], 200)
    return ""


def render_findings(findings: list[dict]) -> list[str]:
    lines = []
    for f in sort_findings(findings):
        lines.append(f"  [{f['severity'].upper():6}] {f['layer']}/{f['kind']}  {_subject(f)}  {_summary(f)}".rstrip())
    return lines


def emit_json(obj: Any) -> None:
    sys.stdout.write(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False))
    sys.stdout.write("\n")


def emit_lines(lines: Iterable[str]) -> None:
    for line in lines:
        sys.stdout.write(line + "\n")
