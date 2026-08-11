"""Stage 0 substrate: durable ingress, send outbox, identity, HITL, write ledger,
consent, temporal patient facts, and a corpus visibility flag.

Every table here exists because something in the current system is best-effort:

  intake_events    replaces the in-memory _SEEN dedup, which was per-process and
                   lost on restart, so a WAHA redelivery after a deploy could
                   double-answer a patient.
  send_intents     replaces fire-and-forget sends. A reply that failed its three
                   retries was simply lost, with no record it was ever owed.
  identity_registry replaces last-9-digit phone LIKE with silent rows[0].
  approval_requests the single HITL primitive (unused by ATC; F6/F9 plug in).
  crm_write_log    the WAL that makes Zoho writes replayable and undoable.
  consent_events   purpose-granular consent, required before care-class storage.

Revision ID: 0002
Revises: 0001
"""
from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


UPGRADE = """
-- -- Durable ingress ----------------------------------------------------------
-- The webhook ACKs only after the row lands here, so redelivery and restart are
-- both no-ops: (source, source_event_id) is the dedup key that _SEEN pretended
-- to be. Payload is PHI-bearing and is covered by the retention job.
CREATE TABLE IF NOT EXISTS intake_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source TEXT NOT NULL CHECK (source IN ('waha','meta','manychat','zoho','app','test')),
  source_event_id TEXT NOT NULL,
  payload JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','processing','processed','failed','skipped')),
  attempts INT NOT NULL DEFAULT 0,
  last_error TEXT,
  locked_at TIMESTAMPTZ,
  turn_id UUID,
  received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  processed_at TIMESTAMPTZ,
  UNIQUE (source, source_event_id)
);

-- The sweeper's claim query: FOR UPDATE SKIP LOCKED over this partial index.
CREATE INDEX IF NOT EXISTS idx_intake_events_unprocessed
  ON intake_events (received_at)
  WHERE status IN ('pending','processing');

-- -- Send outbox --------------------------------------------------------------
-- A row is written before any transport call. message_class drives the in-doubt
-- policy: replies and utility may be re-sent, marketing templates never are --
-- they wait for status correlation and then degrade to a human task.
CREATE TABLE IF NOT EXISTS send_intents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  idempotency_key TEXT NOT NULL UNIQUE,
  transport TEXT NOT NULL CHECK (transport IN ('waha','meta_cloud')),
  recipient TEXT NOT NULL,
  message_class TEXT NOT NULL CHECK (message_class IN ('reply','utility','marketing','team')),
  body_ref JSONB NOT NULL DEFAULT '{}'::jsonb,
  body_text TEXT,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','dispatched','confirmed','failed','abandoned')),
  provider_message_id TEXT,
  attempts INT NOT NULL DEFAULT 0,
  last_error TEXT,
  turn_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  dispatched_at TIMESTAMPTZ,
  confirmed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_send_intents_in_doubt
  ON send_intents (created_at)
  WHERE status IN ('pending','dispatched');
CREATE INDEX IF NOT EXISTS idx_send_intents_provider_msg
  ON send_intents (provider_message_id)
  WHERE provider_message_id IS NOT NULL;

-- -- Identity broker ----------------------------------------------------------
-- wa_id is not typed E.164 (Mexico 521/52, Argentina 549, Brazil's legacy ninth
-- digit), which is exactly where the old suffix-LIKE match silently picked the
-- wrong contact. Keys are unique; ambiguous matches go to human review.
CREATE TABLE IF NOT EXISTS identity_registry (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  phone_e164 TEXT UNIQUE,
  wa_id TEXT UNIQUE,
  email_lower TEXT UNIQUE,
  igsid TEXT UNIQUE,
  zoho_module TEXT,
  zoho_record_id TEXT,
  display_name TEXT,
  merge_state TEXT NOT NULL DEFAULT 'active'
    CHECK (merge_state IN ('active','merged','review')),
  merged_into UUID REFERENCES identity_registry(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_identity_registry_zoho
  ON identity_registry (zoho_module, zoho_record_id);
CREATE INDEX IF NOT EXISTS idx_identity_registry_review
  ON identity_registry (created_at) WHERE merge_state = 'review';

-- -- One owned HITL primitive -------------------------------------------------
-- payload_hash + facts_version + TTL are what make an approval safe to execute
-- later: at execute time the payload is recomputed from current facts and a
-- mismatch voids the request rather than sending a stale price.
CREATE TABLE IF NOT EXISTS approval_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  identity_id UUID REFERENCES identity_registry(id),
  kind TEXT NOT NULL CHECK (kind IN ('crm_write','tee_up','discount','quote_send')),
  action TEXT NOT NULL,
  payload JSONB NOT NULL,
  payload_hash TEXT NOT NULL,
  facts_version TEXT,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','approved','rejected','expired','voided','executed')),
  void_reason TEXT,
  requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMPTZ NOT NULL,
  decided_at TIMESTAMPTZ,
  decided_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_approval_requests_open
  ON approval_requests (expires_at) WHERE status = 'pending';

-- -- CRM write-ahead ledger ---------------------------------------------------
-- Zoho has no idempotency-key mechanism and Quotes/Deals/Tasks/Notes have no
-- upsert path, so write_marker is stamped into a custom field and looked up by
-- COQL before any re-create. That lookup is what turns an ambiguous 5xx into
-- adopt-or-create instead of a duplicate record.
CREATE TABLE IF NOT EXISTS crm_write_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  idempotency_key TEXT NOT NULL UNIQUE,
  identity_id UUID REFERENCES identity_registry(id),
  action TEXT NOT NULL,
  module TEXT NOT NULL,
  record_id TEXT,
  write_marker TEXT,
  params JSONB NOT NULL DEFAULT '{}'::jsonb,
  pre_snapshot JSONB,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','succeeded','failed','adopted','compensated')),
  autonomy_tier TEXT NOT NULL DEFAULT 'shadow'
    CHECK (autonomy_tier IN ('shadow','ask_first','auto')),
  approval_id UUID REFERENCES approval_requests(id),
  attempts INT NOT NULL DEFAULT 0,
  last_error TEXT,
  turn_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_crm_write_log_pending
  ON crm_write_log (created_at) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_crm_write_log_marker
  ON crm_write_log (write_marker) WHERE write_marker IS NOT NULL;

-- -- Purpose-granular consent -------------------------------------------------
CREATE TABLE IF NOT EXISTS consent_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  identity_id UUID REFERENCES identity_registry(id),
  purpose TEXT NOT NULL CHECK (purpose IN ('care','sales_use','marketing_contact')),
  granted BOOLEAN NOT NULL,
  source TEXT NOT NULL,
  evidence_turn_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_consent_events_lookup
  ON consent_events (identity_id, purpose, created_at DESC);

-- -- turn_log: data class and provenance --------------------------------------
ALTER TABLE turn_log ADD COLUMN IF NOT EXISTS conversation_class TEXT NOT NULL
  DEFAULT 'care' CHECK (conversation_class IN ('marketing','care'));
ALTER TABLE turn_log ADD COLUMN IF NOT EXISTS intake_event_id UUID;
ALTER TABLE turn_log ADD COLUMN IF NOT EXISTS identity_id UUID;
ALTER TABLE turn_log ADD COLUMN IF NOT EXISTS deterministic_only BOOLEAN NOT NULL DEFAULT false;

-- -- patient_facts: temporal validity -----------------------------------------
-- The (contact_phone, fact_key) primary key meant every upsert overwrote history,
-- so a fact that changed was indistinguishable from one that was never recorded.
-- Facts become append-only; valid_to marks supersession.
ALTER TABLE patient_facts ADD COLUMN IF NOT EXISTS id UUID DEFAULT gen_random_uuid();
ALTER TABLE patient_facts ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE patient_facts ADD COLUMN IF NOT EXISTS valid_to TIMESTAMPTZ;
UPDATE patient_facts SET id = gen_random_uuid() WHERE id IS NULL;
ALTER TABLE patient_facts ALTER COLUMN id SET NOT NULL;
ALTER TABLE patient_facts DROP CONSTRAINT IF EXISTS patient_facts_pkey;
ALTER TABLE patient_facts ADD CONSTRAINT patient_facts_pkey PRIMARY KEY (id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_patient_facts_current
  ON patient_facts (contact_phone, fact_key) WHERE valid_to IS NULL;

-- -- Knowledge visibility -----------------------------------------------------
-- NutriWhite's corpus contains decks explicitly marked "USO INTERNO" (Candida,
-- Desparasitante). Without a structural flag, one bulk sync makes Gutty able to
-- quote internal clinical protocols at a patient. `corpus` stays free for the
-- multi-corpus seam; visibility answers a different question -- who may see it.
ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL
  DEFAULT 'patient' CHECK (visibility IN ('patient','internal'));
ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL
  DEFAULT 'patient' CHECK (visibility IN ('patient','internal'));

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_visibility ON knowledge_chunks (visibility);
"""

