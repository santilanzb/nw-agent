from __future__ import annotations

import logging

import httpx

from ..models import ClassificationResult, IntentDispatch, IntentMatch

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(connect=2.0, read=8.0, write=2.0, pool=2.0)


class ClassifierClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"X-Internal-Api-Key": api_key, "Content-Type": "application/json"}
        # One pooled client for the process. A per-turn AsyncClient re-ran TLS and
        # connection setup on the hot path of every inbound message.
        self._client = httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def classify(self, message: str, language_hint: str = "es") -> ClassificationResult:
        payload = {"message": message, "language_hint": language_hint, "top_k": 5}
        for attempt in range(2):
            try:
                resp = await self._client.post(
                    f"{self._base_url}/v1/classify_intent", json=payload
                )
                resp.raise_for_status()
                data = resp.json()
                dispatch = None
                if data.get("dispatch"):
                    dispatch = IntentDispatch(
                        tool=data["dispatch"].get("tool"),
                        params=data["dispatch"].get("params", {}),
                    )
                top_matches = [
                    IntentMatch(
                        intent=m["intent"],
                        score=m["score"],
                        example=m.get("example", ""),
                    )
                    for m in data.get("top_matches", [])
                ]
                return ClassificationResult(
                    intent=data["intent"],
                    confidence=data["confidence"],
                    decision=data["decision"],
                    dispatch=dispatch,
                    top_matches=top_matches,
                )
            except Exception as exc:
                if attempt == 0:
                    logger.warning("classify_intent attempt 1 failed: %s — retrying", exc)
                else:
                    logger.error("classify_intent failed after retry: %s", exc)
                    raise

        raise RuntimeError("classify_intent unreachable")
