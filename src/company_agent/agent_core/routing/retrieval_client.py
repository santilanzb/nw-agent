"""
Retrieval for composed answers.

`build_fallback_prompt` passed the patient's message and nothing else, so every
off-FAQ answer was composed from the model's own knowledge of NutriWhite — which
is none. The system prompt asked it not to invent prices; that is a request, not
a mechanism.

Unlike the classifier, a retrieval failure is **not** fatal to the turn. The task
composes with whatever context it has and the model's standing instruction to
defer to an asesora when it does not know. So this client returns an empty list
rather than raising: a patient waiting on an answer is better served by a hedged
reply than by an error.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# Tighter than the classifier's: retrieval is additive, so waiting on it is worse
# than going without it.
_TIMEOUT = httpx.Timeout(connect=2.0, read=5.0, write=2.0, pool=2.0)


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    content: str
    source_uri: str
    score: float


class RetrievalClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=_TIMEOUT,
            headers={"X-Internal-Api-Key": api_key, "Content-Type": "application/json"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def retrieve(self, query: str, top_k: int = 4) -> list[RetrievedChunk]:
        """Best-effort. Never raises — an ungrounded answer beats no answer."""
        if not query.strip():
            return []
        try:
            resp = await self._client.post(
                f"{self._base_url}/v1/retrieve", json={"query": query, "top_k": top_k}
            )
            resp.raise_for_status()
            results = resp.json().get("results") or []
        except Exception as exc:  # noqa: BLE001 - retrieval is additive, never fatal
            logger.warning("retrieve failed query=%r: %s — composing ungrounded", query[:60], exc)
            return []

        return [
            RetrievedChunk(
                content=row.get("content") or "",
                source_uri=row.get("source_uri") or "",
                score=float(row.get("score") or 0.0),
            )
            for row in results
            if (row.get("content") or "").strip()
        ]
