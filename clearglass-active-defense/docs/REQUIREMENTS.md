# Requirements register

Verified against this tree on 2026-11-19. "Tested" names the test that proves the behaviour against synthetic data.

## Unresolved

| ID | Requirement | Status |
|---|---|---|
| REQ-00 | "CA ART" | **[DECISION REQUIRED] Undefined.** The brief names it without a definition. Nothing has been built for it and no expansion has been guessed. The owner needs to say what it means, what it must do, and how it would be tested. |

## Assumptions

| ID | Assumption | Consequence if wrong |
|---|---|---|
| A-01 | Every asset in `config/assets.example.yaml` is synthetic. A real deployment supplies its own verified inventory. | Identity resolution is only as good as the inventory. A wrong binding produces a wrong target. |
| A-02 | Lab use on one host. SQLite is the store. | PostgreSQL is a Stage 2 item ([PRODUCTION_READINESS.md](PRODUCTION_READINESS.md)). |
| A-03 | Approvers are trained people who read the plan before approving it. | Approval binding stops tampering, not careless approval. |
| A-04 | Sensor hosts keep their HMAC keys secret. | A stolen key lets someone forge that sensor's events. PB-08 limits the damage, and a decoy-only sensor can never authorize containment on its own. |
| A-05 | The deployment environment (`lab`, `staging`, `production`) is set honestly. | Environment and scope checks reject events from another environment. They cannot detect a mislabelled deployment. |

## Authorization boundaries (enforced in code)

- Only inventoried assets with `authorized_for_containment: true` can be the target of a proposal. Protected classes (identity, network control, response platform, backup, safety/OT) can never be authorized; configuration validation refuses it.
- Containment is single-asset, through the mock adapter only. Configuration refuses any other adapter name.
- Free text never feeds a decision. Rules match typed attribute values exactly. Policy takes typed values only.
- Captured content is never executed, echoed, or followed. The decoys answer with fixed bytes.
- No outbound calls except sensor-to-API. No callbacks to third-party tracking. Notifications are recorded, not sent.

## Register

| ID | Requirement (brief section) | Status | Evidence |
|---|---|---|---|
| REQ-01 | Explicitly inventoried, owner-authorized assets only (1) | Implemented | `test_every_protected_class_is_excluded`, `test_protected_asset_cannot_be_authorized` |
| REQ-02 | No hack-back, third-party intrusion, malware, credential theft, destructive payloads (1) | Holds by construction: no such code path exists | `test_sensors.py` (decoys never execute or echo input) |
| REQ-03 | No live firewall, endpoint or credential change in the initial build (1) | Holds: mock adapter only | `test_only_mock_adapter_exists` |
| REQ-04 | Python, FastAPI, typed models, strict config, YAML rules and playbooks, pytest (2) | Implemented | `test_config.py` |
| REQ-05 | PostgreSQL with a lightweight local option (2) | **Partial**: SQLite local option only | Backlog B-03 |
| REQ-06 | Durable worker for playbook execution (2) | Implemented: leased action rows in SQLite | `test_restart_after_apply_reconciles_without_duplicate_action` |
| REQ-07 | Separated components; ingestion holds no containment credentials (3) | Implemented | `test_ingestion_and_api_hold_no_adapter_or_executor`, compose `worker` has `network_mode: none` |
| REQ-08 | HTTP decoy, TCP tripwire, honeyfiles, honeytokens (4) | Implemented | `test_sensors.py` |
| REQ-09 | Sensors bound captures, redact, declare what they can and cannot observe (4) | Implemented | `test_http_decoy_bounds_capture`, `test_honeyfile_polling_fallback_cannot_see_reads` |
| REQ-10 | Normalized schema, authenticated ingestion, replay protection, deduplication, size limits (5) | Implemented | `test_ingest.py` |
| REQ-11 | Stale, malformed, delayed, out-of-order events handled (5) | Implemented | `test_event_times`, `test_out_of_order_events_still_correlate_on_occurrence_time` |
| REQ-12 | IP is an observation; NAT, proxies, DHCP, spoofing, scanners handled (5) | Implemented | `test_identity_resolution`, `test_unknown_ambiguous_shared_and_stale_sources_never_reach_an_asset` |
| REQ-13 | Observe, Recommend, Enforce modes; Observe by default (6) | Implemented | `test_observe_mode_records_the_decision_but_proposes_nothing`, `test_enforce_mode_preauthorizes_low_criticality_only` |
| REQ-14 | Decoy interaction alone never authorizes isolation (6) | Implemented as a code invariant | `test_two_decoy_sensors_without_endpoint_evidence_still_never_propose` |
| REQ-15 | Approval bound to target, action, parameters, policy version, expiry (6) | Implemented | `test_approvals.py` |
| REQ-16 | Protected exclusions, critical assets need approval, single asset, rate and concurrency limits (6) | Implemented | `test_policy.py` |
| REQ-17 | Circuit breaker, emergency stop, no automatic un-containment, timers never reconnect (6) | Implemented | `test_bounded_retries_then_failure_and_circuit_breaker`, `test_review_deadline_flags_but_never_releases` |
| REQ-18 | Idempotency, bounded retries, reconciliation, compensating actions, partial failures (6) | Implemented | `test_executor.py` |
| REQ-19 | Never flush rules or replace unrelated policy (6) | Implemented in the mock; the contract requires it of real adapters | `test_full_lifecycle_isolate_verify_recover` (baseline rules unchanged) |
| REQ-20 | Versioned YAML playbooks with every required field; eight playbooks (7) | Implemented | `playbooks/`, `test_isolation_playbook_without_approval_is_refused` |
| REQ-21 | Persisted state machine with rejected, expired, failed, partially_completed (7) | Implemented | `test_invalid_state_transition_is_refused`, lifecycle transition list in `test_full_lifecycle_isolate_verify_recover` |
| REQ-22 | AI may summarize but never authorize; authorization path independent of model output (8) | Holds: no model wired; deterministic templates | `test_no_decision_path_reads_model_or_assist_output` |
| REQ-23 | RBAC, secrets interface, transport protection, append-only audit, evidence manifests, custody, retention (9) | Implemented | `test_api.py`, `test_evidence_audit.py`; TLS required off loopback |
| REQ-24 | Disclose that hashes alone do not establish chain of custody (9) | Implemented | `SECURITY.md`, manifest `limits` field |
| REQ-25 | Measurements labelled with environment, workload and limits (12) | Implemented | `test_metrics_are_labelled_with_their_limits` |

