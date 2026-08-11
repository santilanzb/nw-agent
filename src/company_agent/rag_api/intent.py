from __future__ import annotations

from typing import Literal

from company_agent.common.db import connect, vector_literal
from company_agent.common.embeddings import EmbeddingClient
from company_agent.packages.registry import discover_manifests, merge_seeds

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


def load_dispatch_table() -> dict[str, IntentDispatch]:
    """
    Build the dispatch table from the installed function packages.

    This used to read a single YAML path and return `{}` when the file was
    missing — so a mis-pathed config produced a classifier that classified
    correctly and dispatched nothing, silently. Discovery now raises instead.
    """
    merged = merge_seeds(discover_manifests())
    return {
        intent_class: IntentDispatch(
            tool=intent.dispatch.tool,
            params=intent.dispatch.params,
        )
        for intent_class, intent in merged.items()
    }


class IntentClassifier:
    def __init__(
        self,
        settings: RagSettings,
        embeddings: EmbeddingClient,
        dispatch_table: dict[str, IntentDispatch] | None = None,
    ) -> None:
        self._settings = settings
        self._embeddings = embeddings
        self._dispatch_table = (
            dispatch_table if dispatch_table is not None else load_dispatch_table()
        )

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
