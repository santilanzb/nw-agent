"""
Unit tests for the handoff_state_check endpoint in crm_adapter/main.py.
Patches handoff_store.check_active so no Postgres connection is needed.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Force mock CRM adapter and minimal env so no real credentials are required.
os.environ.setdefault("CRM_PROVIDER", "mock")
os.environ.setdefault("INTERNAL_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql://agent:agent@localhost/company_agent")

from company_agent.crm_adapter.main import app, handoff_store, settings  # noqa: E402
from company_agent.common.handoff_state import HandoffStateRecord  # noqa: E402


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _auth_header() -> dict[str, str]:
    return {"X-Internal-API-Key": settings.internal_api_key or "test-key"}


def test_no_active_handoff_echoes_contact_phone(client: TestClient) -> None:
    """When check_active returns None, contact_phone must mirror the request body."""
    with patch.object(handoff_store, "check_active", return_value=None):
        resp = client.post(
            "/v1/handoff/state/check",
            json={"contact_phone": "+584241329676"},
            headers=_auth_header(),
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] is False
    assert body["contact_phone"] == "+584241329676"


def test_no_active_handoff_echoes_different_phone(client: TestClient) -> None:
    """Phone echo works for any phone, not just the test number."""
    with patch.object(handoff_store, "check_active", return_value=None):
        resp = client.post(
            "/v1/handoff/state/check",
            json={"contact_phone": "+14155550100"},
            headers=_auth_header(),
        )
    assert resp.status_code == 200
    assert resp.json()["contact_phone"] == "+14155550100"


def test_active_handoff_returns_record_phone(client: TestClient) -> None:
    """Active handoff path: phone comes from the DB record, not request."""
    record = HandoffStateRecord(
        id="abc-123",
        contact_phone="+584241329676",
        contact_id=None,
        patient_name="Ana García",
        conversation_id=None,
        status="pending",
        reason="specialist_recommendation",
        priority="high",
        last_message="necesito un especialista",
        zoho_note_id=None,
        claimed_by_phone=None,
        claimed_by_name=None,
        created_at=datetime.now(timezone.utc),
        claimed_at=None,
        resumed_at=None,
        expires_at=datetime.now(timezone.utc),
    )
    with patch.object(handoff_store, "check_active", return_value=record):
        resp = client.post(
            "/v1/handoff/state/check",
            json={"contact_phone": "+584241329676"},
            headers=_auth_header(),
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] is True
    assert body["contact_phone"] == "+584241329676"
    assert body["status"] == "pending"
