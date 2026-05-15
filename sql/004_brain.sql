-- Phase 1: turn_log — analytics-only, phone is hashed
-- Phase 3: patient_episodes, episode_summaries, patient_facts, learning_queue
-- All tables use IF NOT EXISTS so this file can be run multiple times safely.

CREATE TABLE IF NOT EXISTS turn_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  turn_id UUID NOT NULL UNIQUE,
  phone_hash TEXT NOT NULL,               -- sha256(phone), never raw phone
  inbound_text TEXT NOT NULL,
  classified_intent TEXT,
  confidence NUMERIC(5,4),
  decision TEXT,
  dispatch_tool TEXT,
  dispatch_params JSONB,
  task TEXT,
  task_outcome TEXT                       -- 'replied' | 'silent' | 'handoff' | 'error'
    CHECK (task_outcome IN ('replied','silent','handoff','error') OR task_outcome IS NULL),
  composed_by_llm BOOLEAN NOT NULL DEFAULT false,
  model_used TEXT,
  composition_tokens_in INT,
  composition_tokens_out INT,
  latency_ms INT,
  reply_text TEXT,                        -- cleared on retention cycle
  follow_up_within_minutes INT,           -- implicit feedback: patient re-messaged within 30 min
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

CREATE INDEX IF NOT EXISTS idx_turn_log_decision_conf
  ON turn_log (decision, confidence);

CREATE INDEX IF NOT EXISTS idx_turn_log_unreviewed
  ON turn_log (review_status, created_at)
  WHERE review_status = 'unreviewed';

CREATE INDEX IF NOT EXISTS idx_turn_log_phone_hash
  ON turn_log (phone_hash, created_at DESC);

-- ── Phase 3 tables ────────────────────────────────────────────────────────────

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

CREATE INDEX IF NOT EXISTS idx_patient_episodes_turn
  ON patient_episodes (turn_id);

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
  ON episode_summaries USING HNSW (embedding vector_cosine_ops)
  WHERE embedding IS NOT NULL;

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
  kind TEXT NOT NULL CHECK (kind IN ('reseed','new_intent','new_condition','new_entity','prompt_fix')),
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
  ON learning_queue (status, created_at)
  WHERE status = 'pending';
