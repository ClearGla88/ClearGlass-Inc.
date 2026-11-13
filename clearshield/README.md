# ClearShield

Local, defensive monitoring for Linux hosts you own or are authorized to monitor. ClearShield **detects and records**. It does not block, prevent, quarantine, or remove anything, and it sends nothing off the host.

> **Status: `1.0.0.dev0`, unreleased, evaluation stage.** This is a clean-room implementation written on 2026-11-13 from the owner's ClearShield v1 specification. The original v1 source code, its nine tests, and its Linux smoke-test record were not available, so this package is **not** an audit of that code and does not carry over its reported results. What has and has not been verified is in [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md). Threat model and limits: [SECURITY.md](SECURITY.md). Data handling: [PRIVACY.md](PRIVACY.md).

## What it checks, and what it does not

| Layer | Checks | Does not |
|---|---|---|
| File integrity | SHA-256, type, mode, owner, group and inode of each watched path, compared with an approved baseline. Content changes are reported separately from missing, unreadable, and raced files. | Detect malware in general, watch whole directories, see changes made and reverted between two scans. |
| TCP listeners | New `LISTEN` sockets from `/proc/net/tcp` and `/proc/net/tcp6`, classified as loopback, a specific address, or all interfaces, with the owning process where permissions allow. | Inspect packets, monitor traffic, cover UDP, or prove that a port is reachable from the internet. |
| SSH authentication | `Failed …`, `Invalid user …` and `Accepted …` messages from OpenSSH, read from `/var/log/auth.log`, `/var/log/secure`, or the systemd journal. It counts failures per source address in a sliding window. | Confirm an intrusion, cover sudo/su/console logins, or block an address. |
| Audio | Peak and RMS in **dBFS**, clipping runs, and sustained high levels in WAV files. Live microphone input is optional and off by default. | Measure sound-pressure level (dB SPL), identify a source or direction, detect "acoustic weapons", or block sound. |
| Audit integrity | HMAC-SHA256 chained log, an authenticated state file, and checkpoints you can store off the host. | Make records tamper-proof, or protect history from anyone who holds the key (the monitoring user, or root). |

## Requirements and supported environments

- Linux with `/proc`. Python **3.10 or newer**. The core uses only the standard library.
- Verified on 2026-11-13: Ubuntu 24.04.5 LTS container, kernel 6.18.44, Python 3.11.18, 3.12.3 and 3.13.18, both as root and as an unprivileged user. Python 3.10 is the declared minimum, but it was not installed in that environment. It is tested only by the CI workflow `.github/workflows/clearshield-ci.yml`.
- **Not yet verified on real systems:** big-endian hosts; IPv6 listener tables on a live kernel (tested with fixture tables only); real `sshd` log output (tested with synthetic lines in the OpenSSH format); a journal containing entries (tested with simulated `journalctl` output); microphone hardware (tested with a simulated stream). Check these on your target hosts before relying on them. See RELEASE_CHECKLIST.md.
- Optional live audio: the `sounddevice` package and the system PortAudio library.

## Install

No installation is needed. Run it from this directory:

```bash
python3 clearshield.py --help
```

Or install it as a command (no third-party dependencies are pulled in):

```bash
python3 -m pip install ./clearshield
```

```bash
clearshield --help
```

## Quick start

These are the v1 commands. They keep their names and flags:

```bash
python3 clearshield.py init --watch /etc/hosts
```

```bash
python3 clearshield.py baseline
```

```bash
python3 clearshield.py scan
```

```bash
python3 clearshield.py verify
```

```bash
python3 clearshield.py audio-wav --wav sample.wav
```

Real output, captured on 2026-11-13 in the test container, after a line was added to a watched copy of `/etc/hosts` (exit status 1). The container has no journal files, so the authentication layer reports that it could not read anything; it does not report "no failures". The hidden `info` finding is the missing IPv6 table.

```
ClearShield scan 2026-11-13T20:50:40+00:00 (baseline bd2b7f621f0fefd7)
  integrity: 1 watched path(s)
  listeners: 3 TCP listener(s) [tcp4 ok, tcp6 unavailable]
  auth: journal unavailable: no system journal files, 0 event(s)
Findings: high 1, medium 1, info 1 (1 info hidden; --verbose shows them)
  [HIGH  ] integrity/content_changed  /tmp/cs-demo/hosts  sha256 d343af6b2baf... -> f98ffb1c7fc1...
  [MEDIUM] auth/auth_source_unavailable    no authentication source could be read; zero failures means nothing here
Detection only: ClearShield blocked nothing, changed nothing it watches, and uploaded nothing.
```

