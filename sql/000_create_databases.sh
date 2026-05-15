#!/bin/bash
# Creates the langfuse database on fresh Postgres initialization.
# The || true prevents failure if it already exists.
set -e
psql -U "$POSTGRES_USER" -c "CREATE DATABASE langfuse OWNER $POSTGRES_USER;" 2>/dev/null || true
