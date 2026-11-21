-- ClearGlass Agent Office: governance controls ported from agent-office/ (2026-11-08).
-- Apply after 001_init.sql. Runs in one transaction.
--
--   * Grants carry limits, an expiry, and a revocation record.
--   * Missions carry a mode; simulation missions cannot act on production.
--   * Approvals: the original request is immutable, one decision per approval,
--     one execution per approval, and terminal statuses never change.
--   * Idempotency keys and shadow-policy divergences.
--
-- tests/test_postgres_schema.py applies 001 then 002 to a real server and checks
-- each rule below; tests/test_schema_parity.py reads both files.

BEGIN;

-- Grants -------------------------------------------------------------------------
ALTER TABLE permissions ADD COLUMN constraints jsonb NOT NULL DEFAULT '{}';
ALTER TABLE permissions ADD COLUMN expires_at timestamptz;
ALTER TABLE permissions ADD COLUMN revoked_at timestamptz;
ALTER TABLE permissions ADD COLUMN revoked_by text;
ALTER TABLE permissions ADD CONSTRAINT permissions_revocation_attributed
    CHECK ((revoked_at IS NULL) = (revoked_by IS NULL));
ALTER TABLE permissions ADD CONSTRAINT permissions_constraints_known_keys
    CHECK (constraints - 'spend_limit_cents' - 'payload_allowlist' = '{}'::jsonb);
ALTER TABLE permissions ADD CONSTRAINT permissions_spend_limit_non_negative
    CHECK (NOT constraints ? 'spend_limit_cents' OR (constraints->>'spend_limit_cents')::bigint >= 0);

-- Missions -----------------------------------------------------------------------
ALTER TABLE missions ADD COLUMN mode text NOT NULL DEFAULT 'production'
    CHECK (mode IN ('production', 'simulation'));

-- Approvals ----------------------------------------------------------------------
-- One approve / reject / modify decision per approval; 'cancelled' rows may follow.
CREATE UNIQUE INDEX approval_decisions_once ON approval_decisions(approval_id)
    WHERE decision IN ('approve', 'reject', 'modify');

CREATE FUNCTION approvals_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.action, NEW.action_digest, NEW.action_type, NEW.requested_by, NEW.risk_tier, NEW.task_id,
        NEW.mission_id, NEW.change_plan, NEW.rollback_plan, NEW.verification_plan, NEW.created_at, NEW.expires_at)
       IS DISTINCT FROM
       (OLD.action, OLD.action_digest, OLD.action_type, OLD.requested_by, OLD.risk_tier, OLD.task_id,
        OLD.mission_id, OLD.change_plan, OLD.rollback_plan, OLD.verification_plan, OLD.created_at, OLD.expires_at)
    THEN
        RAISE EXCEPTION 'approval % request is immutable', OLD.id USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF OLD.status IN ('executed', 'rejected', 'cancelled', 'expired') AND NEW.status <> OLD.status THEN
        RAISE EXCEPTION 'approval % is % and cannot change status', OLD.id, OLD.status
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF OLD.approved_digest IS NOT NULL AND NEW.approved_digest IS DISTINCT FROM OLD.approved_digest THEN
        RAISE EXCEPTION 'approval % approved digest is immutable', OLD.id USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER approvals_guard BEFORE UPDATE ON approvals FOR EACH ROW EXECUTE FUNCTION approvals_guard();
CREATE TRIGGER approvals_no_delete BEFORE DELETE ON approvals FOR EACH ROW EXECUTE FUNCTION reject_mutation();

-- One execution per approval, recorded before the tool runs.
CREATE TABLE approval_executions (
    approval_id     text PRIMARY KEY REFERENCES approvals(id),
    executed_digest char(64) NOT NULL CHECK (executed_digest ~ '^[0-9a-f]{64}$'),
    executed_at     timestamptz NOT NULL DEFAULT now(),
    task_id         text REFERENCES tasks(id)
);
CREATE INDEX approval_executions_task_idx ON approval_executions(task_id);

-- Idempotency --------------------------------------------------------------------
CREATE TABLE idempotency_keys (
    key            text PRIMARY KEY,
    request_digest char(64) NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
    status         text NOT NULL CHECK (status IN ('in_progress', 'completed', 'failed')),
    result         jsonb,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    CHECK (status <> 'completed' OR result IS NOT NULL)
);

-- Shadow policies ----------------------------------------------------------------
CREATE TABLE shadow_divergences (
    id               text PRIMARY KEY,
    rule_ids         jsonb NOT NULL CHECK (jsonb_typeof(rule_ids) = 'array' AND jsonb_array_length(rule_ids) > 0),
    action_type      text NOT NULL,
    agent_id         text NOT NULL REFERENCES agents(id),
    enforced_outcome text NOT NULL CHECK (enforced_outcome IN ('allow', 'approval_required', 'deny')),
    shadow_outcome   text NOT NULL CHECK (shadow_outcome IN ('allow', 'approval_required', 'deny')),
    digest           char(64) NOT NULL,
    shadow_version   text NOT NULL,
    task_id          text REFERENCES tasks(id),
    created_at       timestamptz NOT NULL DEFAULT now(),
    CHECK (enforced_outcome <> shadow_outcome)
);
CREATE INDEX shadow_divergences_agent_idx ON shadow_divergences(agent_id);
CREATE INDEX shadow_divergences_task_idx ON shadow_divergences(task_id);

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['approval_executions', 'shadow_divergences'] LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION reject_mutation()',
                       t || '_no_mutation', t);
        EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation()',
                       t || '_no_truncate', t);
    END LOOP;
END $$;

COMMIT;
