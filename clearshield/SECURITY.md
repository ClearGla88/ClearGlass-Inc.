# ClearShield security model

ClearShield is a detection and record-keeping tool. This document says what it protects, against whom, where the protection stops, and how to report a vulnerability. Statements here are backed by tests in `tests/`; where a statement rests on something not tested, it says so.

## Reporting a vulnerability

Don't open a public issue: this repository is public. Report privately to the repository owner. **[DECISION REQUIRED]** The owner needs to choose and publish a private reporting channel (for example, GitHub private vulnerability reporting for this repository, or a dedicated address). None is configured or verified at the time of writing.

## Assets and objectives

| Asset | Objective |
|---|---|
| Watched files | Detect changes relative to an approved baseline |
| Baseline and watch list | Authentic: any change needs the key and is logged |
| HMAC key (`keys/hmac.key`) | Confidential, readable only by the monitoring user |
| Audit log and state | Tamper-evident: modification, reordering, insertion and replay are detectable without the key; truncation and rollback are detectable against an off-host checkpoint |
| Host availability | ClearShield must not hang, exhaust memory, or fill the disk without saying so |
| People's privacy | No raw audio, no file contents, no attempted passwords; see PRIVACY.md |

## Trust boundaries

| Input | Trust | Handling |
|---|---|---|
| Auth log and journal text | **Untrusted**: remote clients choose usernames | Address taken from the final `from <ip> port <n>` anchored at end of message and validated; output escaped; per-line and per-scan byte caps |
| WAV files | **Untrusted** | Own bounded parser; header sizes never drive reads or allocation; size and duration caps |
| `/proc` | Trusted only until root is compromised | A rootkit can hide sockets and files |
| `journalctl` output | Semi-trusted | Run without a shell, minimal environment, hard timeout enforced with `select`, byte cap |
| State directory and key | Trusted only if 0700/0600, owned by the monitoring user, not symlinks | Checked on every command; fails closed |
| Operator commands | Trusted | Baseline replacement, watch changes, rotation, purge and microphone sessions are all logged |

## Required permissions

| Capability | Typically needs | Without it |
|---|---|---|
| Hash `/etc/hosts` and similar | Any user | — |
| Hash `/etc/shadow`, root-only configs | root | Reported as `unreadable`, never as changed |
| Read `/var/log/auth.log` | root or the `adm` group on Debian/Ubuntu (verify on your distribution) | `auth_source_unavailable` |
| Read the system journal | root or `systemd-journal`/`adm` (verify on your distribution) | `auth_source_unavailable` (permission_denied) |
| Listener inventory | Any user | — |
| Process attribution for other users' sockets | root | `unattributed`; verified as `nobody` (76 processes denied in the smoke test) |
| Microphone | Audio-device access, plus both opt-in steps | `microphone_unavailable` |

Run as the least-privileged user that can read what you need to watch. ClearShield never needs setuid and must not be installed setuid.

## Deployment environments

- **Intended:** a single Linux host you own, with commands run by hand or by a scheduler you configure.
- **Not intended:** fleet management, multi-tenant hosts where other users must not see the monitoring results, or containers expected to watch their host. Inside a container, `/proc/net/tcp` shows the container's network namespace, not the host's.

## Attacker capabilities and what survives

| Attacker | Can do | What ClearShield still provides |
|---|---|---|
| Remote, no shell | Guess passwords; put arbitrary text in usernames | Threshold alerts; cannot redirect blame to another address (tested) |
| Local user who is not the monitoring user | Change their own files; open listeners on high ports | Detects changes to watched files they can write and new listeners. Cannot read the key (0600), so cannot forge records or state |
| **Holds the monitoring user's privileges** | Read the key; rewrite the log, state, baseline and config | **Nothing on this host is trustworthy from that moment.** Records already exported in a checkpoint stay verifiable: rewriting history before the checkpoint is detected (tested) |
| **Root** | Everything above; hide processes, sockets and files from `/proc`; replace the Python interpreter or ClearShield itself | **Nothing local.** Only evidence already off the host, written before the compromise |

A locally stored HMAC key and log cannot establish trustworthy history after the monitoring user or root is compromised. Independently stored checkpoints, or remote evidence storage (see the roadmap in RELEASE_CHECKLIST.md), are required for that.

## Threat analysis

