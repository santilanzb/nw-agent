"""Identity: who is on the other end of a conversation, and how to reach them."""

from .broker import IdentityBroker, IdentityRecord
from .phone import CanonicalPhone, canonicalize, from_jid

__all__ = [
    "CanonicalPhone",
    "IdentityBroker",
    "IdentityRecord",
    "canonicalize",
    "from_jid",
]
