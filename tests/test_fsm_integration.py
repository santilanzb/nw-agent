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


# ── The context package ──────────────────────────────────────────────────────

def test_the_reference_in_the_group_resolves_to_the_conversation(stack) -> None:
    """
    The team group is told a reference and nothing else, because a WhatsApp group
    has no retention and no erasure path. That discipline only works if the
    reference resolves — otherwise "by reference" is just withholding.
    """
    client, _ = stack
    secret = "llevo tres semanas con acidez y nada me funciona"
    phone, _, sent_now = _turn(stack, secret)

    handoff_id = _query(
        "select id from handoff_state where contact_phone = %s", (phone,)
    )[0][0]

    # The group is given the ticket id — the reference that opens the package.
    # It used to be the turn id, which resolves to nothing an asesora can open.
    team_ping = next(t for a, t in sent_now if a == TEAM_GROUP)
    assert f"Ticket: {str(handoff_id)[:8]}" in team_ping
    assert secret not in team_ping

    resp = client.get(f"/admin/handoff/{handoff_id}/context")
    assert resp.status_code == 200, resp.text
    package = resp.json()

    assert package["errors"] == []
    assert package["ticket"]["reference"] == str(handoff_id)[:8]
    assert package["ticket"]["status"] == "pending"
    assert package["patient"]["known"] is True
    assert package["patient"]["phone_e164"] == phone
    assert package["patient"]["needs_review"] is False

    # What the group was not given: the patient's own words, in order.
    transcript = package["transcript"]
    assert [t["direction"] for t in transcript] == ["inbound", "outbound"]
    assert transcript[0]["text"] == secret

    # This is their first contact, and the package says so.
    assert package["slots"]["derived"]["returning"] is False
    assert package["slots"]["derived"]["patient_turns"] == 1
    assert package["slots"]["learned"] == []

    assert [h["handoff_id"] for h in package["history"]] == [str(handoff_id)]


def test_a_payment_proof_reaches_the_team_and_not_just_the_queue(stack) -> None:
    """
    The media path opened a ticket and told nobody: the notification needed a
    TurnContext, and media never classifies — a caption is not the content of a
    receipt — so it always passed None. A patient's proof of payment landed in a
    queue no one was watching.
    """
    client, sent = stack
    sent.clear()
    phone = _phone()
    event_id = f"fsm-{random.randint(10**9, 10**10)}"
    body = _body(event_id, phone, "")
    body["payload"]["type"] = "image"
    body["payload"]["media"] = {"url": "http://waha/api/files/receipt.jpg", "mimetype": "image/jpeg"}
    body["payload"]["_data"] = {"notifyName": "Paciente Prueba", "caption": ""}

    assert client.post("/webhooks/waha", json=body).status_code == 200
    assert _wait_processed(event_id) == "processed"

    handoff_id = _query(
        "select id from handoff_state where contact_phone = %s", (phone,)
    )[0][0]

    team = [t for a, t in sent if a == TEAM_GROUP]
    assert len(team) == 1
    assert f"Ticket: {str(handoff_id)[:8]}" in team[0]
    assert "media_image" in team[0]
    # A reference to the file, so she knows one is waiting and which — never the
    # file, in a group with no retention policy.
    assert "Adjunto:" in team[0]

    # And the transcript shows something arrived. Without this the history jumps
    # from the patient's last question straight to the handover, and whoever
    # reads it cannot tell a payment proof was ever sent.
    rows = _query(
        """
        select e.direction, e.text from patient_episodes e
          join identity_registry i on i.id = e.identity_id
         where i.phone_e164 = %s order by e.created_at, e.direction
        """,
        (phone,),
    )
    assert [d for d, _ in rows] == ["inbound", "outbound"]
    assert rows[0][1].startswith("[")          # the reference, not the bytes
    assert "image" in rows[0][1]


def test_an_unknown_reference_is_a_404(stack) -> None:
    client, _ = stack
    import uuid as _uuid

    assert client.get(f"/admin/handoff/{_uuid.uuid4()}/context").status_code == 404
    assert client.get("/admin/handoff/not-a-uuid/context").status_code == 404


# ── Expiry ───────────────────────────────────────────────────────────────────

def test_an_expired_case_is_announced_to_the_team_exactly_once(stack) -> None:
    """
    A case that ends on the clock used to end in silence. The team could not tell
    it apart from a case an asesora closed properly, and the patient who never
    wrote again left it sitting claimed forever.
    """
    client, sent = stack
    phone = _phone()

    with psycopg.connect(db_url()) as conn:
        conn.execute(
            """
            INSERT INTO handoff_state (contact_phone, status, reason, priority,
                                       expires_at, claimed_by_name)
            VALUES (%s, 'claimed', 'handoff_specialist', 'high',
                    NOW() - INTERVAL '1 hour', 'Ana')
            """,
            (phone,),
        )

    sent.clear()
    resp = client.post("/admin/handoff/sweep")
    assert resp.status_code == 200, resp.text
    assert resp.json()["announced"] >= 1

    notices = [t for a, t in sent if a == TEAM_GROUP and phone in t]
    assert len(notices) == 1
    assert "Caso vencido" in notices[0]
    assert "Ana" in notices[0]          # who was holding it
    assert "TOMO" not in notices[0]     # the case is over, not up for grabs

    # The patient hears nothing — they were told a human would write, and
    # "never mind" is worse than Gutty simply answering again.
    assert [t for a, t in sent if a != TEAM_GROUP] == []

    assert _query(
        "select status from handoff_state where contact_phone = %s", (phone,)
    ) == [("expired",)]

    # A second sweep has nothing left to say.
    sent.clear()
    assert client.post("/admin/handoff/sweep").json()["announced"] == 0
    assert [t for a, t in sent if phone in t] == []


def test_an_expired_case_stops_muting_the_patient(stack) -> None:
    """
    The mute has to end the moment the window does, not when the sweep gets
    round to flipping the row — otherwise a patient sits unanswered for up to a
    tick after their case is already over.

    Read against test_agent_stays_silent_while_a_human_holds_the_conversation,
    which is this same setup inside the window and expects nothing at all.
    """
    phone, _, _ = _turn(stack, "necesito un especialista para mi caso")

    with psycopg.connect(db_url()) as conn:
        conn.execute(
            "UPDATE handoff_state SET expires_at = NOW() - INTERVAL '1 minute' "
            "WHERE contact_phone = %s",
            (phone,),
        )

    _, _, sent_after = _turn(stack, "hola de nuevo", phone=phone)
    replies = [t for a, t in sent_after if a != TEAM_GROUP]
    assert len(replies) == 1
    assert replies[0].strip()


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