| Threat | Control | Residual risk |
|---|---|---|
| Unauthorized change to a watched file | SHA-256 plus metadata against the approved baseline | Changes made and reverted between scans are missed; anything outside the watch list is not seen |
| Repeated failed authentication | Per-address sliding window, configurable | Slow or distributed guessing below the threshold; non-SSH services are not covered |
| Unexpected listener | Identity diff against the baseline and allowlist, graded by scope | Listeners that open and close between scans; root can hide them |
| Audit record modified | HMAC tag over every field | None without the key |
| Record deleted, inserted, replayed, reordered | Sequence number and previous tag inside the MAC | None without the key |
| **Newest records truncated** | State records the chain head; off-host checkpoint | **The remaining prefix verifies on its own.** Detected against state (unless state is also rolled back) and against a checkpoint |
| **State rollback (old log and state restored together)** | Off-host checkpoint only | **Undetectable locally** (demonstrated by `test_full_rollback_passes_locally_but_fails_against_offhost_checkpoint`) |
| Baseline poisoning | Baseline requires an explicit command; replacement shows a diff, needs confirmation, is logged, and keeps the previous baseline | A baseline taken on an already-compromised host is wrong from the start. Compare critical files with package-manager checksums (for example `debsums` or `rpm -V`) before approving |
| Local secret exposure | Key 0600 in a 0700 directory; refused if looser; never printed or logged (tested) | The monitoring user and root can read it |
| Symlink substitution | `lstat` first; open with `O_NOFOLLOW`; `fstat` identity must match | `O_NOFOLLOW` covers only the last path component. A symlink swapped into a parent directory is followed |
| File-access race | Identity and size/mtime rechecked after reading; mismatches reported as `raced` | Polling is not race-free; a change and revert inside one read can still be missed |
| Malformed, oversized, unsupported WAV | Own parser, explicit rejection with reasons, caps on bytes and seconds | Analysis time grows with file length (pure Python), bounded by `audio.max_seconds` |
| Microphone loss, permission denial, device change | `microphone_unavailable` and `microphone_lost` events; an all-zero session is flagged | Device changes mid-session are seen only as errors or silence |
| Resource exhaustion | Byte caps on files, logs, journal output and lines; time budgets on attribution and `journalctl`; bounded memory of tracked addresses | — |
| Unbounded log growth | `audit.max_log_bytes` warning; `rotate` and `purge` | Nothing rotates automatically |
| Concurrent commands | Exclusive lock on the state directory | Processes that ignore the lock |
| Interrupted writes | State via temp file, fsync and rename; the log is one record ahead at most and reconciled; an interrupted rotation is completed | A partially written final log line needs a person to decide (README, troubleshooting) |

## HMAC tags are not digital signatures

The audit log uses HMAC-SHA256: a tag computed with a secret key shared between whoever writes and whoever verifies. **Anyone who can verify a tag can also create one.** A public-key signature (for example Ed25519) separates the two: the verifier holds only a public key and cannot forge. That helps when a third party must check records. It does not help against an attacker on this host, because the signing key would be stored on the same host. Neither scheme detects deleted newest records by itself.

## Key management

| Topic | Policy |
|---|---|
| Generation | `secrets.token_bytes(32)` at `init`, written with `O_CREAT \| O_EXCL`, mode 0600 |
| Storage | `keys/hmac.key` in the 0700 state directory. Commands refuse to run if it is group/other-readable, owned by someone else, a symlink, or not 32 bytes |
| Identification | Records carry a key id: the first 16 hex digits of HMAC(key, constant). It does not reveal the key |
| Backup | **Back the key up offline at `init`** (removable media kept elsewhere). Without it, existing records can never be verified |
| Rotation | `rotate --new-key` closes the segment with the old key, moves the old key to `keys/retired/<kid>.key`, and starts the next segment with a new key. `verify --all` uses both |
| Suspected compromise | Rotate the key, export a checkpoint immediately, and treat records written between the compromise and the rotation as untrusted |
| Loss | Old segments can't be verified. Re-initialize in a new state directory and keep the old one read-only as evidence |
| Never | Print, log, transmit, or commit the key. The repository is public |

Forward-secure logging would evolve the key with every segment and erase the old one, so a later compromise could not forge earlier segments. ClearShield does not do this. Where journald is available, its Forward Secure Sealing (`journalctl --setup-keys`, `--verify`) is an existing implementation of the idea. Its options were confirmed in `journalctl --help` (systemd 255), but it has not been tested with ClearShield.

## Explicit non-goals

Prevention or blocking; firewall changes; malware scanning; packet capture or traffic analysis; monitoring people, devices or accounts you are not authorized to monitor; identifying the source of a sound; measuring sound-pressure level; collecting raw audio; remote reporting (not implemented).

## Known limitations

- Periodic scans, not continuous monitoring. Nothing runs between scans.
- Only SSH authentication messages in the OpenSSH format are parsed, and they were tested with synthetic lines, not a live `sshd`.
- IPv6 parsing is tested with fixture tables and with one live `[::1]` listener in CI. No other IPv6 configuration (global addresses, IPv4-mapped sockets on a live kernel) has been tested.
- Big-endian hosts are untested.
- The live microphone path was tested with a simulated stream only.
- A dedicated clean-room implementation has not had an independent security review.
