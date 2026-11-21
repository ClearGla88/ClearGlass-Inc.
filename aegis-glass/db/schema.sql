-- Aegis Glass production schema (PostgreSQL 15+).
--
-- Status: designed and syntax-checked against PostgreSQL 16 (scripts/check-schema.sh).
-- The application does not use it yet: this release runs on the in-memory
-- Repository. A Postgres adapter implementing lib/repository.ts is the next step.
--
-- Tenant isolation is enforced twice: every query in the adapter filters by
-- tenant_id, and row-level security refuses rows from any other tenant even if
-- a query forgets. The app role sets `aegis.tenant_id` per transaction:
--   SET LOCAL aegis.tenant_id = '<tenant uuid>';

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TYPE classification AS ENUM ('PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED', 'CROWN_JEWEL');
CREATE TYPE asset_action AS ENUM ('view', 'export');
CREATE TYPE case_kind AS ENUM ('honey_access', 'leak_report', 'risk_critical');
CREATE TYPE case_status AS ENUM ('needs_review', 'investigating', 'closed_no_action', 'closed_action_taken');
CREATE TYPE risk_state AS ENUM ('LOW', 'GUARDED', 'HIGH', 'CRITICAL');

CREATE TABLE tenants (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name        text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- Identity lives in the OIDC provider. This table holds only the stable subject
-- and what authorization needs. No email column on purpose.
CREATE TABLE principals (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  oidc_sub    text NOT NULL,
  roles       text[] NOT NULL DEFAULT '{}'
              CHECK (roles <@ ARRAY['viewer','editor','owner','tenant_admin','investigator']::text[]),
  created_at  timestamptz NOT NULL DEFAULT now(),
  disabled_at timestamptz,
  UNIQUE (tenant_id, oidc_sub),
  UNIQUE (tenant_id, id)
);

CREATE TABLE assets (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  owner_id        uuid NOT NULL,
  title           text NOT NULL CHECK (length(title) BETWEEN 1 AND 300),
  alt_text        text NOT NULL CHECK (length(alt_text) BETWEEN 1 AND 2000),
  classification  classification NOT NULL,
  compartments    text[] NOT NULL DEFAULT '{}',
  is_honey        boolean NOT NULL DEFAULT false,
  -- Object key in the private bucket. Never a public URL.
  storage_key     text NOT NULL UNIQUE,
  mime            text NOT NULL CHECK (mime IN ('image/png', 'image/jpeg', 'image/webp')),
  -- Envelope-encryption metadata. The data key is stored only in wrapped form.
  kek_id          text NOT NULL,
  wrapped_key     bytea NOT NULL,
  original_sha256 bytea NOT NULL CHECK (length(original_sha256) = 32),
  original_dhash  bigint,
  created_at      timestamptz NOT NULL DEFAULT now(),
  deleted_at      timestamptz,
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, owner_id) REFERENCES principals(tenant_id, id)
);
CREATE INDEX assets_tenant_idx ON assets (tenant_id) WHERE deleted_at IS NULL;
CREATE INDEX assets_dhash_idx ON assets (original_dhash);

CREATE TABLE policy_grants (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  user_id     uuid NOT NULL,
  asset_id    uuid,
  compartment text,
  actions     asset_action[] NOT NULL CHECK (cardinality(actions) > 0),
  purpose     text NOT NULL CHECK (length(purpose) BETWEEN 3 AND 300),
  granted_by  uuid NOT NULL,
  expires_at  timestamptz NOT NULL,
  revoked_at  timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now(),
  -- Exactly one target: an asset or a compartment.
  CHECK ((asset_id IS NULL) <> (compartment IS NULL)),
  CHECK (expires_at > created_at),
  FOREIGN KEY (tenant_id, user_id) REFERENCES principals(tenant_id, id),
  FOREIGN KEY (tenant_id, granted_by) REFERENCES principals(tenant_id, id),
  FOREIGN KEY (tenant_id, asset_id) REFERENCES assets(tenant_id, id)
);
CREATE INDEX grants_lookup_idx ON policy_grants (tenant_id, user_id) WHERE revoked_at IS NULL;

