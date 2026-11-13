"""Command-line interface. Run ``python3 clearshield.py --help``.

Commands kept from the v1 description: init, baseline, scan, verify, audio-wav.
Added: watch, checkpoint, rotate, purge, audio-live. See README.md,
"Command reference", for compatibility notes.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from . import __version__, audio_live, audit, authlog, config, fsutil, integrity, listeners, wavfile
from .errors import (
    EXIT_ERROR,
    EXIT_FINDINGS,
    EXIT_INTEGRITY,
    EXIT_OK,
    ClearShieldError,
    ConfigError,
    IntegrityFailure,
)
from .report import (
    actionable,
    emit_json,
    emit_lines,
    render_findings,
    sanitize,
    severity_counts,
    sort_findings,
)
from .state import load_state, new_state_data, save_state, state_path

DETECTION_NOTE = "Detection only: ClearShield blocked nothing, changed nothing it watches, and uploaded nothing."
STREAM_FACTORY = audio_live.open_sounddevice  # replaced in tests with a simulated stream
_SEGMENT_NAME = re.compile(r"\Aaudit-(\d{6})\.jsonl\Z")


def default_state_dir() -> str:
    env = os.environ.get("CLEARSHIELD_STATE_DIR")
    if env:
        return os.path.abspath(env)
    if os.geteuid() == 0:
        return "/var/lib/clearshield"
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(base, "clearshield")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fmt_db(value: float | None, silent_word: str = "silent") -> str:
    return silent_word if value is None else f"{value:.2f} dBFS"


def _confirm(args: argparse.Namespace, word: str, action: str) -> None:
    if getattr(args, "yes", False):
        return
    if sys.stdin.isatty():
        answer = input(f"Type {word} to {action}: ")
        if answer.strip() == word:
            return
        raise ClearShieldError("not confirmed; nothing was changed.")
    raise ClearShieldError(
        f"refusing to {action} without confirmation. Review the output above, then re-run with --yes."
    )


def _normalize_paths(paths: list[str]) -> list[str]:
    out = []
    for p in paths:
        if not p:
            raise ConfigError("watch paths must not be empty")
        if not os.path.isabs(p):
            print(f"clearshield: note: relative path {sanitize(p)!r} stored as {os.path.abspath(p)}",
                  file=sys.stderr)
        out.append(os.path.normpath(os.path.abspath(p)))
    return sorted(set(out))


class Session:
    """A locked, verified state directory: key, state, config, and audit head."""

    def __init__(self, state_dir: str) -> None:
        self.state_dir = state_dir
        self.notes: list[str] = []
        self._lock = fsutil.StateLock(state_dir)

    def __enter__(self) -> "Session":
        fsutil.check_private_dir(self.state_dir)
        self._lock.__enter__()
        try:
            self.keyring = audit.load_keyring(self.state_dir)
            self.state = load_state(self.state_dir, self.keyring)
            self.cfg, self.cfg_sha = config.load_config(self.state_dir)
            self._finish_interrupted_rotation()
            head, recovered = audit.reconcile_head(self.state_dir, self.keyring, self.state["audit_head"])
            self.log = audit.AuditLog(self.state_dir, self.keyring, head)
            if recovered:
                self.state["audit_head"] = head
                self.save()
                self.notes.append("accepted one audit record written by an interrupted command")
        except BaseException:
            self._lock.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc: object) -> None:
        self._lock.__exit__(*exc)

    def _finish_interrupted_rotation(self) -> None:
        head = self.state["audit_head"]
        if os.path.lexists(audit.log_path(self.state_dir)):
            return
        archived = audit.archive_path(self.state_dir, head["segment"])
        if not os.path.isfile(archived):
            return  # reconcile_head reports the missing log
        last = audit.read_last_record(archived)
        if (audit.check_record_tag(self.keyring, last) is None and last["type"] == "segment_end"
                and last["seq"] == head["seq"] and last["tag"] == head["tag"]):
            previous = audit.head_of(last, head["segment"])
            self.state["audit_head"] = audit.AuditLog.start_segment(
                self.state_dir, self.keyring, head["segment"] + 1, previous)
            self.save()
            self.notes.append(f"completed an interrupted rotation (started segment {head['segment'] + 1})")

    def record(self, rtype: str, data: dict) -> dict:
        rec = self.log.append(rtype, data)
        self.state["audit_head"] = self.log.head
        return rec

    def save(self) -> None:
        save_state(self.state_dir, self.keyring, self.state)


def _print_notes(session: Session) -> None:
    for note in session.notes:
        print(f"clearshield: note: {note}", file=sys.stderr)


# ------------------------------------------------------------------- commands

def cmd_init(args: argparse.Namespace) -> int:
    sd = args.state_dir
    if os.path.lexists(state_path(sd)):
        raise ConfigError(f"already initialized at {sd}. Use 'watch --add PATH' to watch more files.")
    watch = _normalize_paths(args.watch)
    parent = os.path.dirname(sd)
    if parent:
        os.makedirs(parent, mode=0o700, exist_ok=True)
    fsutil.make_private_dir(sd)
    with fsutil.StateLock(sd):
        for leftover in (audit.active_key_path(sd), config.config_path(sd), audit.log_path(sd)):
            if os.path.lexists(leftover):
                raise ConfigError(
                    f"{leftover} exists but there is no state file: an earlier init was interrupted. "
                    f"Inspect {sd}, remove it if it holds nothing you need, then run init again.")
        key = audit.generate_key(sd)
        keyring = audit.Keyring(key, {})
        config.write_default_config(sd)
        head = audit.AuditLog.start_segment(sd, keyring, 1, None)
        log = audit.AuditLog(sd, keyring, head)
        rec = log.append("initialized", {"version": __version__, "watch": watch, "uid": os.geteuid()})
        save_state(sd, keyring, new_state_data(watch, log.head, rec["ts"]))
    if args.json:
        emit_json({"initialized": sd, "watch": watch, "key_id": keyring.active_kid})
        return EXIT_OK
    emit_lines([
        f"ClearShield initialized at {sd}",
        f"  key:      {audit.active_key_path(sd)} (0600). Back it up offline; without it nothing can be verified.",
        f"  config:   {config.config_path(sd)} (conservative defaults; live microphone disabled)",
        f"  watching: {len(watch)} path(s)" + ("" if watch else " - add some with 'watch --add PATH'"),
        "Next: confirm this host is in a known-good state, then run 'baseline'.",
    ])
    return EXIT_OK


def cmd_watch(args: argparse.Namespace) -> int:
    with Session(args.state_dir) as s:
        _print_notes(s)
        current = set(s.state["watch"])
        added = [p for p in _normalize_paths(args.add) if p not in current]
        removed = [p for p in _normalize_paths(args.remove) if p in current]
        if added or removed:
            s.state["watch"] = sorted((current | set(added)) - set(removed))
            s.record("watch_changed", {"added": added, "removed": removed})
            s.save()
        watch = s.state["watch"]
    if args.json:
        emit_json({"watch": watch, "added": added, "removed": removed})
    else:
        lines = [f"Watching {len(watch)} path(s):"] + [f"  {sanitize(p, 400)}" for p in watch]
        if added or removed:
            lines.append("Changes take effect in scans now; approve them into the baseline with "
                         "'baseline --replace'.")
        emit_lines(lines)
    return EXIT_OK


def _collect_listeners(cfg: dict) -> dict:
    lc = cfg["listeners"]
    return listeners.collect("/proc", lc["attribute_processes"], lc["attribution_time_budget_seconds"])


def _baseline_id(files: dict, listener_ids: list[str]) -> str:
    return hashlib.sha256(audit.canonical({"files": files, "listeners": listener_ids})).hexdigest()[:16]


def cmd_baseline(args: argparse.Namespace) -> int:
    with Session(args.state_dir) as s:
        _print_notes(s)
        old = s.state["baseline"]
        if old and not args.replace:
            raise ClearShieldError(
                f"a baseline already exists (id {old['id']}, approved {old['approved_at']}). "
                "Use 'baseline --replace' to review differences and replace it.")
        if args.replace and not old:
            raise ClearShieldError("there is no baseline to replace; run 'baseline' first.")
        watch = s.state["watch"]
        files = integrity.snapshot_all(watch, s.cfg["integrity"]["max_file_bytes"])
        current_listeners = (_collect_listeners(s.cfg) if s.cfg["listeners"]["enabled"]
                             else {"listeners": [], "sources": {}})
        listener_ids = [entry["id"] for entry in current_listeners["listeners"]]
        status_counts = Counter(snap["status"] for snap in files.values())
        lines = [f"Baseline candidate: {len(files)} watched path(s), {len(listener_ids)} TCP listener(s)."]
        problems = {p: snap for p, snap in files.items() if snap["status"] not in ("ok", "missing")}
        for path, snap in problems.items():
            lines.append(f"  warning: {sanitize(path, 300)} is {snap['status']}: "
                         f"{sanitize(snap.get('error', ''), 200)}")
        diff: list[dict] = []
        if args.replace:
            diff = (integrity.compare(old["files"], watch, files)
                    + listeners.compare(old["listeners"], current_listeners, []))
            lines.append(f"Differences from baseline {old['id']}: {len(diff)}")
            lines += render_findings(diff) or ["  (none)"]
        lines.append("Approve only if this host is in a known-good state: ClearShield cannot tell "
                     "whether these files were already altered.")
        if not args.json:
            emit_lines(lines)
        if args.replace:
            _confirm(args, "REPLACE", "replace the approved baseline")
        new = {"files": files, "listeners": listener_ids, "config_sha256": s.cfg_sha,
               "approved_at": audit.utc_now(), "approved_uid": os.geteuid()}
        new["id"] = _baseline_id(files, listener_ids)
        s.state["previous_baseline"] = old
        s.state["baseline"] = new
        s.record("baseline_approved", {
            "id": new["id"], "files": len(files), "listeners": len(listener_ids),
            "file_status_counts": dict(status_counts), "replaced": old["id"] if old else None,
            "differences": len(diff),
        })
        s.save()
    if args.json:
        emit_json({"baseline_id": new["id"], "files": len(files), "listeners": len(listener_ids),
                   "replaced": old["id"] if old else None, "differences": sort_findings(diff)})
    else:
        emit_lines([f"Baseline {new['id']} approved and recorded in the audit log."])
    return EXIT_OK


def cmd_scan(args: argparse.Namespace) -> int:
    with Session(args.state_dir) as s:
        _print_notes(s)
        base = s.state["baseline"]
        if not base:
            raise ClearShieldError("no approved baseline; run 'baseline' first.")
        cfg = s.cfg
        findings: list[dict] = []
        layers: dict[str, Any] = {}
        now = _now()

        if not args.no_integrity:
            current = integrity.snapshot_all(s.state["watch"], cfg["integrity"]["max_file_bytes"])
            found = integrity.compare(base["files"], s.state["watch"], current)
            findings += found
            layers["integrity"] = {"watched": len(s.state["watch"]), "findings": len(found)}
        if base.get("config_sha256") != s.cfg_sha:
            findings.append({"layer": "config", "kind": "config_changed_since_baseline", "severity": "low",
                             "path": config.config_path(s.state_dir),
                             "detail": {"note": "thresholds or sources differ from the approved baseline"}})

        if cfg["listeners"]["enabled"] and not args.no_listeners:
            try:
                allow = listeners.parse_allow(cfg["listeners"]["allow"])
            except ValueError as exc:
                raise ConfigError(str(exc)) from None
            current_l = _collect_listeners(cfg)
            found = listeners.compare(base["listeners"], current_l, allow)
            findings += found
            layers["listeners"] = {"count": len(current_l["listeners"]), "sources": current_l["sources"],
                                   "attribution": current_l["attribution"],
                                   "malformed_lines": current_l["malformed_lines"]}

        if cfg["auth"]["enabled"] and not args.no_auth:
            auth_state = s.state["auth"]
            events, cursors, statuses = authlog.gather(cfg["auth"], auth_state["cursors"], now)
            found = authlog.analyze(events, auth_state, cfg["auth"], now) + authlog.source_findings(statuses)
            auth_state["cursors"] = cursors
            findings += found
            layers["auth"] = {"sources": statuses, "events": len(events)}

        try:
            log_size = os.path.getsize(audit.log_path(s.state_dir))
        except OSError:
            log_size = 0
        if log_size > cfg["audit"]["max_log_bytes"]:
            findings.append({"layer": "audit", "kind": "audit_log_large", "severity": "low",
                             "path": audit.log_path(s.state_dir),
                             "detail": {"bytes": log_size, "note": "run 'rotate' to start a new segment"}})

        findings = sort_findings(findings)
        cap = cfg["audit"]["max_findings_per_record"]
        counts = severity_counts(findings)
        s.record("scan", {"counts": counts, "findings": findings[:cap],
                          "findings_truncated": len(findings) > cap, "layers": layers,
                          "baseline_id": base["id"]})
        s.save()
        scanned_at = now.isoformat(timespec="seconds")

    code = EXIT_FINDINGS if actionable(findings) else EXIT_OK
    if args.json:
        emit_json({"scanned_at": scanned_at, "baseline_id": base["id"], "counts": counts,
                   "findings": findings, "layers": layers, "exit_code": code})
        return code
    lines = [f"ClearShield scan {scanned_at} (baseline {base['id']})"]
    if "integrity" in layers:
        lines.append(f"  integrity: {layers['integrity']['watched']} watched path(s)")
    if "listeners" in layers:
        src = ", ".join(f"{k} {v}" for k, v in layers["listeners"]["sources"].items())
        lines.append(f"  listeners: {layers['listeners']['count']} TCP listener(s) [{src}]")
    if "auth" in layers:
        for st in layers["auth"]["sources"]:
            lines.append(f"  auth: {sanitize(st['source'], 200)} {st['status']}, {st['events']} event(s)")
    shown = [f for f in findings if f["severity"] != "info" or args.verbose]
    hidden = len(findings) - len(shown)
    summary = ", ".join(f"{k} {v}" for k, v in counts.items() if v)
    lines.append(f"Findings: {summary or 'none'}" + (f" ({hidden} info hidden; --verbose shows them)" if hidden else ""))
    lines += render_findings(shown)
    lines.append(DETECTION_NOTE)
    emit_lines(lines)
    return code


def _archived_segments(sd: str) -> dict[int, str]:
    found: dict[int, str] = {}
    adir = audit.archive_dir(sd)
    if os.path.isdir(adir):
        for name in os.listdir(adir):
            m = _SEGMENT_NAME.match(name)
            if m:
                found[int(m.group(1))] = os.path.join(adir, name)
    return found


def _find_record(path: str, seq: int) -> tuple[dict | None, int]:
    """Return (record with this seq or None, last seq seen)."""
    last = -1
    for _, raw, complete in audit.iter_lines(path):
        if not complete:
            break
        try:
            rec = json.loads(raw)
        except ValueError:
            break
        if not isinstance(rec, dict) or not isinstance(rec.get("seq"), int):
            break
        last = rec["seq"]
        if rec["seq"] == seq:
            return rec, last
    return None, last


def cmd_verify(args: argparse.Namespace) -> int:
    sd = args.state_dir
    fsutil.check_private_dir(sd)
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})

    with fsutil.StateLock(sd):
        keyring = audit.load_keyring(sd)
        state: dict | None = None
        try:
            state = load_state(sd, keyring)
            check("state file authentication", True, "authenticated")
        except IntegrityFailure as exc:
            check("state file authentication", False, str(exc))

        active = audit.log_path(sd)
        result = audit.verify_file(active, keyring)
        active_segment = None
        if result["first"] is not None:
            active_segment = (result["first"].get("data") or {}).get("segment")
        if args.all:
            archived = _archived_segments(sd)
            purged = {p["segment"]: p for p in (state or {}).get("purged_segments", [])}
            last_seg = active_segment or (max(archived) + 1 if archived else 1)
            expect_prev: str | None = audit.GENESIS
            for seg in range(1, last_seg):
                if seg in archived:
                    r = audit.verify_file(archived[seg], keyring, expect_prev)
                    ok = r["ok"]
                    detail = f"ok, {r['records']} records" if ok else f"line {r['error']['line']}: {r['error']['reason']}"
                    check(f"archived segment {seg}", ok, detail)
                    expect_prev = r["last"]["tag"] if ok else None
                elif seg in purged:
                    check(f"archived segment {seg}", True, f"purged by operator at {purged[seg].get('purged_at')}")
                    expect_prev = purged[seg]["last_tag"]
                else:
                    check(f"archived segment {seg}", False, "missing and not recorded as purged")
                    expect_prev = None
            result = audit.verify_file(active, keyring, expect_prev)
        ok = result["ok"]
        detail = (f"ok, {result['records']} records" if ok
                  else f"line {result['error']['line']}: {result['error']['reason']}")
        check(f"active segment {active_segment if active_segment is not None else '?'} (audit.jsonl)", ok, detail)

        if state is not None and result["last"] is not None:
            head = state["audit_head"]
            last = result["last"]
            if last["seq"] == head["seq"] and last["tag"] == head["tag"]:
                check("log head matches state", True, f"seq {last['seq']}")
            elif last["seq"] == head["seq"] + 1 and last["prev"] == head["tag"]:
                check("log head matches state", True,
                      "log is one record ahead (interrupted command); the next command reconciles it")
            else:
                check("log head matches state", False,
                      f"log ends at seq {last['seq']}, state expects seq {head['seq']}: "
                      "truncation, rollback, or tampering")

        if args.checkpoint:
            try:
                with open(args.checkpoint, "rb") as fh:
                    raw = fh.read(1 << 20)
            except OSError as exc:
                raise ClearShieldError(f"cannot read checkpoint: {exc.strerror}") from None
            cp = audit.parse_checkpoint(raw)
            purged_set = {p["segment"] for p in (state or {}).get("purged_segments", [])}
            if cp["segment"] == active_segment:
                target = active
            else:
                target = _archived_segments(sd).get(cp["segment"])
            name = f"checkpoint (segment {cp['segment']}, seq {cp['seq']})"
            if target is None:
                why = "segment was purged; cannot verify" if cp["segment"] in purged_set else "segment file missing"
                check(name, False, why)
            else:
                if target != active and not args.all:
                    r = audit.verify_file(target, keyring)
                    if not r["ok"]:
                        check(f"archived segment {cp['segment']}", False, r["error"]["reason"])
                rec, last_seq = _find_record(target, cp["seq"])
                if rec is None:
                    check(name, False, f"log ends at seq {last_seq}, before the checkpoint: "
                                       "truncated or rolled back")
                elif rec.get("tag") != cp["tag"]:
                    check(name, False, "record at this seq differs from the checkpoint: history was "
                                       "rewritten (needs the key) or the checkpoint is from another host")
                else:
                    check(name, True, "matches")

    passed = all(c["ok"] for c in checks)
    if args.json:
        emit_json({"passed": passed, "checks": checks})
    else:
        width = max(len(c["check"]) for c in checks) + 2
        lines = [f"ClearShield verify ({sd})"]
        lines += [f"  {c['check']:<{width}} {'ok ' if c['ok'] else 'FAIL'}  {sanitize(c['detail'], 300)}"
                  for c in checks]
        lines.append("Result: PASS" if passed else "Result: FAIL")
        lines.append("Tamper-evident, not tamper-proof: anyone holding the key can rewrite history, and "
                     "removal of the newest records is caught only by an off-host checkpoint.")
        emit_lines(lines)
    return EXIT_OK if passed else EXIT_INTEGRITY


def cmd_checkpoint(args: argparse.Namespace) -> int:
    with Session(args.state_dir) as s:
        _print_notes(s)
        s.record("checkpoint_exported", {"label": args.label})
        s.save()
        cp = audit.make_checkpoint(s.log.head, args.label)
    body = json.dumps(cp, indent=2, sort_keys=True) + "\n"
    if args.output:
        fsutil.atomic_write(args.output, body.encode("ascii"), 0o600)
        if not args.json:
            emit_lines([f"Checkpoint written to {args.output}. Copy it OFF this host (another machine, "
                        "printed, or write-once storage); a copy here protects nothing."])
    if args.json or not args.output:
        sys.stdout.write(body)
    return EXIT_OK


def cmd_rotate(args: argparse.Namespace) -> int:
    with Session(args.state_dir) as s:
        _print_notes(s)
        segment = s.log.head["segment"]
        dest = audit.archive_path(s.state_dir, segment)
        if os.path.lexists(dest):
            raise ClearShieldError(f"{dest} already exists; refusing to overwrite an archived segment.")
        end = s.record("segment_end", {"reason": args.reason, "new_key": bool(args.new_key)})
        s.save()
        fsutil.make_private_dir(audit.archive_dir(s.state_dir))
        os.replace(audit.log_path(s.state_dir), dest)
        fsutil.fsync_dir(audit.archive_dir(s.state_dir))
        fsutil.fsync_dir(s.state_dir)
        previous = audit.head_of(end, segment)
        if args.new_key:
            s.keyring = audit.rotate_key(s.state_dir, s.keyring)
        s.state["audit_head"] = audit.AuditLog.start_segment(s.state_dir, s.keyring, segment + 1, previous)
        s.save()
        new_kid = s.keyring.active_kid
    if args.json:
        emit_json({"archived": dest, "segment": segment + 1, "key_id": new_kid})
    else:
        emit_lines([f"Segment {segment} archived to {dest}; segment {segment + 1} started.",
                    "Verify across segments with 'verify --all'."])
    return EXIT_OK


def cmd_purge(args: argparse.Namespace) -> int:
    with Session(args.state_dir) as s:
        _print_notes(s)
        active = s.log.head["segment"]
        if args.before_segment > active:
            raise ClearShieldError(f"segment {active} is active and cannot be purged.")
        archived = _archived_segments(s.state_dir)
        targets = sorted(seg for seg in archived if seg < args.before_segment)
        if not targets:
            raise ClearShieldError("no archived segments match.")
        entries = []
        for seg in targets:
            r = audit.verify_file(archived[seg], s.keyring)
            last = r["last"] or {}
            entries.append({"segment": seg, "last_seq": last.get("seq"), "last_tag": last.get("tag"),
                            "verified_before_purge": r["ok"], "purged_at": audit.utc_now()})
        if not args.json:
            emit_lines([f"About to delete archived segment(s) {', '.join(map(str, targets))}. Their records "
                        "become unrecoverable; their final tags stay in the audit log."])
        _confirm(args, "PURGE", "delete these audit segments")
        s.record("segments_purged", {"segments": entries})
        s.state.setdefault("purged_segments", []).extend(entries)
        s.save()
        for seg in targets:
            os.unlink(archived[seg])
        fsutil.fsync_dir(audit.archive_dir(s.state_dir))
    if args.json:
        emit_json({"purged": entries})
    else:
        emit_lines([f"Purged {len(entries)} segment(s)."])
    return EXIT_OK


def _audio_overrides(cfg: dict, args: argparse.Namespace) -> dict:
    full = copy.deepcopy(cfg)
    for attr, key in (("window_ms", "window_ms"), ("sustained_dbfs", "sustained_dbfs"),
                      ("sustained_seconds", "sustained_seconds")):
        value = getattr(args, attr, None)
        if value is not None:
            full["audio"][key] = value
    config.validate(full)
    return full["audio"]


def _render_audio(summary: dict, findings: list[dict], recorded: str) -> list[str]:
    lv, win, clip, sus = summary["levels"], summary["windows"], summary["clipping"], summary["sustained_high"]
    lines = []
    if "format" in summary:
        f = summary["format"]
        lines.append(f"ClearShield audio analysis: {sanitize(summary['file'], 400)}")
        lines.append(f"  format: {f['encoding']}, {f['channels']} ch, {f['sample_rate']} Hz; "
                     f"{summary['duration_s']:.3f} s analysed")
        if summary.get("truncated"):
            lines.append(f"  header declares {summary['declared_frames']} frames; "
                         f"{summary['frames_present']} present")
    else:
        lines.append(f"ClearShield live audio analysis: {sanitize(summary['device'], 100)}, "
                     f"{summary['duration_s']:.3f} s analysed")
    lines.append(f"  peak: {_fmt_db(lv['peak_dbfs'])}   RMS: {_fmt_db(lv['rms_dbfs'])}   "
                 f"silent: {'yes' if lv['silent'] else 'no'}")
    lines.append(f"  windows: {win['count']} x {summary.get('window_ms', '?')} ms, "
                 f"max window RMS {_fmt_db(win['max_rms_dbfs'], 'n/a')}, {win['silent']} silent")
    lines.append(f"  clipping: {clip['runs']} run(s) of >= {clip['clip_run_samples']} consecutive full-scale "
                 f"samples; {clip['samples_at_full_scale']} sample(s) at full scale")
    segs = sus["segments"]
    lines.append(f"  sustained >= {sus['threshold_dbfs']} dBFS RMS for >= {sus['min_seconds']} s: "
                 + (", ".join(f"{g['start_s']}-{g['end_s']} s" for g in segs[:10]) or "none"))
    if "sha256" in summary:
        lines.append(f"  sha256: {summary['sha256']}")
    lines.append(f"Units: {summary['units']}")
    if findings:
        lines.append("Findings:")
        lines += render_findings(findings)
    lines.append("Analysed locally. No audio was uploaded or saved. " + recorded)
    lines.append("A level reading does not identify a sound's source, direction, or intent.")
    return lines


def _audio_record(summary: dict, findings: list[dict]) -> dict:
    data = {k: v for k, v in summary.items() if k != "units"}
    sus = dict(data["sustained_high"])
    sus["segments"] = sus["segments"][:200]
    data["sustained_high"] = sus
    data["findings"] = [f["kind"] for f in findings]
    return data


def cmd_audio_wav(args: argparse.Namespace) -> int:
    sd = args.state_dir
    initialized = os.path.exists(state_path(sd))
    if args.no_record or not initialized:
        audio_cfg = _audio_overrides(config.default_config(), args)
        summary, findings = wavfile.analyze_file(args.wav, audio_cfg)
        recorded = ("Not recorded (--no-record)." if args.no_record
                    else "Not recorded: ClearShield is not initialized, so defaults were used.")
    else:
        with Session(sd) as s:
            _print_notes(s)
            audio_cfg = _audio_overrides(s.cfg, args)
            try:
                summary, findings = wavfile.analyze_file(args.wav, audio_cfg)
            except ClearShieldError as exc:
                s.record("audio_wav_rejected", {"file": os.path.abspath(args.wav), "reason": str(exc)})
                s.save()
                raise
            s.record("audio_wav_analyzed", _audio_record(summary, findings))
            s.save()
        recorded = "Summary recorded in the audit log."
    code = EXIT_FINDINGS if actionable(findings) else EXIT_OK
    if args.json:
        emit_json({"summary": summary, "findings": findings, "exit_code": code})
    else:
        emit_lines(_render_audio(summary, findings, recorded))
    return code


def cmd_audio_live(args: argparse.Namespace) -> int:
    with Session(args.state_dir) as s:
        _print_notes(s)
        live = s.cfg["audio"]["live"]
        if not live["enabled"]:
            raise ClearShieldError(
                "live microphone analysis is disabled. To opt in, set audio.live.enabled to true in "
                f"{config.config_path(s.state_dir)} and pass --allow-microphone.")
        if not args.allow_microphone:
            raise ClearShieldError("pass --allow-microphone to confirm you consent to opening the microphone.")
        if not 0 < args.seconds <= live["max_seconds"]:
            raise ClearShieldError(f"--seconds must be between 0 and audio.live.max_seconds ({live['max_seconds']}).")
        device: Any = args.device
        if isinstance(device, str) and device.isdigit():
            device = int(device)
        s.record("microphone_session_started", {"device": args.device or "default", "seconds": args.seconds})
        s.save()
        summary, findings = audio_live.run_live(args.seconds, s.cfg["audio"], device, STREAM_FACTORY)
        summary["window_ms"] = s.cfg["audio"]["window_ms"]
        s.record("microphone_session_ended", _audio_record(summary, findings) if "levels" in summary
                 else {"device": summary["device"], "findings": [f["kind"] for f in findings]})
        s.save()
    failed = any(f["kind"] in ("microphone_unavailable", "microphone_lost") for f in findings)
    code = EXIT_ERROR if failed else (EXIT_FINDINGS if actionable(findings) else EXIT_OK)
    if args.json:
        emit_json({"summary": summary, "findings": findings, "exit_code": code})
    elif "levels" in summary:
        emit_lines(_render_audio(summary, findings, "Summary recorded in the audit log."))
    else:
        emit_lines(["Microphone could not be opened."] + render_findings(findings))
    return code


# --------------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clearshield.py",
        description="ClearShield: local, defensive monitoring for Linux hosts you own. "
                    "It detects and records; it does not block or prevent anything.")
    parser.add_argument("--version", action="version", version=f"ClearShield {__version__}")
    parser.add_argument("--state-dir", default=None,
                        help="state directory (default: $CLEARSHIELD_STATE_DIR, /var/lib/clearshield "
                             "as root, otherwise ~/.local/state/clearshield)")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="print machine-readable JSON")
    common.add_argument("--state-dir", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p = sub.add_parser("init", parents=[common], help="create the state directory, key, and config")
    p.add_argument("--watch", action="append", default=[], metavar="PATH",
                   help="file to monitor (repeatable)")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("watch", parents=[common], help="list, add, or remove watched paths")
    p.add_argument("--add", action="append", default=[], metavar="PATH")
    p.add_argument("--remove", action="append", default=[], metavar="PATH")
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("baseline", parents=[common], help="approve the current state as the baseline")
    p.add_argument("--replace", action="store_true", help="review differences and replace an existing baseline")
    p.add_argument("--yes", action="store_true", help="approve --replace without an interactive prompt")
    p.set_defaults(func=cmd_baseline)

    p = sub.add_parser("scan", parents=[common], help="compare files, listeners, and auth logs with the baseline")
    p.add_argument("--no-integrity", action="store_true")
    p.add_argument("--no-listeners", action="store_true")
    p.add_argument("--no-auth", action="store_true")
    p.add_argument("--verbose", action="store_true", help="also show info-level findings")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("verify", parents=[common], help="verify the audit chain, state, and optional checkpoint")
    p.add_argument("--all", action="store_true", help="verify archived segments too")
    p.add_argument("--checkpoint", metavar="FILE", help="checkpoint exported earlier and stored off-host")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("checkpoint", parents=[common], help="export the current chain head for off-host storage")
    p.add_argument("--output", metavar="FILE")
    p.add_argument("--label", default=None, help="free-text label stored in the checkpoint")
    p.set_defaults(func=cmd_checkpoint)

    p = sub.add_parser("rotate", parents=[common], help="archive the audit log and start a new segment")
    p.add_argument("--new-key", action="store_true", help="also retire the HMAC key and generate a new one")
    p.add_argument("--reason", default="operator rotation")
    p.set_defaults(func=cmd_rotate)

    p = sub.add_parser("purge", parents=[common], help="delete archived audit segments (retention)")
    p.add_argument("--before-segment", type=int, required=True, metavar="N")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_purge)

    p = sub.add_parser("audio-wav", parents=[common], help="analyse digital levels in a WAV file")
    p.add_argument("--wav", required=True, metavar="FILE")
    p.add_argument("--window-ms", type=int)
    p.add_argument("--sustained-dbfs", type=float)
    p.add_argument("--sustained-seconds", type=float)
    p.add_argument("--no-record", action="store_true", help="do not write a summary to the audit log")
    p.set_defaults(func=cmd_audio_wav)

    p = sub.add_parser("audio-live", parents=[common],
                       help="opt-in: analyse live microphone levels in memory for N seconds")
    p.add_argument("--seconds", type=float, required=True)
    p.add_argument("--allow-microphone", action="store_true")
    p.add_argument("--device", default=None, help="input device name or index (default device if omitted)")
    p.set_defaults(func=cmd_audio_live)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.state_dir = os.path.abspath(args.state_dir) if args.state_dir else default_state_dir()
    try:
        return args.func(args)
    except ClearShieldError as exc:
        print(f"clearshield: error: {sanitize(exc, 2000)}", file=sys.stderr)
        return exc.exit_code
    except OSError as exc:
        if os.environ.get("CLEARSHIELD_DEBUG"):
            raise
        where = f" ({sanitize(exc.filename, 400)})" if exc.filename else ""
        print(f"clearshield: error: {exc.strerror or exc}{where}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("clearshield: interrupted", file=sys.stderr)
        return 130