And `verify` on the same state (exit status 0):

```
ClearShield verify (/tmp/cs-demo/state)
  state file authentication        ok   authenticated
  active segment 1 (audit.jsonl)   ok   ok, 4 records
  log head matches state           ok   seq 3
Result: PASS
Tamper-evident, not tamper-proof: anyone holding the key can rewrite history, and removal of the newest records is caught only by an off-host checkpoint.
```

Every command accepts `--json` for machine-readable output.

## Command reference

| Command | Purpose | Compared with the v1 description |
|---|---|---|
| `init --watch PATH …` | Create the state directory (0700), a 32-byte HMAC key (0600), the config, and the first audit segment. | Kept. `--watch` can be repeated or omitted. Refuses to run twice. |
| `watch [--add PATH] [--remove PATH]` | List or change the watched paths. Changes are logged. | New. |
| `baseline [--replace --yes]` | Approve the current files and listeners as known-good. | Kept. **Changed behavior:** it no longer overwrites an existing baseline. Replacing one requires `--replace`, which shows the differences first, then confirmation (typed, or `--yes`). Scripts that re-run `baseline` must add `--replace --yes`. This is deliberate, so evidence can't be erased by re-baselining. |
| `scan [--no-integrity] [--no-listeners] [--no-auth] [--verbose]` | Compare the host with the baseline and record the result. | Kept. |
| `verify [--all] [--checkpoint FILE]` | Verify the audit chain, the state authentication, the head agreement and, optionally, an off-host checkpoint. Read-only. | Kept. `--all` also checks archived segments. |
| `checkpoint [--output FILE] [--label TEXT]` | Export the current chain head, to be stored off the host. | New. |
| `rotate [--new-key] [--reason TEXT]` | Archive the log segment. Optionally retire the key and generate a new one. | New. |
| `purge --before-segment N [--yes]` | Delete archived segments (retention). Their final tags stay in the log. | New. |
| `audio-wav --wav FILE [--window-ms] [--sustained-dbfs] [--sustained-seconds] [--no-record]` | Analyze digital levels in a WAV file. | Kept. Works without `init`: it uses the defaults and records nothing. |
| `audio-live --seconds N --allow-microphone [--device D]` | Live microphone analysis, in memory only. | New. Opt-in in two steps (see below). |

`--state-dir DIR` (before or after the command) overrides the state directory. The default is `$CLEARSHIELD_STATE_DIR`, then `/var/lib/clearshield` when running as root, otherwise `~/.local/state/clearshield`.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Completed. No findings above `info`. |
| 1 | Completed. Findings reported (`low`, `medium` or `high`). |
| 2 | Operational error: usage, configuration, permissions, unusable input, or the microphone was unavailable. |
| 3 | Integrity failure: audit chain, state authentication, head mismatch, or checkpoint mismatch. |

A finding is a reason to look, not a verdict. Severity reflects how much attention it needs, not proof of compromise.

## What each layer measures

**File integrity.** `lstat` comes first. A symlink is recorded with its target and never followed, so to watch content, watch the target path itself. Only regular files are hashed. FIFOs, devices and directories are recorded by type and never opened. A file is opened with `O_NOFOLLOW | O_NONBLOCK`, and its identity is rechecked with `fstat`. A path swapped between the check and the read is reported as `raced`. Results include `content_changed`, `metadata_changed` (mode, uid, gid), `replaced` (same content, new inode; `info`), `missing`, `appeared`, `type_changed`, `symlink_target_changed`, `unreadable`, `collection_error`, `too_large`, `not_in_baseline`, and `removed_from_watch`.

**TCP listeners.** The kernel prints addresses in native byte order, so on a little-endian host `127.0.0.1` appears as `0100007F`. ClearShield decodes this, normalizes IPv4-mapped IPv6 addresses (Python versions disagree on how to print them), and identifies each listener as `tcp4/ADDR:PORT` or `tcp6/[ADDR]:PORT`. New listeners are graded by scope: all interfaces `high`, a specific address `medium`, loopback `low`. Attribution reads `/proc/<pid>/fd`. Without privilege, other users' processes are reported as `unattributed`, but the listener itself is still reported, along with its owning uid. An IPv6 `::` listener may also accept IPv4 unless the socket is IPv6-only. Either way, being on all interfaces does not mean a port is reachable through your firewall.

