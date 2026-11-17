# Traceability

Per SPEC section 14: requirement → control → test → evidence → residual risk → accountable reviewer.

The **evidence** for every row is a passing unit test in this package (CI job "Guardian Sentinel CI" and the root suite in Baseline CI). That makes the control VERIFIED, not VALIDATED.

The **accountable reviewer** for every row is unassigned. No human review has been recorded.

| SPEC | Requirement | Control | Test | Residual risk |
|---|---|---|---|---|
| 1 | No promotion without evidence | `CapabilityRegistry.promote` (one step, typed evidence) | `test_gs_capability.py` | Evidence references are recorded, not inspected |
| 1, 17 | State design mode when integrations are absent | `Guardian.design_mode`, `startup_report` | `test_design_mode_startup_says_so_and_never_claims_monitoring` | |
| 3 | Authenticated configuration; no silent expansion | `config.verify_envelope`, strict `validate` | `test_gs_config.py` | HMAC is shared-secret; key protection is the host's job |
| 3 | Exact triggers, approved recipients, shared-field allowlist | `validate` action checks | `test_schema_rejections` | |
| 5 | Required provenance and quality fields; reject or quarantine malformed input | `parse_observation`, `ObservationGate.admit` | `test_gs_observation.py` | Occlusion and image quality need detector-side checks (not built) |
| 5 | Stale, replay, duplicate, out-of-order, clock, jump | `ObservationGate` | `test_unauthorized_failed_or_stale_input_is_rejected`, `test_duplicates_and_replays_are_rejected`, `test_out_of_order_clock_and_jump_problems_are_quarantined` | The replay window is bounded by `seen_capacity` |
| 5 | Shared upstream is not independent; keep disagreement | `independent`, `independent_groups`, `compare` | `test_shared_upstream_is_not_independent_evidence`, `test_disagreement_is_preserved_not_averaged` | Lineage is only as good as the adapter's declaration |
| 6 | Supported categories only; no intent inference | `HazardKind`, `make_event` | `test_unsupported_hazard_categories_cannot_be_created` | |
| 6 | Calibrated confidence only | `make_event` | `test_confidence_only_from_a_calibrated_detector` | Calibration itself is not checked here |
| 7 | Complete reviewed contract before VALIDATED; no invented targets | `contracts.missing`, `promote` | `test_gs_contracts_hazards.py`, `test_detector_needs_a_complete_contract_to_be_validated` | |
| 8 | Separate lifecycle and health dimensions; coverage from fresh input | `HealthSupervisor` | `test_coverage_depends_on_fresh_permitted_input`, `test_routing_reflects_tested_channels_only` | Connectivity has no probe yet (stays UNKNOWN) |
| 8 | Never "you are safe"; silence is not safety | `Guardian.status_lines`, language tests | `test_gs_language.py`, `test_monitoring_lapses_when_input_goes_stale` | |
| 9 | Templates, 3 to 10 words, no speculative or safety language | `TEMPLATES`, `lint_message` | `test_every_template_passes_the_language_lint` | Comprehension is untested with people |
| 9 | Dedupe without hiding escalation; expire stale alerts | `AlertController.raise_alert`, `expire`, `repeat_last` | `test_duplicates_suppressed_inside_the_window_but_escalation_passes`, `test_stale_events_expire_and_are_repeated_only_as_history` | |
| 10 | Separate delivery states; playback is not acknowledgement; verified fallbacks only | `DELIVERY_TRANSITIONS`, channel routing | `test_delivery_states_follow_platform_reports_only`, `test_falls_back_to_the_next_verified_channel`, `test_headphone_loss_claims_watch_fallback_only_when_verified` | |
| 11 | Action matrix, consent, host confirmation, dedupe, bounded retries | `EmergencyWorkflow` | `test_gs_emergency.py` | No real dispatcher exists |
| 11 | Cancel only what is cancellable; never claim recall | `EmergencyWorkflow.cancel`, `ACTION_TRANSITIONS` | `test_cancel_stops_only_what_has_not_been_attempted`, `test_stop_sharing_reports_what_cannot_be_recalled` | |
| 11 | Disclose unavailability; do not obstruct native controls | `_cmd_help` | `test_emergency_help_in_design_mode_points_to_native_controls` | |
| 12 | Minimal tamper-evident audit; no location or media in logs | `AuditLog` | `test_gs_audit.py` | Truncation of the newest records is not detectable without an external checkpoint |
| 12 | Integrity fault isolates affected functions, keeps the rest | `Guardian.report_integrity_fault` | `test_integrity_fault_isolates_external_actions_but_keeps_local_alerts` | Recovery review is a manual process (not built) |
| 12 | State deletion limits | `_cmd_delete` | `test_delete_states_its_limits_and_unknown_commands_are_refused` | |
| 16 | Commands confirmed only on success; expired alerts historical | `Guardian.command` | `test_gs_health_commands.py` | |

## Not yet traceable

These have no control in this package, because each needs hardware, a host platform or people:

- SPEC 2: operating envelopes.
- SPEC 4: real separation of the language path, which is a host-architecture property.
- SPEC 9: volume limits and directional audio.
- SPEC 12: key storage, encryption and signed updates.
- SPEC 13: battery, thermal and suspension signals.
- SPEC 14: the release gates and field metrics.
