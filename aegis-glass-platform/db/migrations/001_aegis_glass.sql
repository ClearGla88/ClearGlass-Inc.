-- Aegis Glass schema, version 1.
-- Applied by src/lib/store.ts (AegisStore.migrate) inside a transaction.
-- Identity data (names, emails) lives in the identity provider, not here:
-- this layer stores ids, roles, and pseudonyms only.

CREATE TABLE tenants (
  tenant_id   uuid PRIMARY KEY,
  name        text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
  pseudonym   text NOT NULL UNIQUE,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (
  user_id       uuid PRIMARY KEY,
  tenant_id     uuid NOT NULL REFERENCES tenants (tenant_id),
  display_name  text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),
  roles         text[] NOT NULL CHECK (roles <@ ARRAY['member', 'tenant_admin', 'investigator']::text[]),
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX users_tenant_idx ON users (tenant_id);

-- Server-side sessions: the cookie carries only a signed session id, so
-- revocation takes effect on the very next request.
CREATE TABLE sessions (
  session_id       uuid PRIMARY KEY,
  tenant_id        uuid NOT NULL REFERENCES tenants (tenant_id),
  user_id          uuid NOT NULL REFERENCES users (user_id),
  auth_level       text NOT NULL CHECK (auth_level IN ('pwd', 'mfa', 'phishing_resistant')),
  auth_time        timestamptz NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  expires_at       timestamptz NOT NULL,
  revoked_at       timestamptz,
  paused_at        timestamptz,
  last_risk_state  text NOT NULL DEFAULT 'LOW' CHECK (last_risk_state IN ('LOW', 'GUARDED', 'HIGH', 'CRITICAL')),
  CHECK (expires_at > created_at)
);
CREATE INDEX sessions_user_idx ON sessions (user_id);

CREATE TABLE assets (
  asset_id        uuid PRIMARY KEY,
  tenant_id       uuid NOT NULL REFERENCES tenants (tenant_id),
  owner_id        uuid NOT NULL REFERENCES users (user_id),
  title           text NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
  alt_text        text NOT NULL CHECK (length(alt_text) BETWEEN 1 AND 1000),
  classification  text NOT NULL CHECK (classification IN ('PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED', 'CROWN_JEWEL')),
  compartment     text CHECK (compartment ~ '^[a-z0-9][a-z0-9-]{0,62}$'),
  honey           boolean NOT NULL DEFAULT false,
  blob_key        text NOT NULL UNIQUE,
  content_type    text NOT NULL CHECK (content_type IN ('image/png', 'image/jpeg', 'image/webp')),
  width           integer NOT NULL CHECK (width > 0),
  height          integer NOT NULL CHECK (height > 0),
  original_dhash  text NOT NULL CHECK (original_dhash ~ '^[0-9a-f]{16}$'),
  kek_id          text NOT NULL,
  revoked_at      timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX assets_tenant_idx ON assets (tenant_id);

-- Just-in-time entitlements: exactly one subject (user or role) and exactly one
-- scope (asset or compartment), always with an expiry.
CREATE TABLE grants (
  grant_id         uuid PRIMARY KEY,
  tenant_id        uuid NOT NULL REFERENCES tenants (tenant_id),
  subject_user_id  uuid REFERENCES users (user_id),
  subject_role     text CHECK (subject_role IN ('member', 'tenant_admin', 'investigator')),
  asset_id         uuid REFERENCES assets (asset_id),
  compartment      text CHECK (compartment ~ '^[a-z0-9][a-z0-9-]{0,62}$'),
  actions          text[] NOT NULL CHECK (cardinality(actions) > 0 AND actions <@ ARRAY['view', 'export']::text[]),
  purpose          text CHECK (purpose IS NULL OR length(purpose) BETWEEN 3 AND 200),
  not_before       timestamptz NOT NULL DEFAULT now(),
  expires_at       timestamptz NOT NULL,
  revoked_at       timestamptz,
  created_by       uuid NOT NULL REFERENCES users (user_id),
  created_at       timestamptz NOT NULL DEFAULT now(),
  CHECK ((subject_user_id IS NULL) <> (subject_role IS NULL)),
  CHECK ((asset_id IS NULL) <> (compartment IS NULL)),
  CHECK (expires_at > not_before)
);
CREATE INDEX grants_tenant_idx ON grants (tenant_id) WHERE revoked_at IS NULL;

-- One row per authorised view. The trace token printed in the watermark
-- resolves to this row; only investigators can perform that lookup.
CREATE TABLE views (
  view_id                uuid PRIMARY KEY,
  tenant_id              uuid NOT NULL REFERENCES tenants (tenant_id),
  asset_id               uuid NOT NULL REFERENCES assets (asset_id),
  session_id             uuid NOT NULL REFERENCES sessions (session_id),
  user_id                uuid NOT NULL REFERENCES users (user_id),
  viewer_pseudonym       text NOT NULL,
  trace_token            text NOT NULL UNIQUE CHECK (trace_token ~ '^[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$'),
  capability_id          uuid NOT NULL UNIQUE,
  capability_expires_at  timestamptz NOT NULL,
  consumed_at            timestamptz,
  revoked_at             timestamptz,
  watermark_density      text NOT NULL CHECK (watermark_density IN ('none', 'light', 'standard', 'dense')),
  rotation_seconds       integer NOT NULL CHECK (rotation_seconds >= 0),
  max_width              integer NOT NULL CHECK (max_width > 0),
  risk_state             text NOT NULL CHECK (risk_state IN ('LOW', 'GUARDED', 'HIGH')),
  policy_version         text NOT NULL,
  decision_reasons       text[] NOT NULL,
  -- Purpose stated at request time; media delivery re-runs policy with it.
  purpose                text CHECK (purpose IS NULL OR length(purpose) <= 200),
  derivative_dhash       text CHECK (derivative_dhash ~ '^[0-9a-f]{16}$'),
  created_at             timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX views_session_idx ON views (session_id);
CREATE INDEX views_asset_idx ON views (asset_id);

CREATE TABLE view_receipts (
  receipt_id  uuid PRIMARY KEY,
  view_id     uuid NOT NULL UNIQUE REFERENCES views (view_id),
  payload     jsonb NOT NULL,
  signature   text NOT NULL,
  key_id      text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE risk_events (
  risk_event_id  bigserial PRIMARY KEY,
  session_id     uuid NOT NULL REFERENCES sessions (session_id),
  kind           text NOT NULL CHECK (kind ~ '^[a-z_]{3,40}$'),
  asset_id       uuid,
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX risk_events_session_time_idx ON risk_events (session_id, created_at);

-- Cases always start in needs_human_review. Nothing in this system moves a
-- case to a conclusion automatically.
CREATE TABLE incidents (
  incident_id  uuid PRIMARY KEY,
  tenant_id    uuid REFERENCES tenants (tenant_id),
  kind         text NOT NULL CHECK (kind IN ('honey_access', 'critical_risk', 'leak_report')),
  status       text NOT NULL DEFAULT 'needs_human_review'
               CHECK (status IN ('needs_human_review', 'investigating', 'closed_no_action', 'closed_confirmed')),
  session_id   uuid,
  view_id      uuid,
  asset_id     uuid,
  summary      text NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now()
);

-- Tamper-evident audit trail. ts is stored as the exact ISO string that was
-- hashed, so verification recomputes byte-identical input.
CREATE TABLE audit_events (
  seq          bigint PRIMARY KEY CHECK (seq > 0),
  event_id     uuid NOT NULL UNIQUE,
  ts           text NOT NULL CHECK (ts ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$'),
  type         text NOT NULL,
  tenant_id    uuid,
  actor        text NOT NULL,
  severity     text NOT NULL CHECK (severity IN ('info', 'notice', 'warning', 'critical')),
  subject      jsonb NOT NULL DEFAULT '{}'::jsonb,
  data         jsonb NOT NULL DEFAULT '{}'::jsonb,
  prev_hash    char(64) NOT NULL,
  hash         char(64) NOT NULL UNIQUE,
  recorded_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_events_tenant_idx ON audit_events (tenant_id, seq);

-- Single-row chain head, locked FOR UPDATE on every append to serialise writers.
CREATE TABLE audit_chain_head (
  id    boolean PRIMARY KEY DEFAULT true CHECK (id),
  seq   bigint NOT NULL,
  hash  char(64) NOT NULL
);
INSERT INTO audit_chain_head (id, seq, hash) VALUES (true, 0, repeat('0', 64));

CREATE TABLE audit_checkpoints (
  seq        bigint PRIMARY KEY REFERENCES audit_events (seq),
  hash       char(64) NOT NULL,
  ts         text NOT NULL,
  key_id     text NOT NULL,
  signature  text NOT NULL
);

CREATE FUNCTION aegis_forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'aegis: % on append-only table % is not permitted', TG_OP, TG_TABLE_NAME
    USING ERRCODE = 'insufficient_privilege';
END
$$;

CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events
  FOR EACH ROW EXECUTE FUNCTION aegis_forbid_mutation();
CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON audit_events
  FOR EACH STATEMENT EXECUTE FUNCTION aegis_forbid_mutation();
CREATE TRIGGER audit_checkpoints_append_only BEFORE UPDATE OR DELETE ON audit_checkpoints
  FOR EACH ROW EXECUTE FUNCTION aegis_forbid_mutation();
CREATE TRIGGER audit_checkpoints_no_truncate BEFORE TRUNCATE ON audit_checkpoints
  FOR EACH STATEMENT EXECUTE FUNCTION aegis_forbid_mutation();
CREATE TRIGGER view_receipts_append_only BEFORE UPDATE OR DELETE ON view_receipts
  FOR EACH ROW EXECUTE FUNCTION aegis_forbid_mutation();
CREATE TRIGGER view_receipts_no_truncate BEFORE TRUNCATE ON view_receipts
  FOR EACH STATEMENT EXECUTE FUNCTION aegis_forbid_mutation();