-- One row per served preview. Signed; never updated.
CREATE TABLE view_receipts (
  receipt_id        uuid PRIMARY KEY,
  tenant_id         uuid NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  trace_token       text NOT NULL CHECK (trace_token ~ '^T-[0-9A-Z]{10}$'),
  asset_id          uuid NOT NULL,
  user_id           uuid NOT NULL,
  capability_id     text NOT NULL,
  classification    classification NOT NULL,
  policy_version    text NOT NULL,
  served_at         timestamptz NOT NULL,
  served_sha256     bytea NOT NULL CHECK (length(served_sha256) = 32),
  served_dhash      bigint NOT NULL,
  body              jsonb NOT NULL,
  signature         bytea NOT NULL,
  key_id            text NOT NULL,
  UNIQUE (tenant_id, trace_token),
  FOREIGN KEY (tenant_id, asset_id) REFERENCES assets(tenant_id, id),
  FOREIGN KEY (tenant_id, user_id) REFERENCES principals(tenant_id, id)
);
CREATE INDEX receipts_asset_idx ON view_receipts (tenant_id, asset_id, served_at DESC);
CREATE INDEX receipts_dhash_idx ON view_receipts (served_dhash);

CREATE TABLE risk_decisions (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id     uuid NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  session_id    text NOT NULL,
  user_id       uuid NOT NULL,
  from_state    risk_state NOT NULL,
  to_state      risk_state NOT NULL,
  score         integer NOT NULL CHECK (score >= 0),
  contributions jsonb NOT NULL,
  decided_at    timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, user_id) REFERENCES principals(tenant_id, id)
);
CREATE INDEX risk_session_idx ON risk_decisions (tenant_id, session_id, decided_at DESC);

CREATE TABLE incident_cases (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          uuid NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  kind               case_kind NOT NULL,
  status             case_status NOT NULL DEFAULT 'needs_review',
  subject_user_id    uuid NOT NULL,
  subject_session_id text NOT NULL,
  asset_id           uuid,
  summary            text NOT NULL,
  opened_at          timestamptz NOT NULL DEFAULT now(),
  -- Closing a case requires a named reviewer and a written rationale.
  reviewed_by        uuid,
  review_notes       text,
  closed_at          timestamptz,
  legal_hold         boolean NOT NULL DEFAULT false,
  CHECK ((closed_at IS NULL) OR (reviewed_by IS NOT NULL AND review_notes IS NOT NULL)),
  FOREIGN KEY (tenant_id, subject_user_id) REFERENCES principals(tenant_id, id),
  FOREIGN KEY (tenant_id, reviewed_by) REFERENCES principals(tenant_id, id)
);
CREATE INDEX cases_open_idx ON incident_cases (tenant_id, status) WHERE closed_at IS NULL;

-- Append-only, hash-chained audit trail. See lib/audit.ts for the record format.
CREATE TABLE audit_events (
  seq        bigint PRIMARY KEY,
  ts         timestamptz NOT NULL,
  type       text NOT NULL,
  tenant_id  text NOT NULL,
  actor      text NOT NULL,
  subject    text,
  data       jsonb NOT NULL,
  prev_hash  char(64) NOT NULL,
  hash       char(64) NOT NULL UNIQUE,
  mac        char(64) NOT NULL,
  CHECK (type IN (
    'authz.decision','capability.issued','capability.denied','media.served','media.denied',
    'rate.limited','risk.state_changed','session.revoked','grant.revoked','honey.accessed',
    'case.opened','trace.resolved','audit.verified'))
);
CREATE INDEX audit_tenant_ts_idx ON audit_events (tenant_id, ts);

CREATE TABLE audit_checkpoints (
  seq        bigint PRIMARY KEY REFERENCES audit_events(seq),
  hash       char(64) NOT NULL,
  ts         timestamptz NOT NULL,
  signature  text NOT NULL,
  key_id     text NOT NULL
);

-- Refuse UPDATE, DELETE and TRUNCATE on evidence tables, whoever asks.
-- Retention runs through a separate, audited archival job with its own role.
CREATE FUNCTION refuse_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
END;
$$;

CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events
  FOR EACH ROW EXECUTE FUNCTION refuse_mutation();
CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON audit_events
  FOR EACH STATEMENT EXECUTE FUNCTION refuse_mutation();
CREATE TRIGGER audit_checkpoints_append_only BEFORE UPDATE OR DELETE ON audit_checkpoints
  FOR EACH ROW EXECUTE FUNCTION refuse_mutation();
CREATE TRIGGER view_receipts_append_only BEFORE UPDATE OR DELETE ON view_receipts
  FOR EACH ROW EXECUTE FUNCTION refuse_mutation();
CREATE TRIGGER risk_decisions_append_only BEFORE UPDATE OR DELETE ON risk_decisions
  FOR EACH ROW EXECUTE FUNCTION refuse_mutation();

-- Row-level security for tenant isolation.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['principals','assets','policy_grants','view_receipts','risk_decisions','incident_cases'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON %I USING (tenant_id = current_setting(''aegis.tenant_id'', true)::uuid) '
      'WITH CHECK (tenant_id = current_setting(''aegis.tenant_id'', true)::uuid)', t);
  END LOOP;
END;
$$;

COMMIT;
