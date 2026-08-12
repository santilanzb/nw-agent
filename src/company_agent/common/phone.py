"""
One phone canonicalizer, replacing three.

Before this module the system transformed phone numbers in three unrelated
places, none of them country-aware:

  transport/waha.py       "+" + whatever digits preceded "@"
  crm_adapter/zoho_client last 9 digits, LIKE-matched
  agent_core/fsm.py       "+" + the first run of 7-15 digits in a group command

**A WhatsApp id is not E.164, and the divergence runs in both directions.**
Verified against libphonenumber 9.0.36:

  Mexico     wa_id 52 1 55 5123 4567   E.164 +52 55 5123 4567   (the 1 is not dialled)
  Argentina  wa_id 54 11 3456789       E.164 +54 9 11 3456789   (the 9 IS dialled)
  Brazil     wa_id 55 11 8765 4321     E.164 +55 11 9 8765 4321 (legacy 8-digit local)

So canonicalizing and then addressing outbound from the canonical form produces
an **undeliverable** JID for Mexico, and the reverse for Argentina. The rule this
module exists to enforce:

    canonicalize for identity; address from the wa_id the transport gave you.

`identity_registry` is shaped for exactly that — `phone_e164` and `wa_id` are
separate unique columns.

It lives in `common/` rather than under `agent_core/identity/` because
**crm-adapter needs it too**. `handoff_state.contact_phone` is a lookup key, and
agent-core wrote it from the raw wa_id while the group-command path read it in
canonical form — so `@Gutty tomo` matched nothing for every Mexican, Argentine
and Brazilian patient whose id diverges, and `@Gutty resume` left Gutty mute for
the full TTL. Canonicalizing at the crm-adapter boundary fixes every caller at
once, including the OpenClaw plugin, which writes a third format of its own.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import phonenumbers

_NON_DIGITS = re.compile(r"\D")


@dataclass(frozen=True, slots=True)
class CanonicalPhone:
    """
    A number in both the forms we need.

    `e164` identifies the person. `wa_id` addresses them. They are frequently
    the same string and must not be assumed to be.
    """

    e164: str
    wa_id: str
    valid: bool
    region: str | None = None

    @property
    def suffix(self) -> str:
        """Last 9 significant digits — how Zoho's inconsistently-formatted numbers are matched."""
        digits = _NON_DIGITS.sub("", self.e164)
        return digits[-9:] if len(digits) >= 9 else digits


def _parse(digits: str) -> phonenumbers.PhoneNumber | None:
    try:
        return phonenumbers.parse("+" + digits, None)
    except phonenumbers.NumberParseException:
        return None


def _repairs(digits: str) -> list[str]:
    """
    Country-specific rewrites to try when a WhatsApp id is not valid E.164.

    Each is a documented divergence between what WhatsApp addresses and what the
    ITU numbering plan says, not a guess. Ordered most-specific first; the first
    one that parses as a valid number wins.
    """
    candidates: list[str] = []

    # Mexico: WhatsApp keeps the legacy "1" for mobiles; E.164 dropped it in 2019.
    if digits.startswith("521") and len(digits) == 13:
        candidates.append("52" + digits[3:])

    # Argentina: mobiles are dialled with a "9" that WhatsApp ids omit.
    if digits.startswith("54") and not digits.startswith("549"):
        candidates.append("549" + digits[2:])

    # Brazil: the ninth digit was added to mobile numbers; old ids lack it.
    if digits.startswith("55") and len(digits) == 12:
        area, local = digits[2:4], digits[4:]
        candidates.append(f"55{area}9{local}")

    return candidates


def _is_mobile(number: phonenumbers.PhoneNumber) -> bool:
    return phonenumbers.number_type(number) in (
        phonenumbers.PhoneNumberType.MOBILE,
        phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE,
    )


def canonicalize(raw: str) -> CanonicalPhone:
    """
    Best-effort canonical E.164 plus the addressable id.

    **Validity alone is not enough to detect the Argentine case.** Dropping the
    mobile `9` from `+54 9 11 2345-6789` leaves `+54 11 2345-6789`, which
    libphonenumber accepts as a perfectly valid *fixed line*. Since WhatsApp is a
    mobile-only service, a reading that yields a valid mobile beats one that
    yields a valid landline — that preference, not a validity check, is what
    recovers the number the patient actually holds.

    Idempotent on its own `e164` output, which is what lets agent-core send the
    raw wa_id and crm-adapter canonicalize it again without moving the key.

    Never raises and never returns an empty `wa_id` for input that has digits: an
    unparseable number still has to reach `identity_registry` so the conversation
    is not silently dropped, and `valid=False` is what routes it to human review.
    """
    digits = _NON_DIGITS.sub("", raw or "")
    if not digits:
        return CanonicalPhone(e164="", wa_id="", valid=False)

    def _result(number: phonenumbers.PhoneNumber) -> CanonicalPhone:
        return CanonicalPhone(
            e164=phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164),
            # The ORIGINAL digits stay the address. Sending to the repaired form
            # is precisely the undeliverable-JID bug this module exists to avoid.
            wa_id=digits,
            valid=True,
            region=phonenumbers.region_code_for_number(number),
        )

    parsed = _parse(digits)
    as_is = parsed if parsed is not None and phonenumbers.is_valid_number(parsed) else None

    for candidate in _repairs(digits):
        repaired = _parse(candidate)
        if repaired is None or not phonenumbers.is_valid_number(repaired):
            continue
        if as_is is None or (_is_mobile(repaired) and not _is_mobile(as_is)):
            return _result(repaired)

    if as_is is not None:
        return _result(as_is)

    # Unparseable: carry it forward rather than dropping the conversation.
    return CanonicalPhone(e164="+" + digits, wa_id=digits, valid=False)


def from_jid(jid: str) -> CanonicalPhone:
    """Canonicalize a transport address like '584145610594@c.us'."""
    return canonicalize(jid.split("@", 1)[0])


def canonical_key(raw: str) -> str:
    """
    The string a patient is keyed on across services.

    Raises on input carrying no digits at all. Every other input is carried
    forward: a number we cannot parse still belongs to a real conversation, and
    refusing it here would drop the patient rather than flag them.
    """
    canonical = canonicalize(raw)
    if not canonical.wa_id:
        raise ValueError("phone must contain at least one digit")
    return canonical.e164
