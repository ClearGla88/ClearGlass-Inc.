# Security

## Scope and intent

This is a defensive tool for assets ClearGlass Inc. owns or is authorized to protect. It deceives, records, correlates, and proposes containment inside that boundary. It contains no capability to scan, probe, exploit or retaliate against any other system, and changes to add one will not be accepted.

## What it does not do

- It does not isolate anything real. The only adapter is a mock that writes to its own SQLite file.
- It does not prevent attacks. Decoys only see what touches them.
- It does not identify people. An IP address is an observation, and the decoys cannot see past NAT, proxies or VPNs.
- The honeyfile watcher cannot say which process or user opened a file. Without inotify (outside Linux) it cannot see reads at all, and it says so in `capabilities()` and in every event.
- No model reads or acts on anything. `assist.py` is deterministic text over stored records.

## Evidence limits

Each artifact is the exact signed request body, stored with its SHA-256, size, collector, and a custody record. Manifests hash the artifact list, and the audit log is a SHA-256 hash chain protected by append-only triggers.

**Hashes do not, by themselves, establish an immutable chain of custody.** They show that content has not changed since it was hashed. Someone with write access to the database file can drop the triggers and rewrite the chain consistently from the start. The defence is to copy the audit `head` hash off-host regularly (see the runbook), keep backups, and restrict who can reach the control host. Purged evidence leaves its hash and a `purged` custody record, so any gap is explained.

Raw artifacts hold what the sensor sent. Sensors are built to send metadata, hashes and fingerprints, not bodies or credentials, and the API is the only reader. Treat the database as sensitive.

## Secrets

Sensor HMAC keys and API tokens come from 0600 files (`init-secrets`) or environment variables, never from the repository. Configuration stores token references or SHA-256 hashes only. A missing, short or shared secret stops startup. The worker loads no sensor key and no token. Each sensor process holds only its own key.

## Reporting

Report a suspected vulnerability privately to the repository owner, not in a public issue. Include the commit, the steps, and what you expected. Do not test against systems you are not authorized to test.