DOWNGRADE = """
DROP INDEX IF EXISTS idx_knowledge_chunks_visibility;
ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS visibility;
ALTER TABLE knowledge_documents DROP COLUMN IF EXISTS visibility;

DROP INDEX IF EXISTS uq_patient_facts_current;
ALTER TABLE patient_facts DROP CONSTRAINT IF EXISTS patient_facts_pkey;
ALTER TABLE patient_facts DROP COLUMN IF EXISTS valid_to;
ALTER TABLE patient_facts DROP COLUMN IF EXISTS valid_from;
ALTER TABLE patient_facts DROP COLUMN IF EXISTS id;
ALTER TABLE patient_facts ADD CONSTRAINT patient_facts_pkey PRIMARY KEY (contact_phone, fact_key);

ALTER TABLE turn_log DROP COLUMN IF EXISTS deterministic_only;
ALTER TABLE turn_log DROP COLUMN IF EXISTS identity_id;
ALTER TABLE turn_log DROP COLUMN IF EXISTS intake_event_id;
ALTER TABLE turn_log DROP COLUMN IF EXISTS conversation_class;

DROP TABLE IF EXISTS consent_events;
DROP TABLE IF EXISTS crm_write_log;
DROP TABLE IF EXISTS approval_requests;
DROP TABLE IF EXISTS identity_registry;
DROP TABLE IF EXISTS send_intents;
DROP TABLE IF EXISTS intake_events;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
