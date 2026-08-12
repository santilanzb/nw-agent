"""
One canonicalizer, and the round-trip it must not break.

A WhatsApp id is not E.164, and the divergence runs in **both** directions:
Mexico's wa_id carries a `1` that E.164 dropped in 2019, Argentina's omits a `9`
that E.164 requires. So canonicalizing and then addressing the reply from the
canonical form produces an undeliverable JID for one country and works for the
other — which is the kind of bug that looks like "WhatsApp is flaky".

The rule: canonicalize for identity, address from the observed wa_id.
"""
from __future__ import annotations

import pytest

from company_agent.agent_core.fsm import _target_phone
from company_agent.agent_core.transport.waha import WahaTransport
from company_agent.common.phone import canonical_key, canonicalize, from_jid

# (label, what WhatsApp sends, canonical E.164)
COUNTRY_CASES = [
    ("venezuela", "584145610594", "+584145610594"),
    ("mexico wa_id keeps the legacy 1", "5215512345678", "+525512345678"),
    ("mexico already canonical", "525512345678", "+525512345678"),
    # The no-9 form parses as a valid FIXED_LINE, so only the mobile preference
    # recovers the number the patient actually holds.
    ("argentina wa_id omits the mobile 9", "541123456789", "+5491123456789"),
    ("argentina already canonical", "5491123456789", "+5491123456789"),
    ("brazil legacy 8-digit local", "551187654321", "+5511987654321"),
    ("brazil with ninth digit", "5511987654321", "+5511987654321"),
]


@pytest.mark.parametrize(("label", "wa_id", "expected"), COUNTRY_CASES)
def test_canonical_e164_per_country(label: str, wa_id: str, expected: str) -> None:
    result = canonicalize(wa_id)
    assert result.e164 == expected, label
    assert result.valid, label


@pytest.mark.parametrize(("label", "wa_id", "_expected"), COUNTRY_CASES)
def test_the_reply_is_still_deliverable(label: str, wa_id: str, _expected: str) -> None:
    """
    The load-bearing property. `wa_id` must survive canonicalization untouched,
    because that is what `address_for` turns back into a JID.
    """
    result = canonicalize(wa_id)
    assert result.wa_id == wa_id, label

    transport = WahaTransport(base_url="http://waha", api_key="k", hmac_key="", allow_unverified=True)
    assert transport.address_for("+" + result.wa_id) == f"{wa_id}@c.us", label
    # Addressing from the canonical form is the bug this guards against.
    if result.e164.lstrip("+") != wa_id:
        assert transport.address_for(result.e164) != f"{wa_id}@c.us", label


def test_two_formats_of_one_number_share_an_identity_key() -> None:
    """A Mexican patient reaching us both ways is one person, not two."""
    assert canonicalize("5215512345678").e164 == canonicalize("525512345678").e164
    # ...but they are two different addresses.
    assert canonicalize("5215512345678").wa_id != canonicalize("525512345678").wa_id


def test_formatting_noise_does_not_change_the_identity() -> None:
    formatted = canonicalize("+58 414-561 0594")
    plain = canonicalize("+584145610594")
    assert formatted.e164 == plain.e164
    assert formatted.suffix == plain.suffix == "145610594"


def test_a_jid_is_canonicalized_the_same_way() -> None:
    assert from_jid("584145610594@c.us").e164 == "+584145610594"


def test_an_unparseable_number_is_kept_and_flagged() -> None:
    """A conversation we cannot name is still one we must not drop."""
    result = canonicalize("12345")
    assert not result.valid
    assert result.wa_id == "12345"


def test_an_empty_number_yields_nothing_to_resolve() -> None:
    result = canonicalize("")
    assert not result.valid
    assert result.wa_id == ""


# ── The group command an asesora actually types ──────────────────────────────

