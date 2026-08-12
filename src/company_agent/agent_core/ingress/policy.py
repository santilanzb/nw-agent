"""
Who agent-core is allowed to answer.

OpenClaw has had `dmPolicy: "allowlist"` since it went live. agent-core had
nothing: every direct message reaching the paired number got a reply. That is
correct for a dedicated bot line and dangerous for anything else — pointing the
brain at a real corporate WhatsApp meant patients and colleagues writing to a
person would be answered by Gutty instead.

Two lists, because the safe shape changes between testing and production:

  allowlist   only these numbers are answered. What a test window wants: the
              line stays a person's line, and exactly one number is a patient.
  blocklist   everyone is answered except these. What production wants, since
              future patients cannot be enumerated, but specific numbers — the
              team's own phones, a partner, the founder — must never get a bot.

**The blocklist wins.** A number on both is blocked: the list that says "never"
has to beat the list that says "sometimes", or a copy-paste into the wrong
variable silently opens what someone meant to close.

Both sides are compared **canonicalized**. A blocklist written in E.164 against
an inbound wa_id is a string comparison that misses — Mexico's legacy `1`,
Argentina's absent `9` — and here that failure does not lose a message, it
answers someone who was meant to be left alone.

Groups are not governed here. agent-core only ever acts on one group, the team
JID it is configured with, and the FSM checks that itself.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from company_agent.common.phone import canonical_key

from ..transport.base import InboundEvent

logger = logging.getLogger(__name__)


def parse_numbers(raw: str) -> frozenset[str]:
    """
    A comma- or semicolon-separated list of numbers, as canonical keys.

    **Not space-separated**, though it was until a test caught it: a phone number
    written the way a person writes one contains spaces, so splitting on
    whitespace turned `+58 414-561 0594` into three fragments and the entry
    protected nobody. A list separator cannot be a character that appears inside
    the items.

    Unparseable entries are dropped with a warning rather than silently kept in a
    form nothing will ever match: a blocklist entry that cannot match is a number
    someone believes is protected and is not.
    """
    keys: set[str] = set()
    for chunk in raw.replace(";", ",").split(","):
        try:
            keys.add(canonical_key(chunk))
        except ValueError:
            logger.warning("ignoring unusable number in a DM policy list: %r", chunk)
    return frozenset(keys)


@dataclass(frozen=True, slots=True)
class DmPolicy:
    allowed: frozenset[str] = frozenset()
    blocked: frozenset[str] = frozenset()

    @classmethod
    def from_settings(cls, allowed_raw: str, blocked_raw: str) -> DmPolicy:
        return cls(allowed=parse_numbers(allowed_raw), blocked=parse_numbers(blocked_raw))

    @property
    def describe(self) -> str:
        if self.blocked and self.allowed:
            return f"allowlist of {len(self.allowed)}, minus {len(self.blocked)} blocked"
        if self.allowed:
            return f"allowlist of {len(self.allowed)}"
        if self.blocked:
            return f"open, minus {len(self.blocked)} blocked"
        return "open to every direct message"

    def refusal(self, event: InboundEvent) -> str | None:
        """
        Why this event must not be answered, or None to proceed.

        Returns a reason string rather than a bool so the inbox row records what
        happened: "why did Gutty not answer me" has to be answerable months later
        from the database, not from whether a log line survived.
        """
        if event.is_group:
            return None

        try:
            key = canonical_key(event.conversation_key)
        except ValueError:
            # No digits at all. Nothing can be on either list, and nothing can be
            # replied to either, so this is refused on its own merits.
            return "sender has no usable phone number"

        if key in self.blocked:
            return "sender is on BLOCKED_DM_SENDERS"
        if self.allowed and key not in self.allowed:
            return "sender is not on ALLOWED_DM_SENDERS"
        return None
