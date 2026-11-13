-- ClearGlass Agent Office: plan-first missions.
--
-- Applies on top of 002_governance_controls.sql; neither earlier file is edited.
--
-- A plan-first mission may research, analyse and draft. The policy gate refuses every
-- external action, every write to records, and any spending in that mode
-- (config/policy.json, "mission_modes"). The database only needs to accept the mode.

BEGIN;

ALTER TABLE missions DROP CONSTRAINT missions_mode_check;
ALTER TABLE missions ADD CONSTRAINT missions_mode_check
    CHECK (mode IN ('production', 'simulation', 'plan_first'));

COMMIT;
