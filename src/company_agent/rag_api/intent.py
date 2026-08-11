from __future__ import annotations

import logging
import threading
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

logger = logging.getLogger(__name__)

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


DISPATCH_SQL = """
SELECT DISTINCT ON (intent_class) intent_class, metadata
FROM intent_vectors
ORDER BY intent_class, created_at DESC
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


def load_dispatch_table_from_db(database_url: str) -> dict[str, IntentDispatch]:
    """
    Build the dispatch table from `intent_vectors.metadata`.

    The seeder has always written the dispatch payload onto every row it
    inserts; rag-api simply never read it, parsing the YAML instead. Reading it
    here makes the vectors and the dispatch table physically incapable of
    disagreeing — one writer, one transaction — where before the seeder could
    write new vectors while rag-api kept dispatching from an older image.

    Rows seeded before this column carried a dispatch are treated as
    "classify but do not act", which is what an absent dispatch already meant.
    """
    with connect(database_url) as conn:
        rows = conn.execute(DISPATCH_SQL).fetchall()

    table: dict[str, IntentDispatch] = {}
    for row in rows:
        dispatch = (row["metadata"] or {}).get("dispatch") or {}
        table[row["intent_class"]] = IntentDispatch(
            tool=dispatch.get("tool"),
            params=dispatch.get("params") or {},
        )
    return table


class IntentClassifier:
    def __init__(
        self,
        settings: RagSettings,
        embeddings: EmbeddingClient,
        dispatch_table: dict[str, IntentDispatch] | None = None,
    ) -> None:
        self._settings = settings
        self._embeddings = embeddings
        # Empty until reload_dispatch() runs in the app's lifespan. Building it
        # in the constructor would make importing this module require a
        # database, which every unit test would then have to fake.
        self._dispatch_table: dict[str, IntentDispatch] = dispatch_table or {}
        self._reload_lock = threading.Lock()

    @property
    def dispatch_table(self) -> dict[str, IntentDispatch]:
        return self._dispatch_table

    def reload_dispatch(self) -> tuple[list[str], list[str], list[str]]:
        """
        Rebuild the dispatch table from Postgres. Returns (added, removed, changed).

        `classify_intent` is a sync `def`, so FastAPI runs it in a threadpool and
        these are real threads. The new table is built completely and then bound
        in one statement: attribute rebinding is atomic under CPython, so a
        concurrent lookup sees either the whole old table or the whole new one.
        Mutating in place — `.clear()` then `.update()` — would expose a window
        where a patient's turn dispatches to nothing.

        The lock covers build-and-swap only, never reads, so two concurrent
        reloads cannot both query and report contradictory diffs.
        """
        with self._reload_lock:
            new_table = load_dispatch_table_from_db(self._settings.database_url)
            old_table = self._dispatch_table
            added = sorted(set(new_table) - set(old_table))
            removed = sorted(set(old_table) - set(new_table))
            changed = sorted(
                intent
                for intent in set(new_table) & set(old_table)
                if new_table[intent] != old_table[intent]
            )
            self._dispatch_table = new_table
        return added, removed, changed

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
