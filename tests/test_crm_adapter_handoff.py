"""
Unit tests for the handoff endpoints in crm_adapter/main.py.
Patches handoff_store so no Postgres connection is needed.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Force mock CRM adapter and minimal env so no real credentials are required.
os.environ.setdefault("CRM_PROVIDER", "mock")
os.environ.setdefault("INTERNAL_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql://agent:agent@localhost/company_agent")

from company_agent.common.handoff_state import HandoffStateRecord
from company_agent.crm_adapter.main import app, handoff_store, settings


def _record(**overrides: object) -> HandoffStateRecord:
    base = {
        "id": "abc-123",
        "contact_phone": "+584241329676",
        "contact_id": None,
        "patient_name": "Ana García",
        "conversation_id": None,
        "status": "pending",
        "reason": "specialist_recommendation",
        "priority": "high",
        "last_message": "necesito un especialista",
        "zoho_note_id": None,
        "claimed_by_phone": None,
        "claimed_by_name": None,
        "created_at": datetime.now(UTC),
        "claimed_at": None,
        "resumed_at": None,
        "expires_at": datetime.now(UTC),
    }
    return HandoffStateRecord(**{**base, **overrides})  # type: ignore[arg-type]


@pytest.fixture
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
        created_at=datetime.now(UTC),
        claimed_at=None,
        resumed_at=None,
        expires_at=datetime.now(UTC),
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


# ── A handoff with no phone ──────────────────────────────────────────────────

PHONELESS_BODIES = [
    ("the key is missing entirely", {}),
    ("an empty string", {"contact_phone": ""}),
    ("only whitespace", {"contact_phone": "   "}),
    ("no digits at all", {"contact_phone": "sin número"}),
]


@pytest.mark.parametrize(("label", "extra"), PHONELESS_BODIES)
def test_a_phoneless_handoff_is_refused_before_zoho_is_touched(
    client: TestClient, label: str, extra: dict
) -> None:
    """
    This used to return 200, log a warning and skip the state row: an escalation
    that left an audit Note in the CRM and never muted Gutty — which reads, from
    the patient's side, as the bot talking over the asesora who just picked up.

    The rejection has to happen at the model, not in the endpoint body. The Zoho
    Note is written on the first line of that body, so a check placed after it
    would 4xx *and* leave an orphan Note, which `postJsonWithRetry` in the
    OpenClaw plugin then duplicates.
    """
    with patch("company_agent.crm_adapter.main.adapter") as never_touched:
        resp = client.post(
            "/v1/handoff",
            json={"reason": "el paciente necesita una asesora", **extra},
            headers=_auth_header(),
        )

    assert resp.status_code == 422, f"{label}: {resp.text}"
    never_touched.handoff.assert_not_called()


def test_a_handoff_with_a_phone_still_opens_a_ticket(client: TestClient) -> None:
    """The other half of the contract: the happy path is untouched."""
    with patch.object(handoff_store, "create", return_value=_record()) as create:
        resp = client.post(
            "/v1/handoff",
            json={
                "contact_phone": "+584241329676",
                "reason": "el paciente necesita una asesora",
            },
            headers=_auth_header(),
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "pending"
    create.assert_called_once()


def test_the_stored_phone_is_canonical_whatever_the_caller_sent(client: TestClient) -> None:
    """
    An Argentine wa_id arrives without the mobile 9. The row must be keyed on the
    form the team command resolves, or nobody can claim the case.
    """
    with patch.object(handoff_store, "create", return_value=_record()) as create:
        client.post(
            "/v1/handoff",
            json={
                "contact_phone": "+541123456789",
                "reason": "el paciente necesita una asesora",
            },
            headers=_auth_header(),
        )

    assert create.call_args.kwargs["contact_phone"] == "+5491123456789"