**SSH authentication.** The username in these messages is chosen by the remote client. The parser anchors on the *final* `from <ip> port <n>`, so a username like `x from 10.0.0.5 port 22` cannot shift blame to 10.0.0.5. Output is escaped so log text can't drive your terminal. Failures are counted per address within `window_seconds`. Reaching `failure_threshold` gives `repeated_auth_failures` (medium). A successful login from an address with recent failures gives `login_success_after_failures` (high), but that is still not proof. If no source can be read, the scan reports `auth_source_unavailable` instead of "zero failures".

**Audio.** The WAV parser is ClearShield's own, so supported formats don't depend on the Python version. It handles integer PCM at 8 (unsigned), 16, 24 and 32 bits; IEEE float at 32 and 64 bits; and WAVE_FORMAT_EXTENSIBLE wrapping either. It accepts 1–32 channels. It rejects RF64 and compressed encodings, with the reason. Files are read one window at a time. A header that claims more data than the file holds is flagged as `audio_truncated`, and the header is never trusted for how much to read. Levels are in **dBFS**: RMS is referenced so that a full-scale sine reads −3.01 dBFS. Silence is reported as `null`, never as −∞. A clipping run is `clip_run_samples` or more consecutive full-scale samples on one channel, so isolated peaks don't count. A sustained high level means windows at or above `sustained_dbfs` for at least `sustained_seconds`.

## Configuration

`<state-dir>/config.json` is created by `init`. [`clearshield.example.json`](clearshield.example.json) shows every key at its default; a test keeps the two identical. Unknown keys are rejected. The SHA-256 of the config is stored with each baseline, and `scan` reports `config_changed_since_baseline` when it differs.

| Key | Default | Meaning |
|---|---|---|
| `integrity.max_file_bytes` | 64 MiB | Larger files are reported as `too_large`, not hashed |
| `auth.enabled` | true | Read authentication sources during `scan` |
| `auth.sources` | `["auto"]` | `auto` (the first of `/var/log/auth.log`, `/var/log/secure`, else the journal), `journal`, or `file:/path` |
| `auth.failure_threshold` | 10 | Failures per address within the window that raise an alert |
| `auth.window_seconds` | 600 | Sliding window |
| `auth.initial_lookback_seconds` | 3600 | How far back the first scan reads |
| `auth.max_bytes_per_scan` | 50 MiB | Read cap per source per scan; exceeding it is reported |
| `auth.journal_timeout_seconds` | 30 | `journalctl` is killed after this |
| `auth.record_invalid_usernames` | false | Store sample usernames tried against non-existent accounts. Off because people type passwords into the username prompt |
| `auth.max_tracked_sources` | 10000 | Bound on addresses remembered between scans |
| `listeners.enabled` | true | Inventory TCP listeners |
| `listeners.attribute_processes` | true | Map sockets to processes where permitted |
| `listeners.attribution_time_budget_seconds` | 5.0 | Stop attribution after this |
| `listeners.allow` | `[]` | Never report these, e.g. `"127.0.0.1:631"`, `"[::1]:631"`, `"*:22"` |
| `audio.window_ms` | 1000 | Analysis window |
| `audio.sustained_dbfs` | −12.0 | RMS level counted as high |
| `audio.sustained_seconds` | 10.0 | Minimum duration of a sustained segment |
| `audio.clip_run_samples` | 3 | Consecutive full-scale samples that count as clipping |
| `audio.max_bytes` | 2 GiB | Larger WAV files are rejected |
| `audio.max_seconds` | 7200 | Analysis stops here; the result is marked `partial` |
| `audio.live.enabled` | **false** | First of two opt-in steps for the microphone |
| `audio.live.max_seconds` | 600 | Longest live session |
| `audio.live.sample_rate` / `channels` | 48000 / 1 | Live capture format |
| `audit.max_log_bytes` | 64 MiB | `scan` suggests `rotate` above this |
| `audit.max_findings_per_record` | 200 | Cap on the findings stored per scan record |

## State directory

```
<state-dir>/            0700, owned by the monitoring user
  keys/hmac.key         0600  32 random bytes; never printed or logged
  keys/retired/*.key    0600  keys retired by 'rotate --new-key', kept to verify old segments
  config.json           0600  operator settings
  state.json            0600  watch list, baseline, auth cursors, chain head (HMAC-authenticated)
  audit.jsonl           0600  active audit segment (HMAC-chained JSON lines)
  archive/audit-NNNNNN.jsonl  rotated segments
  .lock                 prevents two commands from interleaving
```

