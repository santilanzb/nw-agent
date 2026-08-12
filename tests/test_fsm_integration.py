"""
Full-path integration: webhook -> inbox -> FSM -> real classifier -> task ->
real handoff -> outbox.

Everything here is real except the two things that leave the machine: the WhatsApp
transport (captured) and the LLM (booby-trapped, because none of these paths may
compose). That makes this the test that would actually catch a broken ATC turn.

Needs the local stack:
    docker compose -f docker-compose.yml -f docker-compose.local.yml up -d postgres rag-api crm-adapter
"""
from __future__ import annotations

import random
import time

import psycopg
import pytest
from _stack import SKIP_STACK, db_url, stack_available

pytestmark = pytest.mark.skipif(not stack_available(), reason=SKIP_STACK)

TEAM_GROUP = "120363000000000000@g.us"


def _phone() -> str:
    """
    A fresh number per test: handoff state is keyed on it and persists.

    `414` is a real Venezuelan mobile prefix, and it has to be. The previous
    generator produced `+5841X…` for any X, and only 412/414/416/417/418 are
    valid — so a third of runs created a number libphonenumber rejects, which
    the identity broker (correctly) files for human review. The test that
    asserts a healthy identity was passing two times in three.
    """
    return f"+58414{random.randint(1_000_000, 9_999_999)}"


def _body(event_id: str, phone: str, text: str) -> dict:
    return {
        "event": "message",
        "payload": {
            "id": event_id,
            "from": f"{phone.lstrip('+')}@c.us",
            "body": text,
            "type": "chat",
            "fromMe": False,
            "isGroup": False,
            "timestamp": 1760000000,
            "_data": {"notifyName": "Paciente Prueba"},
        },
    }


def _query(sql: str, params: tuple) -> list[tuple]:
    with psycopg.connect(db_url()) as conn:
        return conn.execute(sql, params).fetchall()


def _wait_processed(event_id: str, timeout: float = 25.0) -> str | None:
    deadline = time.monotonic() + timeout
    status = None
    while time.monotonic() < deadline:
        rows = _query(
            "select status from intake_events where source_event_id = %s", (event_id,)
        )
        status = rows[0][0] if rows else None
        if status in {"processed", "failed", "skipped"}:
            return status
        time.sleep(0.1)
    return status


@pytest.fixture(scope="module")
def stack(agent_app):
    client, main_mod = agent_app

    sent: list[tuple[str, str]] = []

    async def fake_send(address: str, text: str) -> str:
        sent.append((address, text))
        return f"wamid.{len(sent)}"

    async def exploding_compose(**kwargs: object) -> tuple[str, int, int]:
        raise AssertionError("LLM composed on a turn that must be deterministic")

    originals = (main_mod.waha.send_text, main_mod.llm.compose, main_mod.fsm._team_group_jid)
    main_mod.waha.send_text = fake_send
    main_mod.llm.compose = exploding_compose
    main_mod.fsm._team_group_jid = TEAM_GROUP
    try:
        yield client, sent
    finally:
        main_mod.waha.send_text, main_mod.llm.compose, main_mod.fsm._team_group_jid = originals


def _turn(stack, text: str, phone: str | None = None) -> tuple[str, str, list]:
    client, sent = stack
    sent.clear()
    phone = phone or _phone()
    event_id = f"fsm-{random.randint(10**9, 10**10)}"
    resp = client.post("/webhooks/waha", json=_body(event_id, phone, text))
    assert resp.status_code == 200
    assert _wait_processed(event_id) == "processed"
    return phone, event_id, sent


# ── Deterministic answers, no model involved ─────────────────────────────────

def test_greeting_answers_from_the_canned_string(stack) -> None:
    from company_agent.packages.customer_service.policy import CANNED_GREETING

    phone, _, sent = _turn(stack, "hola buenas tardes")

    assert len(sent) == 1
    address, text = sent[0]
    assert address == f"{phone.lstrip('+')}@c.us"
    assert text == CANNED_GREETING


def test_location_question_answers_from_the_faq_dict(stack) -> None:
    from company_agent.packages.customer_service.policy import DIRECT_FAQ_REPLIES

    _, _, sent = _turn(stack, "hola, dónde quedan ustedes?")

    assert len(sent) == 1
    assert sent[0][1] == DIRECT_FAQ_REPLIES["faq_location"]


def test_reply_is_recorded_in_the_outbox_as_dispatched(stack) -> None:
    _, event_id, _ = _turn(stack, "hola")

    rows = _query(
        "select status, message_class, provider_message_id from send_intents "
        "where idempotency_key = %s",
        (f"waha:{event_id}:reply",),
    )
    assert len(rows) == 1
    status, message_class, provider_id = rows[0]
    assert status == "dispatched"
    assert message_class == "reply"
    assert provider_id is not None


def test_turn_is_logged_with_the_classified_intent(stack) -> None:
    phone, _, _ = _turn(stack, "dónde están ubicados?")

    import hashlib

    phone_hash = hashlib.sha256(phone.encode()).hexdigest()
    rows = _query(
        "select classified_intent, composed_by_llm, task from turn_log where phone_hash = %s",
        (phone_hash,),
    )
    assert len(rows) == 1
    intent, composed, task = rows[0]
    assert intent == "faq_location"
    assert composed is False
    assert task == "customer_service"


