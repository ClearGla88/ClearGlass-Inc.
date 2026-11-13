# ClearShield privacy notice

ClearShield runs on your host and sends nothing anywhere. It has no network code, no telemetry, and no upload function. This document lists exactly what it stores, where, who can read it, and how to delete it.

## What is stored

Everything lives in the state directory (default `~/.local/state/clearshield`, or `/var/lib/clearshield` as root). The directory is mode 0700 and every file in it is 0600, owned by the monitoring user.

| Data | Example | File | Why | Retention |
|---|---|---|---|---|
| Watched paths and their metadata | `/etc/hosts`, SHA-256, size, mode, uid, gid, inode | `state.json`, `audit.jsonl` | Integrity comparison | Until the baseline is replaced or the state directory is deleted |
| Symlink targets of watched symlinks | `/run/systemd/resolve/stub-resolv.conf` | same | Detect retargeting | same |
| TCP listener identities | `tcp4/0.0.0.0:22`, uid, PID, executable path, process name (up to 64 characters) | same | Detect new listeners | Per scan record |
| Failed SSH logins: source IP address, timestamps, counts | `203.0.113.9`, 10 failures in 600 s | same | Threshold alerts | Timestamps in `state.json` are pruned after one window; alerts stay in the audit log until purged |
| Names of **existing local accounts** targeted | `root` | `audit.jsonl` | Show which real accounts were attacked | Until purged |
| Names tried against **non-existent** accounts | — | **not stored by default** | People type passwords into the username prompt; such a name can be a credential | Only if `auth.record_invalid_usernames` is set to true; then up to 5 escaped samples per alert |
| Read positions in auth sources | inode and offset, or a journal cursor | `state.json` | Avoid re-reading and double-counting | Overwritten every scan |
| WAV analysis summary | path, SHA-256 of the file, format, peak/RMS dBFS, clipping counts, time ranges of sustained levels | `audit.jsonl` | Record of the analysis | Until purged |
| Microphone session summary | device name, duration, the same level aggregates, start and end records | `audit.jsonl` | Transparency about every time the microphone was opened | Until purged |
| Configuration | thresholds | `config.json` | Operator settings | Until edited |
| HMAC key | 32 random bytes | `keys/` | Authenticate records | Until deleted |

## What is never collected

- **Raw audio.** WAV files are read, never copied. Microphone samples are analyzed one window at a time in memory and discarded. Tests check that no file is created during analysis.
- File contents. Only hashes and metadata are kept.
- Passwords or authentication secrets, and attempted usernames for non-existent accounts (unless you opt in).
- Full log lines, message bodies, keystrokes, screen contents, location, or any data from devices or accounts other than this host's.

## Who can read it

The monitoring user and root. ClearShield refuses to run if the state directory or its files are readable by group or other users. Anyone you give a JSON report, checkpoint or copy of the audit log to can read what is in it. A checkpoint contains only a segment number, sequence number, tag, key id, time and an optional label.

## Microphone

The microphone is off unless **both** `audio.live.enabled` is true in config.json **and** `--allow-microphone` is given. A session lasts only as long as `--seconds` specifies (at most `audio.live.max_seconds`). Each session writes a start record and an end record. Recording other people's conversations raises legal questions that a level meter does not avoid. Use it only where you are authorized to, and inform the people affected. **[LEGAL REVIEW]**

## Deleting data

| To delete | Do this |
|---|---|
| Old audit history | `python3 clearshield.py rotate`, then `python3 clearshield.py purge --before-segment N`. The purge itself is logged, with the final tag of each deleted segment, so verification still works |
| Everything | Delete the state directory: `rm -r <state-dir>`. Delete any checkpoints you copied elsewhere |
| A specific record inside the active segment | Not possible without breaking the chain. Rotate, then purge the segment that contains it |

## Legal considerations

IP addresses and account names can be personal information. Whether and how privacy law applies depends on who runs ClearShield, on whose systems, and for what purpose. This document does not decide that. **[LEGAL REVIEW]** Obtain advice before monitoring systems that other people use, and tell those people that monitoring is in place.
