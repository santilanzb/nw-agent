from __future__ import annotations

import hashlib
import hmac


def verify_waha_hmac(body: bytes, header_value: str, secret: str) -> bool:
    """Return True if the X-Webhook-Hmac header matches HMAC-SHA512(body, secret)."""
    if not secret:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, header_value.lower())
