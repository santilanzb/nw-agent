"""
WhatsApp's LID addressing, and the phone hiding behind it.

`payload.from` is increasingly `<opaque-id>@lid` rather than `<phone>@c.us`. The
real number rides in `_data.key.remoteJidAlt`. Read the LID as a number and every
layer below is quietly wrong: the identity broker registers a patient at a number
nobody has, the ticket is keyed on it so no asesora can claim the case, and the
reply is addressed to a JID that does not resolve.

The payloads here are the real thing, captured from the first inbound message a
real phone ever sent this deployment (2026-08-12). The simulated transport had
never produced a LID, which is why a green suite and a green synthetic smoke test
both missed it — the only way to see this was to point it at a real WhatsApp.
"""
from __future__ import annotations

from company_agent.agent_core.transport.waha import WahaTransport

TRANSPORT = WahaTransport(
    base_url="http://waha", api_key="k", hmac_key="", allow_unverified=True
)

LID = "65575912997059@lid"
PHONE_JID = "584121102566@s.whatsapp.net"
PHONE = "+584121102566"


def _dm(from_jid: str, key: dict) -> dict:
    return {
        "event": "message",
        "payload": {
            "id": f"false_{from_jid}_AC3B9C6C9F199FACEA7EBCAA4099F3DB",
            "from": from_jid,
            "body": "Buenas!",
            "type": "chat",
            "fromMe": False,
            "isGroup": False,
            "timestamp": 1786556874,
            "_data": {"key": key, "pushName": "Santiago Lanz"},
        },
    }


def test_a_lid_resolves_to_the_number_behind_it() -> None:
    event = TRANSPORT.normalize(
        _dm(LID, {"remoteJid": LID, "remoteJidAlt": PHONE_JID, "fromMe": False})
    )
    assert event is not None
    assert event.conversation_key == PHONE
    assert event.sender_e164 == PHONE


def test_the_reply_goes_to_the_number_not_the_lid() -> None:
    """The address is derived from conversation_key, so the LID must not reach it."""
    event = TRANSPORT.normalize(
        _dm(LID, {"remoteJid": LID, "remoteJidAlt": PHONE_JID, "fromMe": False})
    )
    assert event is not None
    assert TRANSPORT.address_for(event.conversation_key) == "584121102566@c.us"


def test_a_plain_phone_jid_is_untouched() -> None:
    """The old shape still arrives from other contacts and must not change."""
    event = TRANSPORT.normalize(_dm("584145610594@c.us", {"fromMe": False}))
    assert event is not None
    assert event.conversation_key == "+584145610594"


def test_a_lid_with_no_alternative_is_carried_not_dropped() -> None:
    """
    An unaddressable conversation is still a patient talking to us. It reaches
    the broker, which files an unparseable number for human review — losing the
    message would be worse than mis-filing it.
    """
    event = TRANSPORT.normalize(_dm(LID, {"remoteJid": LID, "fromMe": False}))
    assert event is not None
    assert event.conversation_key == "+65575912997059"


GROUP_JID = "120363429796220809@g.us"


def _group_command(*, with_flag: bool) -> dict:
    """
    The real shape WAHA 2026.7 delivers: a group JID in `from`, a LID in
    `participant`, the asesora's number in `_data.key.participantAlt` — and no
    `isGroup` field at all.
    """
    raw = _dm(GROUP_JID, {"remoteJid": GROUP_JID, "participantAlt": PHONE_JID, "fromMe": False})
    raw["payload"]["participant"] = LID
    raw["payload"]["body"] = "@Gutty tomo +584121102566"
    if with_flag:
        raw["payload"]["isGroup"] = True
    return raw


def test_a_group_is_recognised_without_the_isGroup_flag() -> None:
    """
    WAHA 2026.7 sends no `isGroup`. Trusting it made every team-group message
    look like a direct message from a "patient" whose number was the group id:
    the claim was refused by the DM allowlist and the case could never be taken.
    A JID ending in @g.us is a group, whatever the provider chooses to send.
    """
    event = TRANSPORT.normalize(_group_command(with_flag=False))
    assert event is not None
    assert event.is_group is True
    assert event.group_id == GROUP_JID
    assert event.conversation_key == GROUP_JID


def test_the_flag_is_still_honoured_when_present() -> None:
    event = TRANSPORT.normalize(_group_command(with_flag=True))
    assert event is not None
    assert event.is_group is True


def test_a_group_participant_lid_resolves_too() -> None:
    """
    This org's groups are LID-addressed, so an asesora's claim would otherwise be
    recorded against an id that is not her phone.
    """
    event = TRANSPORT.normalize(_group_command(with_flag=False))
    assert event is not None
    assert event.sender_e164 == PHONE
