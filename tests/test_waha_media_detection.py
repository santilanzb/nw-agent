"""
A photo is a photo because it carries one, not because a field says so.

WAHA 2026.7 sends no `type`. normalize keyed on it, so every inbound image looked
like an empty text message and was dropped — and dropped means `None`, which
answers 204 and writes nothing, so a patient's payment proof vanished with no
record it had ever arrived. Captured live on 2026-08-12:

    from=65575912997059@lid type=None hasMedia=True
    media_keys=['filename','mimetype','url'] body_len=0

This is the same failure the media work already closed once, arriving through a
different field. The evidence the payload actually carries — `hasMedia`, and a
media object with a url — is what decides now.
"""
from __future__ import annotations

import pytest

from company_agent.agent_core.transport.waha import WahaTransport

TRANSPORT = WahaTransport(
    base_url="http://waha", api_key="k", hmac_key="", allow_unverified=True
)


def _message(payload_extra: dict) -> dict:
    payload = {
        "id": "false_65575912997059@lid_ABC123",
        "from": "65575912997059@lid",
        "body": "",
        "fromMe": False,
        "timestamp": 1786556874,
        "_data": {
            "key": {"remoteJidAlt": "584121102566@s.whatsapp.net"},
            "pushName": "Santiago Lanz",
        },
    }
    payload.update(payload_extra)
    return {"event": "message", "payload": payload}


def _photo(**over: object) -> dict:
    """The captured shape: no `type`, hasMedia true, media object present."""
    media = {
        "url": "http://waha:3000/api/files/false_ABC.jpeg",
        "mimetype": "image/jpeg",
        "filename": "false_ABC.jpeg",
    }
    media.update(over)  # type: ignore[arg-type]
    return _message({"hasMedia": True, "media": media})


def test_a_photo_without_a_type_field_is_still_a_photo() -> None:
    event = TRANSPORT.normalize(_photo())
    assert event is not None, "the message was dropped, as it was in production"
    assert event.media is not None
    assert event.media.kind == "image"
    assert event.media.url == "http://waha:3000/api/files/false_ABC.jpeg"


def test_the_patient_is_still_identified_on_a_media_turn() -> None:
    """The LID resolution has to survive the media branch too."""
    event = TRANSPORT.normalize(_photo())
    assert event is not None
    assert event.conversation_key == "+584121102566"


@pytest.mark.parametrize(
    ("mimetype", "kind"),
    [
        ("image/jpeg", "image"),
        ("image/png", "image"),
        ("image/webp", "sticker"),
        ("audio/ogg; codecs=opus", "audio"),   # the voice note, with its parameters
        ("video/mp4", "video"),
        ("application/pdf", "document"),
    ],
)
def test_the_kind_comes_from_the_mimetype_when_the_type_is_missing(
    mimetype: str, kind: str
) -> None:
    """
    Not fatal to get wrong — the acknowledgement is the same — but it is what the
    asesora reads next to the reference, so "audio" beats "unknown".
    """
    event = TRANSPORT.normalize(_photo(mimetype=mimetype))
    assert event is not None
    assert event.media is not None
    assert event.media.kind == kind


def test_an_explicit_type_still_wins() -> None:
    """Older payloads, and any WAHA that sends the field again."""
    raw = _photo(mimetype="application/octet-stream")
    raw["payload"]["type"] = "ptt"
    event = TRANSPORT.normalize(raw)
    assert event is not None
    assert event.media is not None
    assert event.media.kind == "audio"


def test_a_caption_becomes_the_text_and_survives() -> None:
    raw = _photo()
    raw["payload"]["_data"]["caption"] = "aquí está mi comprobante"
    event = TRANSPORT.normalize(raw)
    assert event is not None
    assert event.text == "aquí está mi comprobante"
    assert event.media is not None


def test_a_plain_text_message_gains_no_media() -> None:
    event = TRANSPORT.normalize(_message({"body": "hola", "hasMedia": False}))
    assert event is not None
    assert event.media is None


def test_an_empty_message_with_nothing_attached_is_still_dropped() -> None:
    """No text, no media: there is nothing to answer."""
    assert TRANSPORT.normalize(_message({"body": "", "hasMedia": False})) is None
