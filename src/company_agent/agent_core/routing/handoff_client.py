from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(connect=2.0, read=8.0, write=2.0, pool=2.0)


class HandoffClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"X-Internal-Api-Key": api_key, "Content-Type": "application/json"}
        self._client = httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        resp = await self._client.post(f"{self._base_url}{path}", json=payload)
        resp.raise_for_status()
        return resp.json()  # type: ignore[return-value]

    async def check_active(self, phone: str) -> bool:
        """
        Return True if there is an active handoff for this phone.

        Raises on failure. The caller must NOT read an exception as "not muted":
        an unreachable crm-adapter used to mean Gutty talked over a human asesora
        mid-conversation. The FSM degrades to deterministic-only replies instead.
        """
        data = await self._post("/v1/handoff/state/check", {"contact_phone": phone})
        return bool(data.get("active", False))

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
        identity_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "contact_phone": contact_phone,
            "reason": reason,
            "priority": priority,
        }
        # The durable key for this patient. The phone is what crm-adapter looks
        # the ticket up by; this is what an erasure finds it by.
        if identity_id:
            payload["identity_id"] = str(identity_id)
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

    async def sweep(self) -> list[dict[str, Any]]:
        """
        Close every case whose window ran out, and get back what was closed.

        Raises on failure, like `check_active`: a sweep that silently returned []
        would look exactly like "nothing expired", and the whole point of this
        call is that expiries stop being invisible.
        """
        data = await self._post("/v1/handoff/sweep", {})
        return list(data.get("expired", []))

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
