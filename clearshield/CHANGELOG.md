# Changelog

Versions follow [PEP 440](https://peps.python.org/pep-0440/). Dates are UTC.

## 1.0.0.dev1 — 2026-11-19 (unreleased)

Changes from the 2026-11-19 audit ([AUDIT-2026-11-19.md](AUDIT-2026-11-19.md)). Each fix has a regression test that fails when the fix is reverted.

### Security

- **Retired keys were accepted everywhere.** After `rotate --new-key`, anyone holding the old key could do two things. They could sign `state.json`, for example a baseline with a changed file's new hash, which made `scan` report nothing. And they could append records to the active segment, or rebuild later segments, and `verify --all` still passed. State must now carry the active key. A segment uses one key. Key changes between segments must follow a recorded `new_key` rotation. A retired key never signs a later segment, and the active segment must use the active key.
- `purge` deleted segments that failed verification, destroying the evidence of tampering. It now refuses unless the whole chain verifies.

### Fixed

- `rotate --new-key` could crash between retiring the old key and writing the new one, leaving no active key. The new key is now written first (`keys/hmac.key.next`), and every crash point is recovered by the next writing command. A rotation interrupted before the key swap now still swaps the key.
- SSH failures written between the previous scan and a log rotation were silently lost. They are now read from `<log>.1` when its inode matches the cursor. Rotations that can't be followed, including `copytruncate`, are reported as `auth_rotation_gap`.

### Added

- `listener_owner_changed` (medium): a different executable now holds an approved port. The baseline gains a `listener_owners` map. Baselines without it, and unattributed listeners, never trigger the finding.
- `no_audio_data` (low): a WAV file whose data chunk has no complete frame.
- Purge records now carry each segment's key id and rotation flag, so `verify --all` checks key succession across purged segments.

### Compatibility

- State and audit formats are unchanged. A `1.0.0.dev0` state directory loads, unless it was already signed with a retired key, which now fails closed (exit 3).
- Scripts that rely on `purge` succeeding over a broken chain will now get exit 3.

## 1.0.0.dev0 — 2026-11-13 (unreleased)

A clean-room implementation of the ClearShield v1 specification. The original v1 source, tests and smoke-test record were not available, so nothing here is derived from them, and their reported results ("nine tests passing", "Linux smoke test passed") do not apply to this code.

### Added

- `init`, `baseline`, `scan`, `verify`, `audio-wav`, with the command names and flags from the v1 description.
- `watch`, `checkpoint`, `rotate`, `purge`, `audio-live`, and `--json` on every command.
- File integrity: SHA-256 plus type, mode, uid, gid and inode. Symlinks are recorded, never followed; FIFOs and devices are never opened; paths swapped mid-read are reported as `raced`.
- TCP listener inventory from `/proc/net/tcp{,6}`, decoded in native byte order and graded by scope, with time-budgeted process attribution and `unattributed` reporting.
- SSH authentication monitoring from log files or the journal: end-anchored address parsing, sliding-window thresholds, cursors, rotation detection, and alerts for a success after failures.
- WAV analysis with a dedicated bounded RIFF parser (PCM 8/16/24/32-bit, float 32/64-bit, WAVE_FORMAT_EXTENSIBLE), dBFS levels, clipping runs and sustained-level segments.
- Opt-in live microphone analysis (two-step consent, in memory, sessions logged).
- An HMAC-SHA256 chained audit log, HMAC-authenticated state, key rotation, segment archive and purge, and off-host checkpoints.
- The README, SECURITY.md, PRIVACY.md, a sample configuration, and the release checklist.
- 192 tests at that version (unit and integration), a Linux smoke script, and a CI workflow for Python 3.10–3.13.

### Fixed during development (found by testing, before any release)

- A file appearing at a path the baseline recorded as missing crashed `scan` (`TypeError`: keyword collision). Found by `test_still_missing_is_quiet_and_appearance_is_reported`.
- With no journal files, the journal source reported `ok, 0 events`: `journalctl --output=json` exits 0 with empty stderr. It now checks the journal files directly and reports `unavailable` or `permission_denied`. Found in the first end-to-end run.
- Listener identities for IPv4-mapped IPv6 addresses depended on the Python version (3.12.3 prints `::ffff:7f00:1`; 3.11.18 and 3.13.18 print `::ffff:127.0.0.1`), so upgrading Python would have produced false listener findings. The format is now normalized. Found by running the suite on three interpreters.
- The `journalctl` timeout was not enforced while a silent child blocked a read; reads now go through `select`. Found in review, covered by `test_bounded_runner_enforces_timeout_on_silent_process`.
- A missing PortAudio library (which makes `import sounddevice` raise `OSError` on Linux) gave a device error instead of install guidance. Found by reading the sounddevice 0.5.6 source.
