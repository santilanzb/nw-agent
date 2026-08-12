"""Key the episodic tables on identity, while they are still empty.

`patient_episodes`, `episode_summaries` and `patient_facts` have had schemas
since the baseline and zero readers or writers — grep across src/ returns
nothing. The next commit gives them their first, so this is the last moment
re-keying them is free. After they hold conversation history it is a backfill
against data whose only join to a human is a phone string.

They keyed on raw `contact_phone`, which is the same weakness `turn_log` had: the
value changes when the formatting does, so one patient reaching us in two forms
gets two unrelated memories. `contact_phone` is kept — operators search by phone,
and dropping it would make the tables unreadable by hand — but it stops being
the key.

`patient_facts` is the delicate one: its current-fact uniqueness is a partial
index on (contact_phone, fact_key) WHERE valid_to IS NULL, added by 0002. That
index has to be rebuilt on the new key or two identities could hold contradictory
current values for the same fact.

Revision ID: 0004
Revises: 0003
"""
from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


UPGRADE = """
ALTER TABLE patient_episodes
  ADD COLUMN IF NOT EXISTS identity_id UUID REFERENCES identity_registry(id) ON DELETE CASCADE;
ALTER TABLE episode_summaries
  ADD COLUMN IF NOT EXISTS identity_id UUID REFERENCES identity_registry(id) ON DELETE CASCADE;
ALTER TABLE patient_facts
  ADD COLUMN IF NOT EXISTS identity_id UUID REFERENCES identity_registry(id) ON DELETE CASCADE;

-- CASCADE here, unlike turn_log's SET NULL. turn_log is the audit trail that
-- erasure is measured against and must outlive the identity; conversation
-- memory is the thing being erased.

-- The read on every composed turn: "the last N turns of this conversation".
CREATE INDEX IF NOT EXISTS idx_patient_episodes_identity
  ON patient_episodes (identity_id, created_at DESC)
  WHERE identity_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_episode_summaries_identity
  ON episode_summaries (identity_id, window_end DESC)
  WHERE identity_id IS NOT NULL;

-- Current-fact uniqueness moves onto the identity. The phone-keyed index stays
-- for now: both are partial and neither blocks the other while the tables are
-- empty, and dropping it is a separate decision once facts have a writer.
CREATE UNIQUE INDEX IF NOT EXISTS uq_patient_facts_current_identity
  ON patient_facts (identity_id, fact_key)
  WHERE valid_to IS NULL AND identity_id IS NOT NULL;
"""

DOWNGRADE = """
DROP INDEX IF EXISTS uq_patient_facts_current_identity;
DROP INDEX IF EXISTS idx_episode_summaries_identity;
DROP INDEX IF EXISTS idx_patient_episodes_identity;
ALTER TABLE patient_facts DROP COLUMN IF EXISTS identity_id;
ALTER TABLE episode_summaries DROP COLUMN IF EXISTS identity_id;
ALTER TABLE patient_episodes DROP COLUMN IF EXISTS identity_id;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
