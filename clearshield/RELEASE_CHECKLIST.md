# ClearShield release checklist

## Decision (2026-11-13)

**Evaluation-ready for testing on hosts you own.** ClearShield CI passed on Python 3.10, 3.11, 3.12 and 3.13 on 2026-11-13 (pull request ClearGla88/ClearGlass-Inc.#28, head `0a770fd`), alongside every Baseline CI job. **Not production-ready.**

This is a clean-room `1.0.0.dev0`. It is not the original v1 code, and the results reported for that code (nine tests, one Linux smoke test) were never verified here and are not claimed.

## Evidence captured

Environment: Ubuntu 24.04.5 LTS container, kernel 6.18.44, x86-64 (little-endian), no IPv6, no journal files, no `sshd`, no audio hardware. pytest 9.1.1.

| Check | Command (from the repository root) | Result |
|---|---|---|
| Unit and integration, Python 3.11.18, root | `python3.11 -m pytest -q -p no:cacheprovider clearshield/tests` | 190 passed, 2 skipped: the real-permission test (root ignores permissions) and the live IPv6 test (no IPv6 in this container) |
| Same, Python 3.12.3, root | `python3.12 -m pytest …` | 190 passed, 2 skipped |
| Same, Python 3.13.18, root | `python3.13 -m pytest …` | 190 passed, 2 skipped |
| Same, Python 3.13.18, uid 65534 (`nobody`) | `setpriv --reuid=65534 --regid=65534 --clear-groups python -m pytest … clearshield/tests` | 191 passed, 1 skipped (live IPv6) |
| Whole repository suite (what Baseline CI runs), 3.13 | `python -m pytest -q` | 292 passed, 2 skipped (102 existing tests, all still passing, plus ClearShield's 192) |
| ClearShield CI on a GitHub-hosted Ubuntu 24.04.5 runner (kernel 7.0.0-1017-azure), unprivileged uid 1001, Python 3.10.22 | `.github/workflows/clearshield-ci.yml` | At `0a770fd`: 191 passed (all tests at that commit), smoke PASS with `tcp6 ok` and `/var/log/auth.log` read as `ok`, ruff pass, package installs. 3.11, 3.12 and 3.13 jobs also green. The live IPv6 test was added afterwards and runs in the same workflow |
| Linux smoke, root and uid 65534 | `python3 clearshield/tests/smoke/linux_smoke.py` | PASS for both. As `nobody`, attribution was denied for 76 processes and the listeners were still reported |
| Lint | `ruff check --select E9,F .` (ruff 0.16.9) | pass |
| Compile every tracked file, 3.11 and 3.13 | `git ls-files -z '*.py' \| xargs -0 python -m py_compile` | pass |
| Repository hygiene | `python3 tools/repo_hygiene.py` | 0 findings |
| Package install, Python 3.11 venv | `pip install ./clearshield && clearshield --version` | `ClearShield 1.0.0.dev0`, no dependencies installed |
| Tests catch real defects (fault injection) | Bugs injected one at a time: skipping the record-tag check, skipping the sequence check, decoding IPv4 big-endian, treating 8-bit audio as signed, skipping state authentication, removing the end anchor from the address match | Each made the suite fail (1–5 failures each). A no-op control passed |
| Python 3.10 | — | Not installed locally; verified only in CI (row above) |

## Not yet verified (before relying on these layers)

- [ ] Real OpenSSH log lines on each target distribution, including the `sshd-session` program name used by newer OpenSSH. Only synthetic lines have been parsed. The CI runner's `/var/log/auth.log` was read successfully as a non-root user, but it contained no `sshd` entries.
- [ ] A systemd journal that actually contains entries, read as an unprivileged member of `systemd-journal`/`adm`. Only simulated `journalctl` output has been tested.
- [ ] IPv6 listener decoding on a live kernel: `test_live_kernel_ipv6_listener_is_decoded` runs in ClearShield CI. Tick this once a CI run shows it passed rather than skipped (all ClearShield tests passing with none skipped on the unprivileged runner).
- [ ] A big-endian host.
- [ ] Live microphone hardware: opening, permission denial, unplugging mid-session. Only a simulated stream has been tested.
- [x] Python 3.10: 3.10.22 in CI, 2026-11-13.

## Manual deployment checks (per host, by a person)

- [ ] The host is in a known-good state before `baseline`. Critical files were compared with package checksums (`debsums -s` or `rpm -Va`, as applicable).
- [ ] `init` was run as the intended monitoring user; `ls -la <state-dir> <state-dir>/keys` shows 0700 directories and 0600 files.
- [ ] `keys/hmac.key` is backed up offline, and the backup has been tested by restoring it to a scratch copy and running `verify`.
- [ ] The watch list covers what matters (for example `/etc/passwd`, `/etc/group`, `/etc/sudoers`, `/etc/ssh/sshd_config`, `/etc/hosts`). Root-only files are readable by the monitoring user, or reported as `unreadable` and accepted.
- [ ] `scan` shows each auth source as `ok`. If it says `unavailable` or `permission_denied`, fix that before relying on SSH monitoring.
- [ ] The first `checkpoint` is copied off the host, and the procedure for doing it again is written down.
- [ ] `audio.live.enabled` is still false, unless microphone monitoring is authorized and the people affected have been told.
- [ ] No scheduler, service, firewall rule or persistent monitoring was installed (none is shipped; adding one is roadmap stage 3).

## Unresolved blockers for production

1. **[DECISION REQUIRED]** A private vulnerability-reporting channel (SECURITY.md).
2. **[LEGAL REVIEW]** The privacy notice, before monitoring any system other people use (PRIVACY.md).
3. Independent security review of the audit chain, the state handling and the parsers.
4. Real-host validation of every item under "Not yet verified".
5. Off-host evidence storage that doesn't depend on a person copying files (roadmap stage 1).

## Production roadmap

Effort figures are **estimates** for one engineer familiar with the code. They are not measurements.

| Stage | Problem addressed | Dependencies | Implementation sequence | Acceptance criteria | Operational risks | Rollback | Estimated effort |
|---|---|---|---|---|---|---|---|
| 1. Independently stored audit evidence | Local history is untrustworthy once the monitoring user or root is compromised; checkpoints depend on a person copying them | Current `checkpoint` command | Write each checkpoint to an append-only remote target over TLS (a remote syslog collector or a write-once bucket); alternatively use journald Forward Secure Sealing with the verification key kept off the host; add `verify --remote` | In a test VM, both a truncation and a full rollback are detected against the remote copy; one week of checkpoints arrive with no gaps | Remote target unavailable (must queue, not block scans); metadata leaving the host (update PRIVACY.md) | Disable export; the local chain is unaffected | 3–5 days |
| 2. Centralized event logging | Findings stay on one host | Stage 1 transport | Emit one JSON line per finding to syslog/journald; publish the event schema; add a schema-validation test | Findings reach the collector within 60 s; schema test passes; no secrets in events (test) | Personal data in transit and in the collector; alert fatigue | Remove the forwarder configuration | 2–3 days |
| 3. Optional service management, least privilege | Manual runs leave gaps | Stable exit codes (done); stages 1–2 recommended | Ship *disabled* systemd service and timer files: a dedicated user, `NoNewPrivileges=yes`, `ProtectSystem=strict`, `ReadWritePaths=` limited to the state directory, `PrivateTmp=yes`, `ProtectHome=yes`, a capability bounding set. The operator enables them. Check the directives against the target's systemd version | `systemd-analyze security` reviewed and recorded; scans run on schedule for 7 days; the service cannot write outside the state directory (test) | Over-restriction makes it fail silently (alert on a missed run); under-restriction | `systemctl disable --now`; delete the unit files | 2–3 days |
| 4. Integration with established endpoint detection and response | ClearShield is not EDR and should not grow into one | Stage 2 | Evaluate forwarding into tools already in use (for example Wazuh, osquery or Falco); choose by fit, don't build | Findings correlate in the chosen tool; a documented mapping from ClearShield kinds to that tool's rules | Duplicate alerts; another agent on the host | Stop forwarding | 3–5 days (evaluation) |
| 5. Controlled firewall integration | Detection only, no response | Stages 1–3; a human approval step; a decision on false-positive handling | Generate a proposed nftables rule as text for a person to review; validate with `nft -c`; apply only by hand, with a timed automatic revert; never apply automatically from log content | The proposal is correct in a VM; the timed revert restores the previous ruleset; nothing is applied without approval (test) | **Self-lockout**; blocking innocent addresses (log text is attacker-influenced, though address framing is defended and tested) | Timed revert; console access required before enabling | 3–5 days |

Firewall integration comes last on purpose. Every input it would act on is detection output, and detection is not proof.