def test_a_spaced_number_in_a_group_command_is_found() -> None:
    """
    The regression. `\\+?\\d{7,15}` needed seven CONSECUTIVE digits, so this
    matched nothing, the command was silently ignored, and the bot kept
    answering a patient the asesora had just claimed.
    """
    assert _target_phone("tomo +58 414 561 0594") == "+584145610594"


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("tomo +584145610594", "+584145610594"),
        ("tomo 584145610594", "+584145610594"),
        ("tomo +58 414-561-0594", "+584145610594"),
        ("tomo +58 (414) 561 0594", "+584145610594"),
        ("resume +584145610594", "+584145610594"),
        ("tomo +5215512345678", "+525512345678"),
    ],
)
def test_group_command_phone_forms(command: str, expected: str) -> None:
    assert _target_phone(command) == expected


def test_a_command_with_no_phone_targets_nothing() -> None:
    assert _target_phone("tomo") is None
    assert _target_phone("resume el caso del protocolo 3R") is None


def test_the_longest_candidate_wins_over_stray_digits() -> None:
    """A ticket reference in the same message must not beat the phone."""
    assert _target_phone("tomo ref 12345 el +584145610594") == "+584145610594"


# ── The mention, as WhatsApp actually sends it ───────────────────────────────

BOT_LID = "77043643474009"          # 14 digits: longer than any real number here


def test_a_serialised_mention_does_not_hide_the_command() -> None:
    """
    WhatsApp puts no "@Gutty" in the body. It serialises a mention as `@<id>`,
    and under LID addressing that is the bot's own linked id. The old pattern
    matched only the literal name, so the command never started with "tomo" and
    was dropped without a word — captured live on 2026-08-12.
    """
    from company_agent.agent_core.fsm import _GUTTY_MENTION

    body = f"@{BOT_LID} tomo +584121102566"
    assert _GUTTY_MENTION.sub("", body).strip().startswith("tomo")


def test_the_bot_does_not_claim_itself() -> None:
    """
    A linked id is 14-15 digits, inside E.164's range, so length cannot tell it
    from a phone — and it rides in every mention. On digit count alone the bot's
    own id wins and Gutty claims her own case.
    """
    assert _target_phone(f"@{BOT_LID} tomo +584121102566") == "+584121102566"


def test_a_mentioned_target_after_the_command_still_wins() -> None:
    """Only leading mentions are stripped; the target must survive."""
    assert _target_phone(f"@{BOT_LID} resume +58 414 561 0594") == "+584145610594"


# ── The lookup key the two paths must agree on ───────────────────────────────

@pytest.mark.parametrize(("label", "wa_id", "expected"), COUNTRY_CASES)
def test_the_dm_key_and_the_group_key_converge(label: str, wa_id: str, expected: str) -> None:
    """
    The divergence this key closes.

    agent-core hands crm-adapter the raw wa_id — `'+' + digits` — because that is
    what the reply address round-trips from. An asesora's "@Gutty tomo" resolves
    the canonical E.164. Those were two different strings for Mexico-with-the-1,
    Argentina-without-the-9 and eight-digit Brazil, so the claim matched no row
    and the resume left Gutty mute for the whole TTL. They coincide in Venezuela,
    which is the only country this repo's fixtures ever used.
    """
    typed = _target_phone(f"tomo +{wa_id}")
    assert typed is not None, label
    assert canonical_key("+" + wa_id) == canonical_key(typed) == expected, label


@pytest.mark.parametrize(("label", "wa_id", "expected"), COUNTRY_CASES)
def test_canonical_key_is_idempotent(label: str, wa_id: str, expected: str) -> None:
    """
    Canonicalizing at the boundary means an already-canonical number gets a
    second pass. If that moved the key, the group path would break the moment
    agent-core started sending canonical numbers.
    """
    once = canonical_key(wa_id)
    assert canonical_key(once) == once == expected, label


def test_a_key_needs_at_least_one_digit() -> None:
    """The one input a handoff cannot be keyed on."""
    for junk in ("", "   ", "sin número"):
        with pytest.raises(ValueError, match="digit"):
            canonical_key(junk)


def test_an_unparseable_number_still_gets_a_key() -> None:
    """Same doctrine as the broker: flag it, do not drop the conversation."""
    assert canonical_key("12345") == "+12345"
