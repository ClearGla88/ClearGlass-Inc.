-- ClearGlass Agent Office: the Revenue Floor (packages/revenue_ops).
--
-- Applies on top of 003_plan_first_mode.sql; no earlier file is edited.
--
-- Invariants enforced by the database, not only by application code:
--   * money_events, suppressions, offer_decisions and external_action_receipts reject
--     UPDATE, DELETE and TRUNCATE.
--   * Money is "received" only on a processor record; a payment marked as paid by hand
--     is only ever "reported".
--   * One provider record is counted once: (provider, record_type, external_ref, kind) is unique.
--   * One external reference (a message id, an invoice id) belongs to one action.
--   * One approval drives at most one external action.
--   * A released action carries its ticket; an executed one carries its receipt.

BEGIN;

CREATE TABLE opportunities (
    id              text PRIMARY KEY,
    stage           text NOT NULL
                    CHECK (stage IN ('new','qualified','disqualified','contacted','engaged','proposal_sent',
                                     'accepted','invoiced','paid','in_fulfillment','lost')),
    rehearsal       boolean NOT NULL DEFAULT false,
    source          text NOT NULL,
    source_ref      text NOT NULL,
    contact         jsonb NOT NULL,
    consent         jsonb NOT NULL,
    lead_facts      jsonb NOT NULL DEFAULT '{}',
    offer_sku       text,
    offer_digest    char(64) CHECK (offer_digest IS NULL OR offer_digest ~ '^[0-9a-f]{64}$'),
    priority        smallint NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
    qualification   jsonb NOT NULL DEFAULT '{}',
    research        jsonb NOT NULL DEFAULT '{}',
    drafts          jsonb NOT NULL DEFAULT '{}',
    terms           jsonb NOT NULL DEFAULT '{}',
    fulfillment     jsonb NOT NULL DEFAULT '{}',
    timeline        jsonb NOT NULL DEFAULT '[]',
    flags           jsonb NOT NULL DEFAULT '[]',
    lost_reason     text,
    content_version integer NOT NULL DEFAULT 1 CHECK (content_version >= 1),
    created_by      text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source, source_ref),
    CHECK (stage <> 'lost' OR lost_reason IS NOT NULL)
);
CREATE INDEX opportunities_stage_idx ON opportunities(stage);

CREATE TABLE external_actions (
    id             text PRIMARY KEY,
    opportunity_id text NOT NULL REFERENCES opportunities(id),
    kind           text NOT NULL CHECK (kind IN ('outreach_email','proposal_email','invoice')),
    action_type    text NOT NULL CHECK (action_type IN ('outreach.send','proposal.send','invoice.send')),
    agent_id       text NOT NULL REFERENCES agents(id),
    connector      text NOT NULL CHECK (connector IN ('gmail','microsoft_365','paypal')),
    payload        jsonb NOT NULL,
    payload_digest char(64) NOT NULL CHECK (payload_digest ~ '^[0-9a-f]{64}$'),
    record_version integer NOT NULL CHECK (record_version >= 1),
    status         text NOT NULL DEFAULT 'awaiting_approval'
                   CHECK (status IN ('awaiting_approval','approved','released','executed','verified',
                                     'verification_failed','rejected','expired','cancelled','stale','blocked','abandoned')),
    approval_id    text REFERENCES approvals(id),
    rehearsal      boolean NOT NULL DEFAULT false,
    ticket         jsonb,
    receipt        jsonb,
    verification   jsonb,
    error          text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    CHECK (status NOT IN ('released','executed','verified','verification_failed') OR ticket IS NOT NULL),
    CHECK (status NOT IN ('executed','verified','verification_failed') OR receipt IS NOT NULL)
);
CREATE INDEX external_actions_opportunity_idx ON external_actions(opportunity_id);
CREATE INDEX external_actions_agent_idx ON external_actions(agent_id);
CREATE UNIQUE INDEX external_actions_one_per_approval ON external_actions(approval_id) WHERE approval_id IS NOT NULL;

CREATE TABLE external_action_receipts (
    connector    text NOT NULL,
    external_ref text NOT NULL CHECK (external_ref <> ''),
    action_id    text NOT NULL REFERENCES external_actions(id),
    recorded_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (connector, external_ref)
);
CREATE INDEX external_action_receipts_action_idx ON external_action_receipts(action_id);

CREATE TABLE money_events (
    seq             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id        text NOT NULL UNIQUE,
    opportunity_id  text NOT NULL,           -- an opportunity id, or 'company' for a company-level cost
    kind            text NOT NULL
                    CHECK (kind IN ('proposal_issued','terms_accepted','invoice_issued','invoice_cancelled',
                                    'payment_pending','payment_received','payment_reported','payment_failed',
                                    'refund','dispute_opened','dispute_closed','fee','operating_cost')),
    amount_cents    bigint NOT NULL CHECK (amount_cents >= 0),
    currency        char(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    provider        text NOT NULL,
    record_type     text NOT NULL,
    external_ref    text NOT NULL CHECK (external_ref <> ''),
    provider_status text NOT NULL,
    verification    text NOT NULL
                    CHECK (verification IN ('provider_record','operator_receipt','operator_attested','unverified')),
    evidence        text NOT NULL,
    raw_digest      char(64) CHECK (raw_digest IS NULL OR raw_digest ~ '^[0-9a-f]{64}$'),
    rehearsal       boolean NOT NULL DEFAULT false,
    occurred_at     timestamptz NOT NULL,
    recorded_by     text NOT NULL,
    recorded_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, record_type, external_ref, kind),
    CHECK (kind <> 'payment_received' OR verification = 'provider_record'),
    CHECK (kind <> 'payment_reported' OR verification = 'unverified')
);
CREATE INDEX money_events_opportunity_idx ON money_events(opportunity_id);

CREATE TABLE suppressions (
    seq         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    address     text NOT NULL CHECK (address = lower(address) AND address LIKE '%@%'),
    reason      text NOT NULL,
    source_ref  text NOT NULL,
    recorded_by text NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX suppressions_address_idx ON suppressions(address);

CREATE TABLE offer_decisions (
    seq          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sku          text NOT NULL,
    decision     text NOT NULL CHECK (decision IN ('approve','reject','retire')),
    offer        jsonb NOT NULL,
    offer_digest char(64) NOT NULL CHECK (offer_digest ~ '^[0-9a-f]{64}$'),
    reason       text NOT NULL CHECK (length(reason) >= 12),
    decided_by   text NOT NULL,
    decided_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX offer_decisions_sku_idx ON offer_decisions(sku);

-- An offer decision is a human act: refuse one recorded in an agent's name.
CREATE FUNCTION offer_decision_by_human() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM agents WHERE id = NEW.decided_by) THEN
        RAISE EXCEPTION 'offer decisions are made by a human operator, not by agent %', NEW.decided_by
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER offer_decisions_by_human BEFORE INSERT ON offer_decisions
    FOR EACH ROW EXECUTE FUNCTION offer_decision_by_human();

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['money_events', 'suppressions', 'offer_decisions', 'external_action_receipts'] LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION reject_mutation()',
                       t || '_no_mutation', t);
        EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation()',
                       t || '_no_truncate', t);
    END LOOP;
END $$;

COMMIT;
