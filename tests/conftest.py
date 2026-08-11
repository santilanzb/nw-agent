"""
Shared test environment.

`agent_core.main` reads its settings at import time and builds module-level
singletons, so every test module that imports it must agree on the environment —
whichever imports first wins. Setting it here, before collection, removes that
ordering hazard.

Integration tests expect the local stack:

    docker compose -f docker-compose.yml -f docker-compose.local.yml up -d postgres rag-api crm-adapter
    alembic upgrade head

They skip cleanly when it is not running.
"""
from __future__ import annotations

import os

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://agent:agent@localhost:5432/company_agent"
)

os.environ["DATABASE_URL"] = TEST_DATABASE_URL
# Matches docker-compose.local.yml so the in-process app can reach the containers.
os.environ["INTERNAL_API_KEY"] = os.environ.get("INTERNAL_API_KEY", "local-dev-internal-key")
os.environ["RAG_API_URL"] = os.environ.get("RAG_API_URL", "http://localhost:8081")
os.environ["CRM_ADAPTER_URL"] = os.environ.get("CRM_ADAPTER_URL", "http://localhost:8082")
# No WAHA locally: no signing key exists, so verification is explicitly waived.
# agent-core refuses to boot on an empty key without this, which is the point.
os.environ["WAHA_HOOK_HMAC_KEY"] = ""
os.environ["ALLOW_UNVERIFIED_WEBHOOKS"] = "true"
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")
os.environ.setdefault("HANDOFF_TEAM_GROUP_JID", "120363000000000000@g.us")

# Availability probes live in tests/_stack.py — import them from there.

import pytest


@pytest.fixture(scope="session")
def agent_app():
    """
    The one agent-core app for the whole session.

    Its connection pool is a module-level singleton that can be opened and closed
    exactly once per process — true in production too — so every test module
    shares this client rather than standing up its own. Modules patch what they
    need on `main_mod` and restore it in their own fixtures.

    Only constructed when a test asks for it, so a missing stack skips rather
    than errors.
    """
    from fastapi.testclient import TestClient

    from company_agent.agent_core import main as main_mod

    with TestClient(main_mod.app) as client:
        yield client, main_mod
