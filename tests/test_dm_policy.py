"""
Who agent-core answers, and who it must leave alone.

This exists because of a near miss. WAHA was paired with a live corporate
WhatsApp — a real line, in forty groups, including patients' — and agent-core had
no inbound policy at all: OpenClaw has had `dmPolicy: "allowlist"` since it went
live, the brain had nothing. Every direct message to that number would have been
answered by Gutty. Nothing had arrived yet when it was caught, which was luck.

The two shapes are not the same, and both are needed: a test window wants an
allowlist (the line stays a person's line), production wants a blocklist (future
patients cannot be enumerated, but specific numbers must never get a bot).
"""
from __future__ import annotations

import pytest

from company_agent.agent_core.ingress.policy import DmPolicy, parse_numbers
from company_agent.agent_core.transport.base import InboundEvent

PATIENT = "+584145610594"
STRANGER = "+584241329676"


def _dm(phone: str) -> InboundEvent:
    return InboundEvent(
        source="waha",
        source_event_id="e1",
        conversation_key=phone,
        text="hola",
    )


def _group(jid: str = "120363000000000000@g.us") -> InboundEvent:
    return InboundEvent(
        source="waha",
        source_event_id="e2",
        conversation_key=jid,
        text="@Gutty tomo +584145610594",
        is_group=True,
        group_id=jid,
    )


# ── Open by default, which is the production shape ───────────────────────────

def test_with_no_lists_everyone_is_answered() -> None:
    """Future patients cannot be enumerated, so an empty allowlist means open."""
    assert DmPolicy().refusal(_dm(PATIENT)) is None


# ── Allowlist: the test window ───────────────────────────────────────────────

def test_an_allowlist_answers_only_who_is_on_it() -> None:
    policy = DmPolicy.from_settings(PATIENT, "")
    assert policy.refusal(_dm(PATIENT)) is None
    assert policy.refusal(_dm(STRANGER)) == "sender is not on ALLOWED_DM_SENDERS"


# ── Blocklist: the production exception ──────────────────────────────────────

def test_a_blocklist_answers_everyone_else() -> None:
    policy = DmPolicy.from_settings("", STRANGER)
    assert policy.refusal(_dm(PATIENT)) is None
    assert policy.refusal(_dm(STRANGER)) == "sender is on BLOCKED_DM_SENDERS"


def test_blocked_beats_allowed() -> None:
    """
    The list that says "never" has to beat the list that says "sometimes", or a
    number pasted into the wrong variable silently opens what someone closed.
    """
    policy = DmPolicy.from_settings(f"{PATIENT},{STRANGER}", STRANGER)
    assert policy.refusal(_dm(STRANGER)) == "sender is on BLOCKED_DM_SENDERS"
    assert policy.refusal(_dm(PATIENT)) is None


# ── The comparison itself ────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("listed", "arrives_as"),
    [
        ("+5215551234567", "+525551234567"),   # written with the legacy 1, arrives without
        ("+525551234567", "+5215551234567"),   # and the other way round
        ("+5491123456789", "+541123456789"),   # Argentina, with the mobile 9 and without
        ("+58 414-561 0594", "+584145610594"), # typed the way a person types it
    ],
)
def test_a_blocked_number_stays_blocked_across_formats(listed: str, arrives_as: str) -> None:
    """
    The failure mode this guards is not a lost message — it is answering someone
    who was meant to be left alone, because a blocklist in E.164 was compared as a
    string against an inbound wa_id.
    """
    policy = DmPolicy.from_settings("", listed)
    assert policy.refusal(_dm(arrives_as)) == "sender is on BLOCKED_DM_SENDERS"


def test_an_unusable_list_entry_is_dropped_not_kept() -> None:
    """
    A blocklist entry that can never match is a number someone believes is
    protected and is not. Better to lose it loudly than to keep it as decoration.
    """
    assert parse_numbers("sin numero, +584145610594, ---") == frozenset({PATIENT})


def test_a_written_number_survives_the_split() -> None:
    """
    The bug this caught: the separator used to include whitespace, so a number
    written the way a person writes one was shredded into fragments and the entry
    silently protected nobody.
    """
    assert parse_numbers("+58 414-561 0594") == frozenset({PATIENT})
    assert parse_numbers("+58 414 561 0594, +52 1 555 123 4567") == frozenset(
        {PATIENT, "+525551234567"}
    )


def test_a_sender_with_no_number_is_refused() -> None:
    assert DmPolicy().refusal(_dm("")) == "sender has no usable phone number"


# ── Groups are governed elsewhere ────────────────────────────────────────────

def test_groups_are_not_filtered_here() -> None:
    """
    agent-core acts on exactly one group, the team JID it is configured with, and
    the FSM checks that itself. Filtering group ids against a phone allowlist
    would only ever refuse all of them.
    """
    policy = DmPolicy.from_settings(PATIENT, STRANGER)
    assert policy.refusal(_group()) is None
