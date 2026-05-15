#!/usr/bin/env bash
# Apply sql/004_brain.sql to the running Postgres container.
# Run this on the droplet after deploying Phase 1.
# Usage: bash scripts/apply_brain_sql.sh

set -euo pipefail

CONTAINER="${POSTGRES_CONTAINER:-cs-agent-postgres}"
DB="${POSTGRES_DB:-company_agent}"
USER="${POSTGRES_USER:-agent}"

echo "==> Applying sql/004_brain.sql to $DB ..."
docker exec -i "$CONTAINER" psql -U "$USER" -d "$DB" < sql/004_brain.sql
echo "==> Done."

echo "==> Creating langfuse database if it doesn't exist ..."
docker exec -i "$CONTAINER" psql -U "$USER" -d postgres -c \
  "CREATE DATABASE langfuse OWNER agent;" 2>/dev/null || echo "    (langfuse db already exists)"
echo "==> Done."
