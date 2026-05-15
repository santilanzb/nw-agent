"""
Turn state machine for the NutriWhite Brain agent-core.

Flow per inbound message:
  0. Skip: fromMe / status / empty
  1. Group messages → group_turn handler (team claim/resume commands)
  2. DM: check handoff state → mute if active
  3. Classify intent
  4. Build TurnContext
  5. Task.handle → TaskResult
  6. Fire side-effects: handoff write, team push
  7. Send reply via WAHA
  8. Write turn_log (fire-and-forget)
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from collections import OrderedDict

from .brain.turn_log import TurnLogWriter
from .models import (
    ClassificationResult,
    TaskResult,
    TurnContext,
    WahaInboundMessage,
)
from .routing.classifier_client import ClassifierClient
from .routing.handoff_client import HandoffClient
from .tasks.base import TaskRegistry
from .transport.waha import WahaClient

logger = logging.getLogger(__name__)

# Simple in-memory LRU dedup: skip message IDs we've already processed
_SEEN: "OrderedDict[str, None]" = OrderedDict()
_SEEN_MAX = 10_000

_GUTTY_MENTION = re.compile(r"@[Gg]utty\s*", re.IGNORECASE)
_PHONE_RE = re.compile(r"\+?\d{7,15}")


def _mark_seen(event_id: str) -> bool:
    """Return True if this event_id was already seen (duplicate). Adds to cache."""
    if event_id in _SEEN:
        return True
    _SEEN[event_id] = None
    if len(_SEEN) > _SEEN_MAX:
        _SEEN.popitem(last=False)
    return False


class TurnFSM:
    def __init__(
        self,
        *,
        waha: WahaClient,
        classifier: ClassifierClient,
        handoff_client: HandoffClient,
        registry: TaskRegistry,
        turn_log: TurnLogWriter,
        team_group_jid: str,
        database_url: str,
    ) -> None:
        self._waha = waha
        self._classifier = classifier
        self._handoff = handoff_client
        self._registry = registry
        self._turn_log = turn_log
        self._team_group_jid = team_group_jid
        self._database_url = database_url

    async def handle(self, msg: WahaInboundMessage) -> None:
        # ── 0. Bail-outs ──────────────────────────────────────────────────────
        if msg.from_me:
            return
        if msg.is_status:
            return
        if _mark_seen(msg.event_id):
            logger.debug("duplicate event_id=%s — skipped", msg.event_id)
            return

        # ── 1. Group messages ─────────────────────────────────────────────────
        if msg.is_group:
            await self._handle_group_turn(msg)
            return

        # ── 2–8. DM flow ──────────────────────────────────────────────────────
        await self._handle_dm_turn(msg)

    # ── DM turn ───────────────────────────────────────────────────────────────

    async def _handle_dm_turn(self, msg: WahaInboundMessage) -> None:
        t0 = time.monotonic()
        turn_id = uuid.uuid4()
        phone = msg.phone

        # 2. Handoff mute
        try:
            is_muted = await self._handoff.check_active(phone)
        except Exception as exc:
            logger.warning("handoff check failed (fail-open) phone=%s: %s", phone, exc)
            is_muted = False

        if is_muted:
            await self._turn_log.write(
                turn_id=turn_id,
                phone=phone,
                inbound_text=msg.text,
                cls=None,
                result=TaskResult(
                    reply_text=None,
                    task_outcome="silent",
                    composed_by_llm=False,
                ),
                task_name="muted_handoff",
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
            return

        # 3. Classify
        cls: ClassificationResult | None = None
        try:
            cls = await self._classifier.classify(msg.text)
        except Exception as exc:
            logger.error("classify_intent failed phone=%s: %s", phone, exc)
            # Fail to LLM fallback
            cls = ClassificationResult(
                intent="unknown",
                confidence=0.0,
                decision="fallback_llm",
                dispatch=None,
                top_matches=[],
            )

        # 4. Build TurnContext
        ctx = TurnContext(
            turn_id=turn_id,
            phone=phone,
            contact_id=None,
            inbound_text=msg.text,
            inbound_event_id=msg.event_id,
            classification=cls,
            sender_name=msg.sender_name,
            is_group=False,
        )

        # 5. Task.handle
        task = self._registry.resolve(cls.intent)
        result: TaskResult
        try:
            result = await task.handle(ctx)
        except Exception as exc:
            logger.error(
                "task.handle failed intent=%s phone=%s: %s", cls.intent, phone, exc
            )
            result = TaskResult(
                reply_text="Tengo un problema técnico, ya te conecto con una asesora 🩵",
                task_outcome="error",
            )

        # 6. Side-effects
        if result.handoff:
            await self._fire_handoff(phone, result, ctx)

        # 7. Reply
        if result.reply_text:
            dm_jid = self._waha.dm_jid(phone)
            for attempt in range(3):
                try:
                    await self._waha.send_text(dm_jid, result.reply_text)
                    break
                except Exception as exc:
                    if attempt < 2:
                        await asyncio.sleep(0.5)
                    else:
                        logger.error("WAHA send failed after 3 attempts phone=%s: %s", phone, exc)
                        result = TaskResult(
                            reply_text=result.reply_text,
                            task_outcome="error",
                            handoff=result.handoff,
                        )

        # 8. Turn log (fire-and-forget — don't block the response)
        latency_ms = int((time.monotonic() - t0) * 1000)
        asyncio.create_task(
            self._turn_log.write(
                turn_id=turn_id,
                phone=phone,
                inbound_text=msg.text,
                cls=cls,
                result=result,
                task_name=task.name,
                latency_ms=latency_ms,
            )
        )

        logger.info(
            "turn turn_id=%s intent=%s decision=%s outcome=%s composed=%s latency_ms=%d",
            turn_id,
            cls.intent,
            cls.decision,
            result.task_outcome,
            result.composed_by_llm,
            latency_ms,
        )

    async def _fire_handoff(
        self, phone: str, result: TaskResult, ctx: TurnContext
    ) -> None:
        h = result.handoff
        assert h is not None  # checked by caller

        # Write handoff state row
        try:
            await self._handoff.create_handoff(
                contact_phone=phone,
                reason=h.reason,
                priority=h.priority,
                contact_id=h.contact_id,
                patient_name=h.patient_name,
                last_message=h.last_message,
                conversation_id=h.conversation_id,
            )
        except Exception as exc:
            logger.error("handoff create failed phone=%s: %s", phone, exc)

        # Team-group push
        if self._team_group_jid and result.team_notification_text:
            try:
                await self._waha.send_to_group(
                    self._team_group_jid, result.team_notification_text
                )
            except Exception as exc:
                logger.warning("team-group push failed: %s", exc)

    # ── Group turn: team claim / resume commands ──────────────────────────────

    async def _handle_group_turn(self, msg: WahaInboundMessage) -> None:
        if not self._team_group_jid:
            return

        # Only respond in the team group
        if msg.group_jid != self._team_group_jid:
            return

        text = msg.text.strip()
        # Strip @Gutty mention
        command = _GUTTY_MENTION.sub("", text).strip()

        phone_match = _PHONE_RE.search(command)
        target_phone = phone_match.group(0) if phone_match else None
        if target_phone and not target_phone.startswith("+"):
            target_phone = "+" + target_phone

        claimer_phone = msg.participant_phone or msg.phone
        claimer_name = msg.sender_name or claimer_phone or "Equipo"

        lower = command.lower()

        if lower.startswith("resume") or lower.startswith("ya terminé") or lower.startswith("ya termine"):
            if not target_phone:
                return
            await self._cmd_resume(msg, target_phone)

        elif lower.startswith("tomo") or lower.startswith("toma"):
            if not target_phone:
                return
            await self._cmd_claim(msg, target_phone, claimer_phone, claimer_name)

    async def _cmd_resume(self, msg: WahaInboundMessage, patient_phone: str) -> None:
        assert msg.group_jid is not None
        try:
            data = await self._handoff.resume(patient_phone)
            if data.get("success"):
                reply = f"✅ Caso cerrado. Vuelvo a atender a {patient_phone} 🩵"
            else:
                reason = data.get("reason", "not_found")
                reply = f"No tengo handoff activo para {patient_phone} ({reason})."
        except Exception as exc:
            logger.error("resume command failed: %s", exc)
            reply = f"Error al cerrar el handoff de {patient_phone}."
        await self._waha.send_to_group(msg.group_jid, reply)

    async def _cmd_claim(
        self,
        msg: WahaInboundMessage,
        patient_phone: str,
        claimer_phone: str,
        claimer_name: str,
    ) -> None:
        assert msg.group_jid is not None
        try:
            data = await self._handoff.claim(patient_phone, claimer_phone, claimer_name)
            if data.get("success"):
                reply = f"✅ Listo, {claimer_name}. Tomas el caso de {patient_phone}."
            else:
                reason = data.get("reason", "")
                state = data.get("state", {})
                if reason == "already_claimed":
                    by = state.get("claimed_by_name", "alguien más")
                    reply = f"Ese caso ya lo tomó {by}."
                else:
                    reply = f"No tengo handoff activo para {patient_phone}."
        except Exception as exc:
            logger.error("claim command failed: %s", exc)
            reply = f"Error al tomar el caso de {patient_phone}."
        await self._waha.send_to_group(msg.group_jid, reply)
