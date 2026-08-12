"""Make the ingress, the egress and the ticket reachable by identity.

Three tables hold patient data that an Art. 17 erasure cannot find:

  intake_events.payload   the whole inbound webhook — raw JID and message text
  send_intents.recipient  the address we answered, plus body_text, the reply
  handoff_state           the ticket, its reason, patient_name and last_message

None of them had a foreign key to anything. The only join to a human was a phone
string inside a JSON blob or a JID — and the spelling of that string is exactly
what diverges between a wa_id and E.164, so a join on it misses the patients it
most needs to find. Erasure would have run, reported success, and left the
patient's own words in the inbox.

This is the single most likely thing to be discovered at the worst moment: the
Phase 6 erasure drill. It is fixed here, before that drill, not during it.

**SET NULL on all three, not CASCADE.** The episodic tables cascade because they
*are* the memory being erased (0004). These three are different: each carries an
idempotency key that has to outlive the person.

  intake_events   UNIQUE (source, source_event_id) — delete the row and a
                  redelivered webhook is processed as new
  send_intents    UNIQUE idempotency_key — delete the row and a re-driven turn
                  sends a message to someone who asked to be forgotten
  handoff_state   the operational record that a human was handed a case

So this migration makes the rows *reachable by key*. Whether erasure then deletes
them or redacts payload / body_text / last_message is Phase 6's decision — the
same one it already owes for turn_log.inbound_text, which has been SET NULL since
0003 for precisely this reason.

The backfill is best-effort and deliberately ordered: the exact join first, the
wa_id fallback only for rows still unmatched, so no row can be claimed by an
arbitrary identity when two could match.

Handoff rows already in flight keep whatever spelling they were created with;
they are not rewritten. `handoff_state` rows expire within hours, and the ones
whose spelling diverged were unclaimable anyway — nobody could take or close
them. Letting them fall out of the mute is the better of the two failures.

Revision ID: 0006
Revises: 0005
"""
from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


UPGRADE = """
ALTER TABLE intake_events
  ADD COLUMN IF NOT EXISTS identity_id UUID REFERENCES identity_registry(id) ON DELETE SET NULL;
ALTER TABLE send_intents
  ADD COLUMN IF NOT EXISTS identity_id UUID REFERENCES identity_registry(id) ON DELETE SET NULL;
ALTER TABLE handoff_state
  ADD COLUMN IF NOT EXISTS identity_id UUID REFERENCES identity_registry(id) ON DELETE SET NULL;

-- "Everything this person sent us", "everything we sent them", "every case a
-- human was handed" — the three questions an erasure and a context package both
-- have to answer.
CREATE INDEX IF NOT EXISTS idx_intake_events_identity
  ON intake_events (identity_id, received_at DESC)
  WHERE identity_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_send_intents_identity
  ON send_intents (identity_id, created_at DESC)
  WHERE identity_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_handoff_state_identity
  ON handoff_state (identity_id, created_at DESC)
  WHERE identity_id IS NOT NULL;

-- -- Backfill ---------------------------------------------------------------
-- Best-effort: rows whose sender never made it into identity_registry stay NULL
-- rather than being guessed at.

UPDATE intake_events e
   SET identity_id = i.id
  FROM identity_registry i
 WHERE e.identity_id IS NULL
   AND i.wa_id IS NOT NULL
   AND split_part(e.payload->'payload'->>'from', '@', 1) = i.wa_id;

UPDATE send_intents s
   SET identity_id = i.id
  FROM identity_registry i
 WHERE s.identity_id IS NULL
   AND i.wa_id IS NOT NULL
   AND split_part(s.recipient, '@', 1) = i.wa_id;

-- Two passes, exact first. An OR across both columns could let one row match two
-- identities, and UPDATE ... FROM would silently pick one of them.
UPDATE handoff_state h
   SET identity_id = i.id
  FROM identity_registry i
 WHERE h.identity_id IS NULL
   AND i.phone_e164 IS NOT NULL
   AND h.contact_phone = i.phone_e164;

UPDATE handoff_state h
   SET identity_id = i.id
  FROM identity_registry i
 WHERE h.identity_id IS NULL
   AND i.wa_id IS NOT NULL
   AND h.contact_phone = '+' || i.wa_id;
"""

DOWNGRADE = """
DROP INDEX IF EXISTS idx_handoff_state_identity;
DROP INDEX IF EXISTS idx_send_intents_identity;
DROP INDEX IF EXISTS idx_intake_events_identity;
ALTER TABLE handoff_state DROP COLUMN IF EXISTS identity_id;
ALTER TABLE send_intents DROP COLUMN IF EXISTS identity_id;
ALTER TABLE intake_events DROP COLUMN IF EXISTS identity_id;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
