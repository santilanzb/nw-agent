-- Per-contact handoff state for the Gutty agent.
-- Lifecycle: pending → claimed → resumed (or expired after 24h).
--
-- The state is consulted by the agent on every patient turn via
-- `check_handoff_state` so it can stay silent while a human is on the line.
-- Apply manually after pulling: psql "$DATABASE_URL" -f sql/002_handoff_state.sql

CREATE TABLE IF NOT EXISTS handoff_state (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Patient identity ----------------------------------------------------------
  contact_phone TEXT NOT NULL,           -- E.164, e.g. +584145610594
  contact_id TEXT,                       -- Zoho Contact record id (if known)
  patient_name TEXT,                     -- denormalized for fast lookups
  conversation_id TEXT,                  -- OpenClaw session key / WhatsApp chat

  -- Lifecycle -----------------------------------------------------------------
  status TEXT NOT NULL DEFAULT 'pending' -- pending | claimed | resumed | expired
    CHECK (status IN ('pending', 'claimed', 'resumed', 'expired')),
  reason TEXT,
  priority TEXT NOT NULL DEFAULT 'normal'
    CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
  last_message TEXT,                     -- patient's last message at handoff time

  -- Audit references ----------------------------------------------------------
  zoho_note_id TEXT,                     -- the Note we created on the Contact

  -- Claim ---------------------------------------------------------------------
  claimed_by_phone TEXT,                 -- logistics member phone (E.164)
  claimed_by_name TEXT,                  -- friendly name shown to patient

  -- Timestamps ----------------------------------------------------------------
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  claimed_at TIMESTAMPTZ,
  resumed_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '24 hours')
);

-- Fast lookup by phone (the hot path: every patient message hits this)
CREATE INDEX IF NOT EXISTS idx_handoff_state_phone_active
  ON handoff_state (contact_phone)
  WHERE status IN ('pending', 'claimed');

-- For sweeping expired rows
CREATE INDEX IF NOT EXISTS idx_handoff_state_expires
  ON handoff_state (expires_at)
  WHERE status IN ('pending', 'claimed');

-- For ops queries / dashboards
CREATE INDEX IF NOT EXISTS idx_handoff_state_status_created
  ON handoff_state (status, created_at DESC);
