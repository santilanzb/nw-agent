from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from typing import Any

from psycopg.types.json import Jsonb

from company_agent.common.db import connect

from ..models import ClassificationResult, TaskResult

logger = logging.getLogger(__name__)


def _hash_phone(phone: str) -> str:
    return hashlib.sha256(phone.encode()).hexdigest()


def _write_sync(
    database_url: str,
    turn_id: uuid.UUID,
    phone: str,
    inbound_text: str,
    cls: ClassificationResult | None,
    result: TaskResult,
    task_name: str,
    latency_ms: int,
    identity_id: uuid.UUID | None = None,
    deterministic_only: bool = False,
) -> None:
    phone_hash = _hash_phone(phone)
    raw_params = cls.dispatch.params if cls and cls.dispatch and cls.dispatch.params else None
    params: dict[str, Any] = {
        "turn_id": turn_id,
        "phone_hash": phone_hash,
        "inbound_text": inbound_text[:4000],
        "classified_intent": cls.intent if cls else None,
        "confidence": cls.confidence if cls else None,
        "decision": cls.decision if cls else None,
        "dispatch_tool": (cls.dispatch.tool if cls and cls.dispatch else None),
        "dispatch_params": Jsonb(raw_params) if raw_params else None,
        "task": task_name,
        "task_outcome": result.task_outcome,
        "composed_by_llm": result.composed_by_llm,
        "model_used": result.model_used,
        "composition_tokens_in": result.composition_tokens_in,
        "composition_tokens_out": result.composition_tokens_out,
        "latency_ms": latency_ms,
        "reply_text": result.reply_text[:4000] if result.reply_text else None,
        "handoff_fired": result.handoff is not None,
        # The durable join to a human. phone_hash cannot serve as one: it changes
        # whenever the phone string does, so one patient reaching us in two
        # formats produced two unrelated histories.
        "identity_id": identity_id,
        "deterministic_only": deterministic_only,
    }
    with connect(database_url) as conn:
        conn.execute(
            """
            INSERT INTO turn_log (
                turn_id, phone_hash, inbound_text,
                classified_intent, confidence, decision,
                dispatch_tool, dispatch_params,
                task, task_outcome, composed_by_llm, model_used,
                composition_tokens_in, composition_tokens_out,
                latency_ms, reply_text, handoff_fired,
                identity_id, deterministic_only
            ) VALUES (
                %(turn_id)s, %(phone_hash)s, %(inbound_text)s,
                %(classified_intent)s, %(confidence)s, %(decision)s,
                %(dispatch_tool)s, %(dispatch_params)s,
                %(task)s, %(task_outcome)s, %(composed_by_llm)s, %(model_used)s,
                %(composition_tokens_in)s, %(composition_tokens_out)s,
                %(latency_ms)s, %(reply_text)s, %(handoff_fired)s,
                %(identity_id)s, %(deterministic_only)s
            )
            ON CONFLICT (turn_id) DO NOTHING
            """,
            params,
        )


class TurnLogWriter:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    async def write(
        self,
        turn_id: uuid.UUID,
        phone: str,
        inbound_text: str,
        cls: ClassificationResult | None,
        result: TaskResult,
        task_name: str,
        latency_ms: int,
        identity_id: uuid.UUID | None = None,
        deterministic_only: bool = False,
    ) -> None:
        try:
            await asyncio.to_thread(
                _write_sync,
                self._database_url,
                turn_id,
                phone,
                inbound_text,
                cls,
                result,
                task_name,
                latency_ms,
                identity_id,
                deterministic_only,
            )
        except Exception as exc:  # noqa: BLE001 - observability must never fail a turn
            logger.error("turn_log write failed turn_id=%s: %s", turn_id, exc)