def test_a_turn_is_linked_to_a_durable_identity(stack) -> None:
    """
    `turn_log.identity_id` existed with no FK, no index and no writer since the
    Stage 0 migration. Without it the only join from a turn to a human is
    sha256(phone), which changes whenever the phone string does — so Art. 17
    erasure has no key that survives a patient reaching us in two formats.
    """
    phone, _, _ = _turn(stack, "dónde están ubicados?")

    rows = _query(
        """
        select i.phone_e164, i.wa_id, i.merge_state
        from turn_log t join identity_registry i on i.id = t.identity_id
        where t.phone_hash = encode(digest(%s, 'sha256'), 'hex')
        """,
        (phone,),
    )
    assert len(rows) == 1, "the turn is not joined to an identity"
    phone_e164, wa_id, merge_state = rows[0]
    assert phone_e164 == phone
    assert wa_id == phone.lstrip("+")
    assert merge_state == "active"


# ── Handoff ───────────────────────────────────────────────────────────────────

def test_medical_question_escalates_and_leaks_no_patient_text(stack) -> None:
    from company_agent.packages.customer_service.policy import HANDOFF_PHRASE

    secret = "me arde el estómago desde hace tres semanas"
    phone, _, sent = _turn(stack, secret)

    # A handoff row exists and is active.
    rows = _query(
        "select status, reason, last_message from handoff_state where contact_phone = %s",
        (phone,),
    )
    assert len(rows) == 1
    status, reason, last_message = rows[0]
    assert status == "pending"
    assert reason.startswith("handoff_")

    # graft 10: the patient's words reach neither the ticket nor the team group.
    assert last_message is None
    patient_reply = [t for a, t in sent if a != TEAM_GROUP]
    team_pings = [t for a, t in sent if a == TEAM_GROUP]
    assert patient_reply == [HANDOFF_PHRASE]
    assert len(team_pings) == 1
    assert secret not in team_pings[0]
    assert phone in team_pings[0]


def test_one_turn_stamps_the_identity_on_every_row_it_writes(stack) -> None:
    """
    The inbox, the outbox and the ticket all carry the patient's data, and none
    of them had a key to it. Identity is resolved inside the turn — after the
    inbox row is already durable, because nothing is ACKed that is not — so the
    stamp has to be threaded back out rather than written on the way in.
    """
    phone, event_id, _ = _turn(stack, "necesito un especialista para mi caso")

    rows = _query("select id from identity_registry where phone_e164 = %s", (phone,))
    assert len(rows) == 1
    identity_id = rows[0][0]

    assert _query(
        "select identity_id from intake_events where source_event_id = %s", (event_id,)
    ) == [(identity_id,)]
    assert _query(
        "select identity_id from handoff_state where contact_phone = %s", (phone,)
    ) == [(identity_id,)]

    # Both sends of this turn: the patient's reply, and the team ping that names
    # their number — which makes it the patient's data too, addressed elsewhere.
    sends = _query(
        """
        select s.identity_id from send_intents s
          join intake_events e on e.turn_id = s.turn_id
         where e.source_event_id = %s
        """,
        (event_id,),
    )
    assert sends == [(identity_id,), (identity_id,)]


def test_a_ticket_that_could_not_be_opened_is_announced_not_swallowed(stack, agent_app) -> None:
    """
    The failure used to be a log line on a droplet, which is not a person.

    A handoff that never became a row means the patient is waiting for an asesora
    nobody told about them, and Gutty is not muted, so it keeps answering. The
    team hears about it — and hears the truth, not the usual "responde TOMO",
    which would send them chasing a ticket that does not exist.
    """
    from company_agent.packages.customer_service.policy import HANDOFF_PHRASE

    _, main_mod = agent_app

    async def unreachable(**kwargs: object) -> dict:
        raise RuntimeError("crm-adapter unreachable")

    original = main_mod.handoff_client.create_handoff
    main_mod.handoff_client.create_handoff = unreachable
    try:
        phone, _, sent = _turn(stack, "necesito que un especialista revise mis síntomas")
    finally:
        main_mod.handoff_client.create_handoff = original

    assert _query("select 1 from handoff_state where contact_phone = %s", (phone,)) == []

    assert [t for a, t in sent if a != TEAM_GROUP] == [HANDOFF_PHRASE]

    team = [t for a, t in sent if a == TEAM_GROUP]
    assert len(team) == 1
    assert "No pude abrir el ticket" in team[0]
    assert "TOMO" not in team[0]
    assert phone in team[0]


def test_agent_stays_silent_while_a_human_holds_the_conversation(stack) -> None:
    client, sent = stack

    # First message escalates.
    phone, _, _ = _turn(stack, "necesito que un especialista revise mis síntomas")
    assert _query(
        "select 1 from handoff_state where contact_phone = %s and status = 'pending'", (phone,)
    )

    # Second message from the same patient must not be answered.
    sent.clear()
    event_id = f"fsm-{random.randint(10**9, 10**10)}"
    resp = client.post("/webhooks/waha", json=_body(event_id, phone, "hola? sigues ahí?"))
    assert resp.status_code == 200
    assert _wait_processed(event_id) == "processed"

    assert sent == []


# ── Idempotency across the whole stack ───────────────────────────────────────

def test_redelivery_produces_exactly_one_reply(stack) -> None:
    client, sent = stack
    sent.clear()
    phone = _phone()
    event_id = f"fsm-{random.randint(10**9, 10**10)}"
    body = _body(event_id, phone, "hola")

    for _ in range(3):
        assert client.post("/webhooks/waha", json=body).status_code == 200
    assert _wait_processed(event_id) == "processed"

    assert len(sent) == 1
    assert len(_query("select 1 from intake_events where source_event_id = %s", (event_id,))) == 1
    assert (
        len(_query("select 1 from send_intents where idempotency_key = %s", (f"waha:{event_id}:reply",)))
        == 1
    )
