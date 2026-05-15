from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(connect=2.0, read=8.0, write=2.0, pool=2.0)


class HandoffClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"X-Internal-Api-Key": api_key, "Content-Type": "application/json"}

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{self._base_url}{path}",
                json=payload,
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()  # type: ignore[return-value]

    async def check_active(self, phone: str) -> bool:
        """Return True if there is an active handoff for this phone."""
        try:
            data = await self._post("/v1/handoff/state/check", {"contact_phone": phone})
            return bool(data.get("active", False))
        except Exception as exc:
            logger.warning("handoff state check failed (fail-open): %s", exc)
            return False  # fail open — let agent answer

    async def create_handoff(
        self,
        *,
        contact_phone: str,
        reason: str,
        priority: str = "high",
        contact_id: str | None = None,
        patient_name: str | None = None,
        last_message: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "contact_phone": contact_phone,
            "reason": reason,
            "priority": priority,
        }
        if contact_id:
            payload["customer_id"] = contact_id
        if patient_name:
            payload["patient_name"] = patient_name
        if last_message:
            payload["last_message"] = last_message
        if conversation_id:
            payload["conversation_id"] = conversation_id
        return await self._post("/v1/handoff", payload)

    async def resume(self, phone: str) -> dict[str, Any]:
        return await self._post("/v1/handoff/resume", {"contact_phone": phone})

    async def claim(
        self, contact_phone: str, claimer_phone: str, claimer_name: str
    ) -> dict[str, Any]:
        return await self._post(
            "/v1/handoff/claim",
            {
                "contact_phone": contact_phone,
                "claimer_phone": claimer_phone,
                "claimer_name": claimer_name,
            },
        )
