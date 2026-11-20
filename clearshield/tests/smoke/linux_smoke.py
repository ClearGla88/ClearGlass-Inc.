#!/usr/bin/env python3
"""Linux smoke test against the real host, using a throwaway state directory.

Reads /etc/hosts, the kernel listener tables, and whatever authentication
sources exist. Writes only inside a new temporary directory, which it deletes
unless --keep is given. Opens no microphone, changes no system setting, and
makes no network connection.

    python3 tests/smoke/linux_smoke.py            # as your normal user
    sudo python3 tests/smoke/linux_smoke.py       # as root, for comparison

Exit status 0 means every step behaved as expected; the printed report is the
evidence to keep with a release.
"""

from __future__ import annotations

import json
import math
import os
import platform
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(os.path.dirname(HERE)), "clearshield.py")


def run(state_dir: str, *args: str) -> subprocess.CompletedProcess:
    env = {"PATH": "/usr/bin:/bin", "HOME": state_dir, "CLEARSHIELD_STATE_DIR": os.path.join(state_dir, "state")}
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, env=env, timeout=120)


def os_release() -> str:
    try:
        with open("/etc/os-release") as fh:
            for line in fh:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "unknown"


def write_tone(path: str) -> None:
    rate, frames = 8000, 8000 * 12
    data = b"".join(struct.pack("<h", int(16000 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(frames))
    fmt = struct.pack("<HHIIHH", 1, 1, rate, rate * 2, 2, 16)
    body = b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + b"data" + struct.pack("<I", len(data)) + data
    with open(path, "wb") as fh:
        fh.write(b"RIFF" + struct.pack("<I", len(body)) + body)


def main() -> int:
    keep = "--keep" in sys.argv
    work = tempfile.mkdtemp(prefix="clearshield-smoke-")
    failures: list[str] = []
    print(f"host: {os_release()}; kernel {platform.release()}; Python {platform.python_version()}; "
          f"euid {os.geteuid()}")

    def step(name: str, result: subprocess.CompletedProcess, expect: tuple[int, ...]) -> dict | None:
        ok = result.returncode in expect
        print(f"[{'ok' if ok else 'FAIL'}] {name}: exit {result.returncode} (expected {expect})")
        if not ok:
            failures.append(name)
            print("    stderr:", result.stderr.strip()[:500])
        try:
            return json.loads(result.stdout) if result.stdout.strip().startswith("{") else None
        except ValueError:
            return None

    try:
        step("init --watch /etc/hosts", run(work, "init", "--watch", "/etc/hosts"), (0,))
        step("baseline", run(work, "baseline"), (0,))
        scan = step("scan (unchanged host)", run(work, "scan", "--json"), (0, 1))
        if scan:
            layers = scan["layers"]
            print(f"    listeners: {layers['listeners']['count']} TCP, sources {layers['listeners']['sources']}, "
                  f"attribution pids_denied={layers['listeners']['attribution'].get('pids_denied')}")
            for src in layers["auth"]["sources"]:
                print(f"    auth source {src['source']}: {src['status']}, {src['events']} event(s)")
            for f in scan["findings"]:
                if f["severity"] != "info":
                    print(f"    finding: {f['severity']} {f['layer']}/{f['kind']}")
        wav = os.path.join(work, "tone.wav")
        write_tone(wav)
        audio = step("audio-wav (12 s tone at -9 dBFS RMS)", run(work, "audio-wav", "--wav", wav, "--json"), (1,))
        if audio:
            lv = audio["summary"]["levels"]
            print(f"    peak {lv['peak_dbfs']} dBFS, RMS {lv['rms_dbfs']} dBFS, findings "
                  f"{[f['kind'] for f in audio['findings']]}")
        cp = os.path.join(work, "checkpoint.json")
        step("checkpoint", run(work, "checkpoint", "--output", cp), (0,))
        step("verify --checkpoint", run(work, "verify", "--checkpoint", cp), (0,))
        step("audio-live refused by default", run(work, "audio-live", "--seconds", "1", "--allow-microphone"), (2,))
        modes = {name: format(os.stat(os.path.join(work, "state", name)).st_mode & 0o777, "03o")
                 for name in ("keys/hmac.key", "state.json", "audit.jsonl", "config.json")}
        print(f"    file modes: {modes}")
        if any(m != "600" for m in modes.values()):
            failures.append("file modes")
    finally:
        if keep:
            print(f"kept: {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
    print("RESULT:", "PASS" if not failures else f"FAIL ({', '.join(failures)})")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
