"""
End-to-end ingress tests against the real app and a real Postgres.

The property under test is the one that made messages disappear: the webhook must
not acknowledge anything it has not made durable, and a redelivery must do
nothing at all.
"""
from __future__ import annotations

import time
import uuid

import pytest
from _stack import SKIP_DB, db_available, db_url

DB_URL = db_url()

pytestmark = pytest.mark.skipif(not db_available(), reason=SKIP_DB)


def _waha_body(event_id: str, text: str = "hola", msg_type: str = "chat") -> dict:
    return {
        "event": "message",
        "payload": {
            "id": event_id,
            "from": "584145610594@c.us",
            "body": text,
            "type": msg_type,
            "fromMe": False,
            "isGroup": False,
            "timestamp": 1760000000,
            "_data": {"notifyName": "Paciente"},
        },
    }


def _count_rows(event_id: str) -> int:
    import psycopg

    with psycopg.connect(DB_URL) as conn:
        cur = conn.execute(
            "select count(*) from intake_events where source_event_id = %s", (event_id,)
        )
        return cur.fetchone()[0]


def _status(event_id: str) -> str | None:
    import psycopg

    with psycopg.connect(DB_URL) as conn:
        cur = conn.execute(
            "select status from intake_events where source_event_id = %s", (event_id,)
        )
        row = cur.fetchone()
        return row[0] if row else None


def _wait_for_status(event_id: str, wanted: str, timeout: float = 5.0) -> str | None:
    deadline = time.monotonic() + timeout
    seen = None
    while time.monotonic() < deadline:
        seen = _status(event_id)
        if seen == wanted:
            return seen
        time.sleep(0.05)
    return seen


@pytest.fixture(scope="module")
def app_client(agent_app):
    """
    Ingress-only view of the shared app: the FSM is stubbed so these tests assert
    what the webhook durably records, not what a turn produces.
    """
    client, main_mod = agent_app
    handled: list = []

    async def fake_handle(event) -> None:
        handled.append(event)

    original = main_mod.fsm.handle
    main_mod.fsm.handle = fake_handle
    try:
        yield client, handled
    finally:
        main_mod.fsm.handle = original


def test_webhook_persists_before_acking_and_redelivery_is_inert(app_client) -> None:
    client, handled = app_client
    handled.clear()

    event_id = f"e2e-{uuid.uuid4()}"
    body = _waha_body(event_id)

    first = client.post("/webhooks/waha", json=body)
    second = client.post("/webhooks/waha", json=body)
    third = client.post("/webhooks/waha", json=body)
    final = _wait_for_status(event_id, "processed")

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 200

    # Durable exactly once, however many times WAHA redelivers it.
    assert _count_rows(event_id) == 1
    # And handled exactly once — the old _SEEN cache could not promise this
    # across a restart.
    assert [e.source_event_id for e in handled] == [event_id]
    assert final == "processed"


def test_media_message_is_no_longer_dropped(app_client) -> None:
    """waha.py:42 used to return None for every image, so payment proofs vanished."""
    client, handled = app_client
    handled.clear()

    event_id = f"e2e-media-{uuid.uuid4()}"
    body = _waha_body(event_id, text="", msg_type="image")
    body["payload"]["media"] = {
        "url": "https://example.invalid/pago.jpg",
        "mimetype": "image/jpeg",
    }
    body["payload"]["_data"]["caption"] = "aquí está mi pago"

    resp = client.post("/webhooks/waha", json=body)
    _wait_for_status(event_id, "processed")

    assert resp.status_code == 200
    assert _count_rows(event_id) == 1
    assert len(handled) == 1
    event = handled[0]
    assert event.media is not None
    assert event.media.kind == "image"
    assert event.media.mime_type == "image/jpeg"
    # The caption is the patient's actual words and becomes the turn text.
    assert event.text == "aquí está mi pago"


def test_non_message_events_are_not_inboxed(app_client) -> None:
    client, _ = app_client
    resp = client.post("/webhooks/waha", json={"event": "session.status", "payload": {}})
    assert resp.status_code == 204


def test_malformed_json_is_rejected(app_client) -> None:
    client, _ = app_client
    resp = client.post(
        "/webhooks/waha",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400


def test_message_without_an_id_is_not_inboxed(app_client) -> None:
    """No id means no dedup key; inboxing it would defeat the whole mechanism."""
    client, _ = app_client
    body = _waha_body("")
    body["payload"]["id"] = ""
    resp = client.post("/webhooks/waha", json=body)
    assert resp.status_code == 204
