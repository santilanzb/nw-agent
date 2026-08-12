"""Make turn_log.identity_id a real key.

0002 added the column and nothing else: no foreign key, no index, and no writer.
It has been NULL on every row since it existed.

That matters for one thing above all — Art. 17 erasure has to enumerate
everything held about one person, and today `turn_log`'s only link to a human is
`sha256(phone)`. The hash changes when the phone string changes, so a patient
whose number reached us in two formats (a Mexican `521...` once and a `+52...`
once) has two unrelated histories and no way to join them. `identity_registry`
is the key that survives reformatting; this makes the column usable as one.

The FK is ON DELETE SET NULL rather than CASCADE deliberately. Erasure scrubs
`turn_log` rows on its own terms — deleting an identity must not silently delete
the turn history that the erasure audit trail is measured against.

Revision ID: 0003
Revises: 0002
"""
from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


UPGRADE = """
-- Existing rows all have identity_id IS NULL, so the constraint is satisfiable
-- without a backfill. Historical turns stay unlinked: their phone_hash cannot be
-- reversed to a number, which is the property that made hashing worth doing.
ALTER TABLE turn_log
  DROP CONSTRAINT IF EXISTS turn_log_identity_id_fkey;

ALTER TABLE turn_log
  ADD CONSTRAINT turn_log_identity_id_fkey
  FOREIGN KEY (identity_id) REFERENCES identity_registry(id) ON DELETE SET NULL;

-- The erasure query is "every turn for this identity, newest first".
CREATE INDEX IF NOT EXISTS idx_turn_log_identity
  ON turn_log (identity_id, created_at DESC)
  WHERE identity_id IS NOT NULL;

-- Answering "which conversations need a human to disambiguate them" without a
-- sequential scan once the table has volume.
CREATE INDEX IF NOT EXISTS idx_identity_registry_wa_id
  ON identity_registry (wa_id)
  WHERE wa_id IS NOT NULL;
"""

DOWNGRADE = """
DROP INDEX IF EXISTS idx_identity_registry_wa_id;
DROP INDEX IF EXISTS idx_turn_log_identity;
ALTER TABLE turn_log DROP CONSTRAINT IF EXISTS turn_log_identity_id_fkey;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
