from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml

from company_agent.common.db import connect, vector_literal
from company_agent.common.embeddings import EmbeddingClient

from .config import RagSettings
from .schemas import (
    ClassifyIntentRequest,
    ClassifyIntentResponse,
    IntentDispatch,
    IntentMatch,
)

INTENT_SQL = """
SELECT
  intent_class,
  example_text,
  1 - (embedding <=> %(embedding)s::vector) AS score
FROM intent_vectors
WHERE embedding IS NOT NULL
  AND language = %(language)s
ORDER BY embedding <=> %(embedding)s::vector
LIMIT %(top_k)s
"""


def _load_dispatch_table(seeds_path: str) -> dict[str, IntentDispatch]:
    path = Path(seeds_path)
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    table: dict[str, IntentDispatch] = {}
    for intent_class, data in raw.get("intents", {}).items():
        dispatch = data.get("dispatch", {})
        table[intent_class] = IntentDispatch(
            tool=dispatch.get("tool"),
            params=dispatch.get("params", {}),
        )
    return table


class IntentClassifier:
    def __init__(self, settings: RagSettings, embeddings: EmbeddingClient) -> None:
        self._settings = settings
        self._embeddings = embeddings
        self._dispatch_table = _load_dispatch_table(settings.intent_seeds_path)

    def classify(self, request: ClassifyIntentRequest) -> ClassifyIntentResponse:
        language = request.language_hint or "es"
        message = request.message.strip()

        if not self._embeddings.enabled:
            return ClassifyIntentResponse(
                intent="unknown",
                confidence=0.0,
                decision="fallback_llm",
                dispatch=None,
                top_matches=[],
            )

        embedding = self._embeddings.embed(message)
        if not embedding:
            return ClassifyIntentResponse(
                intent="unknown",
                confidence=0.0,
                decision="fallback_llm",
                dispatch=None,
                top_matches=[],
            )

        params = {
            "embedding": vector_literal(embedding),
            "language": language,
            "top_k": request.top_k,
        }

        with connect(self._settings.database_url) as conn:
            rows = conn.execute(INTENT_SQL, params).fetchall()

        if not rows:
            return ClassifyIntentResponse(
                intent="unknown",
                confidence=0.0,
                decision="fallback_llm",
                dispatch=None,
                top_matches=[],
            )

        top_matches = [
            IntentMatch(
                intent=row["intent_class"],
                score=round(float(row["score"]), 6),
                example=row["example_text"],
            )
            for row in rows
        ]

        top_intent = top_matches[0].intent
        top_score = top_matches[0].score

        decision: Literal["execute", "clarify", "fallback_llm"]
        dispatch: IntentDispatch | None = None

        threshold_execute = self._settings.intent_threshold_execute
        threshold_clarify = self._settings.intent_threshold_clarify
        tiebreak_margin = self._settings.intent_tiebreak_margin

        if top_score >= threshold_execute:
            # Tie-break: if top-2 are within margin, downgrade to clarify
            if (
                len(top_matches) >= 2
                and top_matches[1].intent != top_intent
                and (top_score - top_matches[1].score) < tiebreak_margin
                and top_matches[1].score >= threshold_execute
            ):
                decision = "clarify"
            else:
                decision = "execute"
                dispatch = self._dispatch_table.get(top_intent)
        elif top_score >= threshold_clarify:
            decision = "clarify"
        else:
            decision = "fallback_llm"

        return ClassifyIntentResponse(
            intent=top_intent,
            confidence=round(top_score, 6),
            decision=decision,
            dispatch=dispatch,
            top_matches=top_matches,
        )
