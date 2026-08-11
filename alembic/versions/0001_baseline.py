"""Baseline: freeze the initdb SQL as revision 0001.

Reproduces sql/001_init.sql, 002_handoff_state.sql, 003_intent_vectors.sql and
004_brain.sql exactly. Every statement is idempotent, so this is safe to run
against a database that docker-entrypoint-initdb.d already built.

On the droplet, where the schema already exists, prefer:

    alembic stamp 0001

The sql/*.sql files stay in place because docker-entrypoint-initdb.d still uses
them to bootstrap a fresh local database. They are frozen from here on: schema
changes go in a new migration, never by editing those files.

Revision ID: 0001
Revises:
"""
from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


BASELINE = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- -- 001_init.sql -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS knowledge_documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_uri TEXT NOT NULL UNIQUE,
  source_type TEXT NOT NULL,
  title TEXT NOT NULL,
  content_md TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
  corpus TEXT NOT NULL DEFAULT 'default',
  chunk_index INTEGER NOT NULL,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  source_uri TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  embedding VECTOR(1536),
  search_tsv TSVECTOR GENERATED ALWAYS AS (
    to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(content, ''))
  ) STORED,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document_id ON knowledge_chunks (document_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_corpus ON knowledge_chunks (corpus);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_metadata ON knowledge_chunks USING GIN (metadata);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_search_tsv ON knowledge_chunks USING GIN (search_tsv);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding_hnsw
  ON knowledge_chunks USING HNSW (embedding vector_cosine_ops);

-- -- 002_handoff_state.sql ----------------------------------------------------
CREATE TABLE IF NOT EXISTS handoff_state (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  contact_phone TEXT NOT NULL,
  contact_id TEXT,
  patient_name TEXT,
  conversation_id TEXT,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'claimed', 'resumed', 'expired')),
  reason TEXT,
  priority TEXT NOT NULL DEFAULT 'normal'
    CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
  last_message TEXT,
  zoho_note_id TEXT,
  claimed_by_phone TEXT,
  claimed_by_name TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  claimed_at TIMESTAMPTZ,
  resumed_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '24 hours')
);

CREATE INDEX IF NOT EXISTS idx_handoff_state_phone_active
  ON handoff_state (contact_phone) WHERE status IN ('pending', 'claimed');
CREATE INDEX IF NOT EXISTS idx_handoff_state_expires
  ON handoff_state (expires_at) WHERE status IN ('pending', 'claimed');
CREATE INDEX IF NOT EXISTS idx_handoff_state_status_created
  ON handoff_state (status, created_at DESC);

-- -- 003_intent_vectors.sql ---------------------------------------------------
CREATE TABLE IF NOT EXISTS intent_vectors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  intent_class TEXT NOT NULL,
  example_text TEXT NOT NULL,
  language TEXT NOT NULL DEFAULT 'es',
  embedding VECTOR(1536),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (intent_class, example_text, language)
);

CREATE INDEX IF NOT EXISTS idx_intent_vectors_class ON intent_vectors (intent_class);
CREATE INDEX IF NOT EXISTS idx_intent_vectors_embedding_hnsw
  ON intent_vectors USING HNSW (embedding vector_cosine_ops);

-- -- 004_brain.sql ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS turn_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  turn_id UUID NOT NULL UNIQUE,
  phone_hash TEXT NOT NULL,
  inbound_text TEXT NOT NULL,
  classified_intent TEXT,
  confidence NUMERIC(5,4),
  decision TEXT,
  dispatch_tool TEXT,
  dispatch_params JSONB,
  task TEXT,
  task_outcome TEXT
    CHECK (task_outcome IN ('replied','silent','handoff','error') OR task_outcome IS NULL),
  composed_by_llm BOOLEAN NOT NULL DEFAULT false,
  model_used TEXT,
  composition_tokens_in INT,
  composition_tokens_out INT,
  latency_ms INT,
  reply_text TEXT,
  follow_up_within_minutes INT,
  handoff_fired BOOLEAN NOT NULL DEFAULT false,
  graph_used BOOLEAN NOT NULL DEFAULT false,
  episodic_used BOOLEAN NOT NULL DEFAULT false,
  review_status TEXT NOT NULL DEFAULT 'unreviewed'
    CHECK (review_status IN ('unreviewed','accepted','rejected','reseed_pending','reseed_done')),
  reviewer TEXT,
  review_notes TEXT,
  reviewed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_turn_log_decision_conf ON turn_log (decision, confidence);
CREATE INDEX IF NOT EXISTS idx_turn_log_unreviewed
  ON turn_log (review_status, created_at) WHERE review_status = 'unreviewed';
CREATE INDEX IF NOT EXISTS idx_turn_log_phone_hash ON turn_log (phone_hash, created_at DESC);

CREATE TABLE IF NOT EXISTS patient_episodes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  contact_phone TEXT NOT NULL,
  contact_id TEXT,
  direction TEXT NOT NULL CHECK (direction IN ('inbound','outbound')),
  text TEXT NOT NULL,
  intent TEXT,
  confidence NUMERIC(5,4),
  decision TEXT,
  task TEXT,
  composed_by_llm BOOLEAN NOT NULL DEFAULT false,
  model_used TEXT,
  turn_id UUID NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_patient_episodes_phone_time
  ON patient_episodes (contact_phone, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_patient_episodes_turn ON patient_episodes (turn_id);

CREATE TABLE IF NOT EXISTS episode_summaries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  contact_phone TEXT NOT NULL,
  summary TEXT NOT NULL,
  window_start TIMESTAMPTZ NOT NULL,
  window_end TIMESTAMPTZ NOT NULL,
  turn_count INT NOT NULL,
  embedding VECTOR(1536),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_episode_summaries_phone
  ON episode_summaries (contact_phone, window_end DESC);
CREATE INDEX IF NOT EXISTS idx_episode_summaries_embedding
  ON episode_summaries USING HNSW (embedding vector_cosine_ops) WHERE embedding IS NOT NULL;

CREATE TABLE IF NOT EXISTS patient_facts (
  contact_phone TEXT NOT NULL,
  fact_key TEXT NOT NULL,
  fact_value TEXT NOT NULL,
  confidence NUMERIC(5,4) NOT NULL DEFAULT 1.0,
  learned_from_turn_id UUID,
  learned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (contact_phone, fact_key)
);

CREATE TABLE IF NOT EXISTS learning_queue (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_turn_id UUID REFERENCES turn_log(turn_id),
  kind TEXT NOT NULL
    CHECK (kind IN ('reseed','new_intent','new_condition','new_entity','prompt_fix')),
  proposed_payload JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','approved','rejected','applied')),
  proposer TEXT,
  reviewer TEXT,
  reviewed_at TIMESTAMPTZ,
  applied_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_learning_queue_pending
  ON learning_queue (status, created_at) WHERE status = 'pending';
"""


def upgrade() -> None:
    op.execute(BASELINE)


def downgrade() -> None:
    raise RuntimeError(
        "Refusing to downgrade past the baseline: this would drop the knowledge "
        "corpus, the handoff state machine and every logged turn."
    )
