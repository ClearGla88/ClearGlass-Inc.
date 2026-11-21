-- ClearGlass Agent Office: PostgreSQL 16 schema (production target).
--
-- The MVP runtime stores the same records in SQLite (packages/agent_core/store.py).
-- tests/test_schema_parity.py asserts every field of every model in
-- packages/agent_core/models.py has a column here (or a documented junction
-- table), and tests/test_postgres_schema.py applies this file to a real
-- PostgreSQL server and checks the append-only triggers.
--
-- Invariants enforced by the database, not only by application code:
--   * audit_events, approval_decisions, decisions, messages, risk_assessments
--     reject UPDATE, DELETE, and TRUNCATE.
--   * No permission row can grant the human-only 'approve' level.
--   * Tiers, statuses, and connector types are closed sets (CHECK constraints).
--   * Every foreign key is indexed.

BEGIN;

CREATE TABLE companies (
    id                     text PRIMARY KEY,
    name                   text NOT NULL,
    tagline                text NOT NULL,
    brand_line             text NOT NULL,
    region                 text NOT NULL,
    mission                text NOT NULL,
    operator               jsonb NOT NULL,
    objectives             jsonb NOT NULL DEFAULT '[]',
    ideal_customer_profile jsonb NOT NULL DEFAULT '{}',
    approved_sources       jsonb NOT NULL DEFAULT '[]',
    brand_guidelines       jsonb NOT NULL DEFAULT '[]',
    created_at             timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE departments (
    id               text PRIMARY KEY,
    name             text NOT NULL,
    room             text NOT NULL,
    head             text NOT NULL,           -- FK added after agents exists
    mission          text NOT NULL,
    responsibilities jsonb NOT NULL DEFAULT '[]',
    boundaries       jsonb NOT NULL DEFAULT '[]'
);

CREATE TABLE agents (
    id               text PRIMARY KEY CHECK (id ~ '^[a-z]+\.[a-z0-9-]+$'),
    callsign         text NOT NULL UNIQUE,
    name             text NOT NULL,
    department       text NOT NULL REFERENCES departments(id),
    reports_to       text NOT NULL,           -- an agent id or 'operator'; checked by trigger below
    objective        text NOT NULL,
    room             text NOT NULL,
    success_criteria jsonb NOT NULL DEFAULT '[]',
    skills           jsonb NOT NULL DEFAULT '[]',
    memory_scopes    jsonb NOT NULL DEFAULT '["company"]',
    clearance        text NOT NULL DEFAULT 'internal'
                     CHECK (clearance IN ('public','internal','confidential','restricted')),
    boundaries       jsonb NOT NULL DEFAULT '[]',
    status           text NOT NULL DEFAULT 'idle'
                     CHECK (status IN ('idle','working','waiting_for_approval','blocked','completed','failed','paused','retired')),
    current_task_id  text,                    -- FK added after tasks exists
    metrics          jsonb NOT NULL DEFAULT '{}',
    version          integer NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX agents_department_idx ON agents(department);
CREATE INDEX agents_reports_to_idx ON agents(reports_to);

ALTER TABLE departments ADD CONSTRAINT departments_head_fk
    FOREIGN KEY (head) REFERENCES agents(id) DEFERRABLE INITIALLY DEFERRED;
CREATE INDEX departments_head_idx ON departments(head);

CREATE FUNCTION agents_reports_to_valid() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.reports_to <> 'operator' AND NOT EXISTS (SELECT 1 FROM agents WHERE id = NEW.reports_to) THEN
        RAISE EXCEPTION 'reports_to % is neither an agent nor the operator', NEW.reports_to;
    END IF;
    RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER agents_reports_to_check AFTER INSERT OR UPDATE ON agents
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION agents_reports_to_valid();

CREATE TABLE tools (
    id           text PRIMARY KEY,
    name         text NOT NULL,
    description  text NOT NULL,
    connector    text NOT NULL CHECK (connector IN ('internal','dry_run','live')),
    actions      jsonb NOT NULL,
    external     boolean NOT NULL DEFAULT false,
    sandbox_only boolean NOT NULL DEFAULT false,
    risk_ceiling text NOT NULL CHECK (risk_ceiling IN ('low','medium','high','critical')),
    secret_ref   text CHECK (secret_ref IS NULL OR secret_ref ~ '^vault:[a-z0-9][a-z0-9_/-]*$')
);

-- Agent.tools (junction)
CREATE TABLE agent_tools (
    agent_id text NOT NULL REFERENCES agents(id),
    tool_id  text NOT NULL REFERENCES tools(id),
    PRIMARY KEY (agent_id, tool_id)
);
CREATE INDEX agent_tools_tool_idx ON agent_tools(tool_id);

-- Agent.permissions (normalized grants; the Permission model)
CREATE TABLE permissions (
    id         text PRIMARY KEY,
    agent_id   text NOT NULL REFERENCES agents(id),
    domain     text NOT NULL,
    level      text NOT NULL CHECK (level IN ('none','read','propose','write','execute')),  -- approval is human-only
    granted_by text NOT NULL,
    granted_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (agent_id, domain)
);

CREATE TABLE missions (
    id             text PRIMARY KEY,
    key            text NOT NULL DEFAULT '',
    title          text NOT NULL,
    objective      text NOT NULL,
    department     text NOT NULL REFERENCES departments(id),
    owner          text NOT NULL REFERENCES agents(id),
    priority       smallint NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
    deadline       date,
    deliverables   jsonb NOT NULL DEFAULT '[]',
    constraints    jsonb NOT NULL DEFAULT '[]',
    approval_rules jsonb NOT NULL DEFAULT '[]',
    goal_ids       jsonb NOT NULL DEFAULT '[]',
    status         text NOT NULL DEFAULT 'active' CHECK (status IN ('active','completed','paused','cancelled')),
    workflow_id    text NOT NULL,             -- FK added after workflows exists
    created_by     text NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX missions_department_idx ON missions(department);
CREATE INDEX missions_owner_idx ON missions(owner);
CREATE UNIQUE INDEX missions_key_uq ON missions(key) WHERE key <> '';

CREATE TABLE workflows (
    id         text PRIMARY KEY,
    mission_id text NOT NULL REFERENCES missions(id) DEFERRABLE INITIALLY DEFERRED,
    status     text NOT NULL DEFAULT 'active' CHECK (status IN ('active','completed','stalled')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
    -- Workflow.task_ids and Workflow.waves are derived from tasks.workflow_id and tasks.wave.
);
CREATE INDEX workflows_mission_idx ON workflows(mission_id);
ALTER TABLE missions ADD CONSTRAINT missions_workflow_fk
    FOREIGN KEY (workflow_id) REFERENCES workflows(id) DEFERRABLE INITIALLY DEFERRED;
CREATE INDEX missions_workflow_idx ON missions(workflow_id);

CREATE TABLE approvals (
    id                text PRIMARY KEY,
    action_type       text NOT NULL,
    action            jsonb NOT NULL,          -- exact payload the digest covers
    action_digest     char(64) NOT NULL CHECK (action_digest ~ '^[0-9a-f]{64}$'),
    requested_by      text NOT NULL REFERENCES agents(id),
    risk_tier         text NOT NULL CHECK (risk_tier IN ('low','medium','high','critical')),
    reasons           jsonb NOT NULL DEFAULT '[]',
    task_id           text,                    -- FK added after tasks exists
    mission_id        text REFERENCES missions(id),
    change_plan       text,
    rollback_plan     text,
    verification_plan text,
    status            text NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending','approved','rejected','changes_requested','cancelled','expired','executed')),
    approved_digest   char(64) CHECK (approved_digest IS NULL OR approved_digest ~ '^[0-9a-f]{64}$'),
    approved_action   jsonb,
    execution         jsonb,
    expires_at        timestamptz NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    -- Critical approvals must carry all three plans.
    CHECK (risk_tier <> 'critical' OR (change_plan <> '' AND rollback_plan <> '' AND verification_plan <> '')),
    -- An approved or executed approval is always bound to a digest.
    CHECK (status NOT IN ('approved','executed') OR approved_digest IS NOT NULL)
    -- Approval.decisions lives in approval_decisions (append-only).
);
CREATE INDEX approvals_status_idx ON approvals(status);
CREATE INDEX approvals_requested_by_idx ON approvals(requested_by);
CREATE INDEX approvals_mission_idx ON approvals(mission_id);

CREATE TABLE tasks (
    id              text PRIMARY KEY,
    key             text NOT NULL,
    mission_id      text NOT NULL REFERENCES missions(id),
    workflow_id     text NOT NULL REFERENCES workflows(id),
    title           text NOT NULL,
    assignee        text NOT NULL REFERENCES agents(id),
    action          jsonb NOT NULL,
    status          text NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','running','waiting_approval','blocked','completed','failed','cancelled')),
    resolved_action jsonb,
    output          jsonb,
    approval_id     text REFERENCES approvals(id),
    attempts        smallint NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts    smallint NOT NULL DEFAULT 2 CHECK (max_attempts BETWEEN 1 AND 5),
    error           text,
    wave            smallint NOT NULL DEFAULT 0 CHECK (wave >= 0),
    started_at      timestamptz,
    completed_at    timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workflow_id, key)
);
CREATE INDEX tasks_mission_idx ON tasks(mission_id);
CREATE INDEX tasks_assignee_status_idx ON tasks(assignee, status);
CREATE INDEX tasks_approval_idx ON tasks(approval_id);

-- Task.depends_on (junction). Same-workflow edges only; cycles are rejected by the workflow engine.
CREATE TABLE task_dependencies (
    task_id    text NOT NULL REFERENCES tasks(id),
    depends_on text NOT NULL REFERENCES tasks(id),
    PRIMARY KEY (task_id, depends_on),
    CHECK (task_id <> depends_on)
);
CREATE INDEX task_dependencies_depends_on_idx ON task_dependencies(depends_on);

ALTER TABLE approvals ADD CONSTRAINT approvals_task_fk FOREIGN KEY (task_id) REFERENCES tasks(id);
CREATE INDEX approvals_task_idx ON approvals(task_id);
ALTER TABLE agents ADD CONSTRAINT agents_current_task_fk FOREIGN KEY (current_task_id) REFERENCES tasks(id);
CREATE INDEX agents_current_task_idx ON agents(current_task_id);

-- Approval.decisions: append-only decision history.
CREATE TABLE approval_decisions (
    seq              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    approval_id      text NOT NULL REFERENCES approvals(id),
    decision         text NOT NULL CHECK (decision IN ('approve','reject','modify','cancelled')),
    reason           text NOT NULL CHECK (length(btrim(reason)) >= 12),
    decided_by       text NOT NULL,
    decided_at       timestamptz NOT NULL DEFAULT now(),
    modifications    jsonb,
    resulting_digest char(64)
);
CREATE INDEX approval_decisions_approval_idx ON approval_decisions(approval_id);

CREATE TABLE messages (
    id         text PRIMARY KEY,
    thread_id  text NOT NULL,
    sender     text NOT NULL,
    recipient  text NOT NULL,
    kind       text NOT NULL CHECK (kind IN ('handoff','assignment','escalation','review','report','decision',
                                             'meeting_summary','notification','note')),
    subject    text NOT NULL,
    body       text NOT NULL,
    mission_id text REFERENCES missions(id),
    task_id    text REFERENCES tasks(id),
    refs       jsonb NOT NULL DEFAULT '[]',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX messages_thread_idx ON messages(thread_id, created_at);
CREATE INDEX messages_mission_idx ON messages(mission_id);
CREATE INDEX messages_task_idx ON messages(task_id);

CREATE TABLE decisions (
    id         text PRIMARY KEY,
    made_by    text NOT NULL,
    kind       text NOT NULL CHECK (kind IN ('agent','operator','policy')),
    summary    text NOT NULL,
    rationale  text NOT NULL,
    outcome    text NOT NULL,
    mission_id text REFERENCES missions(id),
    task_id    text REFERENCES tasks(id),
    refs       jsonb NOT NULL DEFAULT '[]',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX decisions_mission_idx ON decisions(mission_id);
CREATE INDEX decisions_task_idx ON decisions(task_id);

CREATE TABLE memory_records (
    id             text PRIMARY KEY,
    layer          text NOT NULL CHECK (layer IN ('short_term','long_term')),
    scope          text NOT NULL,
    title          text NOT NULL,
    content        text NOT NULL,
    source         text NOT NULL,
    classification text NOT NULL DEFAULT 'internal'
                   CHECK (classification IN ('public','internal','confidential','restricted')),
    status         text NOT NULL CHECK (status IN ('active','expired','proposed','approved','rejected')),
    created_by     text NOT NULL,
    approved_by    text,
    tags           jsonb NOT NULL DEFAULT '[]',
    expires_at     timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    CHECK ((layer = 'short_term' AND status IN ('active','expired'))
        OR (layer = 'long_term'  AND status IN ('proposed','approved','rejected'))),
    CHECK (status <> 'approved' OR approved_by IS NOT NULL)
);
CREATE INDEX memory_records_scope_idx ON memory_records(scope, status);

CREATE TABLE audit_events (
    seq            bigint PRIMARY KEY CHECK (seq >= 1),
    event_id       text NOT NULL UNIQUE,
    ts             timestamptz NOT NULL,
    actor          text NOT NULL,
    actor_type     text NOT NULL CHECK (actor_type IN ('agent','human','system')),
    event_type     text NOT NULL,
    subject        text NOT NULL,
    payload        jsonb NOT NULL,
    risk_tier      text CHECK (risk_tier IS NULL OR risk_tier IN ('low','medium','high','critical')),
    policy_version text,
    prev_hash      char(64) NOT NULL CHECK (prev_hash ~ '^[0-9a-f]{64}$'),
    hash           char(64) NOT NULL UNIQUE CHECK (hash ~ '^[0-9a-f]{64}$')
);
CREATE INDEX audit_events_subject_idx ON audit_events(subject);
CREATE INDEX audit_events_type_idx ON audit_events(event_type);

CREATE TABLE simulations (
    id             text PRIMARY KEY,
    scenario_type  text NOT NULL CHECK (scenario_type IN ('pricing','campaign','incident','rollout')),
    title          text NOT NULL,
    assumptions    jsonb NOT NULL,
    options        jsonb NOT NULL,
    seed           bigint NOT NULL,
    runs           integer NOT NULL CHECK (runs BETWEEN 100 AND 20000),
    status         text NOT NULL DEFAULT 'completed',
    results        jsonb NOT NULL DEFAULT '{}',
    recommendation jsonb NOT NULL DEFAULT '{}',
    disclaimer     text NOT NULL CHECK (disclaimer <> ''),
    created_by     text NOT NULL REFERENCES agents(id),
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX simulations_created_by_idx ON simulations(created_by);

CREATE TABLE reports (
    id           text PRIMARY KEY,
    kind         text NOT NULL CHECK (kind IN ('briefing','eod','weekly','incident','after_action','security_review')),
    title        text NOT NULL,
    period       text NOT NULL,
    generated_by text NOT NULL,
    sections     jsonb NOT NULL DEFAULT '{}',
    metrics      jsonb NOT NULL DEFAULT '{}',
    generated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX reports_kind_idx ON reports(kind, generated_at DESC);

CREATE TABLE risk_assessments (
    id                  text PRIMARY KEY,
    subject_type        text NOT NULL CHECK (subject_type IN ('task','request')),
    subject_id          text NOT NULL,
    action_type         text NOT NULL,
    tier                text NOT NULL CHECK (tier IN ('low','medium','high','critical')),
    score               smallint NOT NULL CHECK (score BETWEEN 0 AND 100),
    outcome             text NOT NULL CHECK (outcome IN ('allow','approval_required','deny')),
    factors             jsonb NOT NULL DEFAULT '[]',
    injection_suspected boolean NOT NULL DEFAULT false,
    policy_version      text NOT NULL,
    assessed_by         text NOT NULL DEFAULT 'policy-engine',
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX risk_assessments_subject_idx ON risk_assessments(subject_type, subject_id);

CREATE TABLE office_state (
    key   text PRIMARY KEY,
    value jsonb NOT NULL
);

-- Append-only enforcement --------------------------------------------------------
CREATE FUNCTION reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
END $$;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['audit_events','approval_decisions','decisions','messages','risk_assessments'] LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION reject_mutation()',
                       t || '_no_mutation', t);
        EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation()',
                       t || '_no_truncate', t);
    END LOOP;
END $$;

COMMIT;