## Required tests (brief section 10)

| Required test | Test(s) |
|---|---|
| Normal traffic produces no containment | `test_ingest.py::test_normal_traffic_creates_no_case` |
| Single decoy interaction alerts, no isolation | `test_policy.py::test_single_decoy_interaction_alerts_but_never_proposes` |
| Corroborated evidence produces a mock isolation proposal | `test_policy.py::test_corroborated_evidence_produces_exact_single_asset_proposal` |
| Approved mock isolation and verified recovery | `test_executor.py::test_full_lifecycle_isolate_verify_recover` |
| Protected-asset rejection | `test_policy.py::test_protected_asset_is_rejected_and_escalated`, `test_every_protected_class_is_excluded` |
| Unknown or ambiguous identity rejection | `test_policy.py::test_unknown_ambiguous_shared_and_stale_sources_never_reach_an_asset`, `test_ambiguous_decoy_source_does_not_corroborate_endpoint_alert`, `test_conflicting_asserted_identity_is_not_trusted` |
| Forged, stale, duplicated, malformed events | `test_ingest.py`: `test_forged_signature_is_rejected_and_recorded`, `test_stale_and_future_request_timestamps_are_rejected`, `test_replayed_request_is_rejected`, `test_duplicate_event_is_accepted_once`, `test_malformed_events_are_rejected` |
| Approval replay and parameter tampering | `test_approvals.py`: `test_approval_replay_is_refused`, `test_wrong_plan_hash_is_refused`, `test_parameter_tampering_in_storage_is_detected_at_approval`, `test_parameter_tampering_after_approval_is_blocked_at_execution` |
| Adapter timeouts and partial failures | `test_executor.py`: `test_timeout_after_apply_is_reconciled_without_reapplying`, `test_timeout_without_apply_retries_then_succeeds`, `test_partial_apply_is_left_in_place_and_escalated` |
| Concurrent incidents and rate limits | `test_policy.py::test_concurrency_limit_blocks_second_incident`, `test_hourly_rate_limit`; `test_executor.py::test_concurrent_incidents_second_approval_refused` |
| Restart-safe execution and reconciliation | `test_executor.py`: `test_restart_after_apply_reconciles_without_duplicate_action`, `test_restart_before_apply_retries_cleanly`, `test_live_lease_is_not_stolen` |
| Emergency stop | `test_executor.py`: `test_emergency_stop_halts_worker_cancels_queue_and_keeps_containment`, `test_emergency_stop_cancels_queued_isolation`, `test_kill_switch_file_halts_worker_and_blocks_proposals` |
| Prompt injection in telemetry stays inert | `test_ingest.py::test_prompt_injection_in_telemetry_stays_inert`; `test_boundaries.py::test_assist_output_is_advisory_and_quotes_hostile_text` |
| Evidence integrity verification | `test_evidence_audit.py`: `test_evidence_manifest_and_integrity`, `test_audit_tampering_is_detected` |

## Success criteria (brief section 12)

| Criterion | How it is shown |
|---|---|
| Every response decision has traceable evidence | Each proposal stores its signal IDs, artifact hashes, all 12 policy checks, and a plan hash. Each step is an audit record. |
| Every applied action has valid authorization | The executor re-checks the approval, the plan hash, and the policy version before every adapter call (`test_parameter_tampering_after_approval_is_blocked_at_execution`). |
| Protected and out-of-scope assets are never automatically isolated | `test_every_protected_class_is_excluded`; configuration cannot authorize them. |
| Duplicate events do not cause duplicate actions | `test_duplicate_corroborating_event_does_not_duplicate_actions` |
| Incomplete evidence does not trigger containment | `test_two_decoy_sensors_without_endpoint_evidence_still_never_propose`, `test_network_lateral_signal_without_endpoint_evidence_is_denied` |
| A restart does not lose action state | `test_restart_after_apply_reconciles_without_duplicate_action` |
| Recovery is verified and auditable | `test_full_lifecycle_isolate_verify_recover`, `test_recovery_requires_every_criterion` |
