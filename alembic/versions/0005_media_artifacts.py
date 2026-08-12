"""Record inbound media so it can be found, and erased.

Patients send payment proofs as photos and questions as voice notes. Stage 0
stopped the transport dropping them silently, but the FSM still only
acknowledged them — the asesora received the word "[image]" and had to go find
the actual receipt in WhatsApp herself.

Storing the bytes creates a new store of patient data, which is the reason this
is a table and not just a directory. Art. 17 erasure enumerates stores keyed on
`identity_registry`; a folder of files nobody has a row for is exactly the store
an erasure drill discovers too late. The row carries the path, never the bytes.

`sha256` is here so the same receipt sent twice does not become two artifacts,
and so an erasure can prove what it deleted.

Revision ID: 0005
Revises: 0004
"""
from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


UPGRADE = """
CREATE TABLE IF NOT EXISTS media_artifacts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  identity_id UUID REFERENCES identity_registry(id) ON DELETE CASCADE,
  turn_id UUID,
  source TEXT NOT NULL,
  provider_media_id TEXT,
  kind TEXT NOT NULL,
  mime_type TEXT,
  byte_size BIGINT,
  sha256 TEXT,
  -- Path within the media volume. The bytes never enter Postgres: they would
  -- bloat every backup of a database that is otherwise all short text.
  storage_path TEXT NOT NULL,
  caption TEXT,
  status TEXT NOT NULL DEFAULT 'stored'
    CHECK (status IN ('stored','fetch_failed','purged')),
  last_error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  purged_at TIMESTAMPTZ
);

-- The erasure query, and the asesora's "what did this patient send me".
CREATE INDEX IF NOT EXISTS idx_media_artifacts_identity
  ON media_artifacts (identity_id, created_at DESC)
  WHERE identity_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_media_artifacts_turn
  ON media_artifacts (turn_id);

-- Retention sweeps by age over rows that still hold bytes.
CREATE INDEX IF NOT EXISTS idx_media_artifacts_unpurged
  ON media_artifacts (created_at)
  WHERE status = 'stored';

-- The same receipt sent twice is one artifact.
CREATE UNIQUE INDEX IF NOT EXISTS uq_media_artifacts_content
  ON media_artifacts (identity_id, sha256)
  WHERE identity_id IS NOT NULL AND sha256 IS NOT NULL;
"""

DOWNGRADE = """
DROP TABLE IF EXISTS media_artifacts;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