ClearShield refuses to run if the directory or any of these files can be read by group or other users, is owned by another user, or is a symlink.

## Off-host checkpoints

The chain on this host can't prove its own newest records still exist, and anyone holding the key can rebuild it. A checkpoint copied elsewhere is what catches truncation, rollback, and rewriting:

```bash
python3 clearshield.py checkpoint --output /tmp/clearshield-checkpoint.json
```

Copy that file **off this host**: another machine, write-once storage, or a printout. Later:

```bash
python3 clearshield.py verify --checkpoint /path/to/copied/checkpoint.json
```

The test suite shows a full rollback passing local `verify` and failing against a checkpoint taken earlier.

## Retention

`rotate` closes the current segment and moves it to `archive/`. `purge --before-segment N` deletes archived segments older than N, after logging their final tags, so that `verify --all` can tell an approved purge from a deletion. To remove everything ClearShield has collected, delete the state directory. See PRIVACY.md.

## Optional live audio

The microphone is opened only by `audio-live`, and only when **both** of these are true:

1. `audio.live.enabled` is set to `true` in config.json, and
2. `--allow-microphone` is passed on the command line.

The session length is bounded by `--seconds` and `audio.live.max_seconds`. Samples are analyzed in memory and discarded, and only the summary is logged. A session's start and end are both recorded in the audit log. A session in which every sample is zero is reported as `no_signal_path_suspected`, never as "quiet". The adapter uses `sounddevice`'s raw stream, so NumPy is not needed. Install `pip install 'sounddevice>=0.5'` and the distribution's PortAudio library. This path has been tested only with a simulated stream.

## Running the tests

| Layer | Command | Notes |
|---|---|---|
| Unit and integration | `python3 -m pytest -q clearshield/tests` (from the repository root), or `python3 -m pytest -q` here | Synthetic fixtures and temporary directories only. One test is skipped as root, because root ignores file permissions; run the suite unprivileged as well. |
| Linux smoke | `python3 tests/smoke/linux_smoke.py` | Real `/etc/hosts`, the real listener table and real auth sources, using a throwaway state directory. Run it as your monitoring user and as root. |
| Manual deployment checks | RELEASE_CHECKLIST.md | Run by a person on each target host. |

## Troubleshooting

| Message | Cause and fix |
|---|---|
| `… does not exist. Run 'clearshield.py init' first.` | Wrong `--state-dir`, or not initialized yet. |
| `… has mode 0755; group/other access is not allowed` | Run `chmod 700` on the directory, or `chmod 600` on the file. |
| `a baseline already exists … Use 'baseline --replace'` | Intended. Review with `baseline --replace`, then confirm. |
| `audit log ends at seq X but state records seq Y` (exit 3) | The log and state disagree: truncation, rollback, or tampering. Run `verify` and compare with your off-host checkpoint before doing anything else. Don't "fix" it by editing files. |
| `ends with an incomplete line` (exit 3) | An append was interrupted (power loss, full disk) or the file was altered. Preserve a copy of the state directory first. If you are certain it was an interrupted write, remove only the partial final line (`truncate`), then run `verify`. That removal itself can't be proven harmless. |
| `HMAC key not found` (exit 2) | Restore `keys/hmac.key` from your offline backup. Without it, existing records can't be verified. |
| `auth_source_unavailable` | No readable log or journal. As an unprivileged user, join the `adm` or `systemd-journal` group (check which one your distribution uses), or set `auth.sources`. |
| Listeners show `unattributed` | Process attribution needs privilege over other users' processes. The listener and its uid are still reported. |
| `live microphone analysis is disabled` | Intended default. See "Optional live audio". |

## Claims ClearShield does not make

Detection is not prevention. Suspicious activity is not proof of compromise. File hashing is not malware detection. A listener is not proof of internet exposure. Tamper-evident is not tamper-proof. Digital amplitude (dBFS) is not calibrated sound exposure (dB SPL). An audio anomaly does not establish intent or identify a source. ClearShield has no certification, approval or endorsement from any agency, and claims none.

## License

Covered by the repository [LICENSE](../LICENSE) (ClearGlass Inc. proprietary).
