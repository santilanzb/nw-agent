"""Identity: who is on the other end of a conversation, and how to reach them.

The canonicalizer itself lives in `company_agent.common.phone` — crm-adapter keys
`handoff_state` on it too, and a copy in each service is how the two drifted
apart in the first place. Re-exported here because this is where the brain thinks
about identity.
"""

from company_agent.common.phone import CanonicalPhone, canonicalize, from_jid

from .broker import IdentityBroker, IdentityRecord

__all__ = [
    "CanonicalPhone",
    "IdentityBroker",
    "IdentityRecord",
    "canonicalize",
    "from_jid",
]
