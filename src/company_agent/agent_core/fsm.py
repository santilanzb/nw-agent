"""
Turn state machine for the NutriWhite Brain agent-core.

Flow per inbound event (already durable in intake_events before we get here):

  0. Skip: fromMe / status
  1. Group  -> team claim/resume commands
  2. DM     -> handoff mute check (fail-degraded) -> media gate -> classify
               -> task -> side effects -> send via the outbox -> turn_log

Every identifier on this path derives from the inbound event, not from wall
clock or randomness, so a sweeper re-drive of the same event produces the same
turn_id and the same send idempotency keys — and therefore answers exactly once.
"""
from __future__ import annotations

import logging
import re
import time
import uuid

from .brain.episodes import EpisodeStore
from .brain.turn_log import TurnLogWriter
from .identity import IdentityBroker, canonicalize
from .models import ClassificationResult, HandoffArgs, TaskResult, TurnContext
from .outbox.sender import SendOutbox
from .routing.classifier_client import ClassifierClient
from .routing.handoff_client import HandoffClient
from .tasks.base import TaskRegistry
from .transport.base import InboundEvent, Transport

logger = logging.getLogger(__name__)

_GUTTY_MENTION = re.compile(r"@[Gg]utty\s*", re.IGNORECASE)

# Matches a phone the way a person types one into a group chat: digits with
# spaces, dots, dashes or parentheses between them.
#
# The previous pattern was `\+?\d{7,15}`, which requires seven *consecutive*
# digits — so "@Gutty tomo +58 414 561 0594" matched nothing at all and the
# command was silently ignored. An asesora who typed the number the way it
# appears on a screen got no reply and no error, and the bot kept answering a
# patient she had just claimed.
_PHONE_RE = re.compile(r"\+?\d[\d\s.()\-]{5,24}\d")
_MIN_PHONE_DIGITS = 7

# Gutty cannot read an image or hear a voice note. Until a PHI-safe transcription
# decision exists, media is acknowledged and routed to a human rather than
# silently dropped, which is what waha.py:42 used to do to every payment proof.
MEDIA_ACK = (
    "Recibí tu archivo 🩵 Se lo paso a una asesora para que lo revise y te responda."
)


def _target_phone(command: str) -> str | None:
    """
    The number an asesora meant in "@Gutty tomo +58 414 561 0594".

    Picks the candidate carrying the most digits, so a stray "3R" or a ticket
    reference in the same message cannot win over the actual phone. Returns the
    canonical E.164, which is what `handoff_state.contact_phone` is keyed on.
    """
    best: str | None = None
    for match in _PHONE_RE.finditer(command):
        canonical = canonicalize(match.group(0))
        digits = canonical.wa_id
        if len(digits) < _MIN_PHONE_DIGITS:
            continue
        if best is None or len(digits) > len(canonicalize(best).wa_id):
            best = canonical.e164
    return best


def turn_id_for(event: InboundEvent) -> uuid.UUID:
    """
    Deterministic turn id.

    A random uuid4 per attempt meant a re-driven event produced a new turn_id, a
    new turn_log row and — worse — a new send idempotency key, so the patient got
    the reply twice. Deriving it from the event makes the whole turn replayable.
    """
    return uuid.uuid5(uuid.NAMESPACE_URL, f"nw-agent:turn:{event.source}:{event.source_event_id}")


class TurnFSM:
    def __init__(
        self,
        *,
        transport: Transport,
        outbox: SendOutbox,
        classifier: ClassifierClient,
        handoff_client: HandoffClient,
        registry: TaskRegistry,
        turn_log: TurnLogWriter,
        team_group_jid: str,
        identity: IdentityBroker | None = None,
        episodes: EpisodeStore | None = None,
    ) -> None:
        self._transport = transport
        self._outbox = outbox
        self._classifier = classifier
        self._handoff = handoff_client
        self._registry = registry
        self._turn_log = turn_log
        self._team_group_jid = team_group_jid
        self._identity = identity
        self._episodes = episodes

    async def handle(self, event: InboundEvent) -> None:
        if event.from_me or event.is_status:
            return
        if event.is_group:
            await self._handle_group_turn(event)
            return
        await self._handle_dm_turn(event)

    # -- DM turn --------------------------------------------------------------

    async def _handle_dm_turn(self, event: InboundEvent) -> None:
        t0 = time.monotonic()
        turn_id = turn_id_for(event)
        phone = event.conversation_key

        # Who is this? Resolved once, before anything else reads the number.
        # Degrades to None rather than failing the turn — an unidentified
        # patient still gets an answer; they just have no durable history yet.
        identity_id = None
        if self._identity is not None:
            record = await self._identity.resolve(
                canonicalize(phone), display_name=event.sender_name
            )
            if record is not None:
                identity_id = record.id
                if record.needs_review:
                    logger.warning(
                        "identity %s needs review — two addresses resolve to one number",
                        record.id,
                    )

        # Handoff mute, fail-degraded. An unreachable crm-adapter must never be
        # read as "no human is on this conversation".
        deterministic_only = False
        try:
            is_muted = await self._handoff.check_active(phone)
        except Exception as exc:  # noqa: BLE001 - degrade, never fail open
            logger.error(
                "handoff check failed phone=%s: %s - degrading to deterministic-only",
                phone,
                exc,
            )
            is_muted = False
            deterministic_only = True

        if is_muted:
            await self._turn_log.write(
                turn_id=turn_id,
                phone=phone,
                inbound_text=event.text,
                cls=None,
                result=TaskResult(reply_text=None, task_outcome="silent", composed_by_llm=False),
                task_name="muted_handoff",
                latency_ms=int((time.monotonic() - t0) * 1000),
                identity_id=identity_id,
                deterministic_only=deterministic_only,
            )
            return

        # Media gate, before classification: the classifier embeds text, and a
        # caption is not the content of a payment receipt.
        if event.media is not None and not event.has_text:
            await self._handle_media_turn(event, turn_id, t0, identity_id=identity_id)
            return

        cls: ClassificationResult
        try:
            cls = await self._classifier.classify(event.text)
        except Exception as exc:  # noqa: BLE001 - classifier down falls through to the task layer
            logger.error("classify_intent failed phone=%s: %s", phone, exc)
            cls = ClassificationResult(
                intent="unknown",
                confidence=0.0,
                decision="fallback_llm",
                dispatch=None,
                top_matches=[],
            )

        ctx = TurnContext(
            turn_id=turn_id,
            phone=phone,
            contact_id=None,
            inbound_text=event.text,
            inbound_event_id=event.source_event_id,
            classification=cls,
            identity_id=identity_id,
            sender_name=event.sender_name,
            is_group=False,
            deterministic_only=deterministic_only,
        )

        task = self._registry.resolve(cls.intent)
        try:
            result = await task.handle(ctx)
        except Exception as exc:  # noqa: BLE001 - a task defect must not lose the patient
            logger.error("task.handle failed intent=%s phone=%s: %s", cls.intent, phone, exc)
            result = TaskResult(
                reply_text="Tengo un problema técnico, ya te conecto con una asesora 🩵",
                task_outcome="error",
            )

        if result.handoff:
            await self._fire_handoff(phone, result, ctx)

        if result.reply_text:
            await self._reply(event, turn_id, result.reply_text)

        # True when the answer could draw on this conversation's history: the
        # column has read `false` on every row since it existed.
        episodic_used = bool(
            result.composed_by_llm and self._episodes is not None and identity_id is not None
        )

        if self._episodes is not None:
            await self._episodes.record(
                identity_id=identity_id,
                contact_phone=phone,
                turn_id=turn_id,
                inbound_text=event.text,
                reply_text=result.reply_text,
                intent=cls.intent,
                confidence=cls.confidence,
                decision=cls.decision,
                task=task.name,
                composed_by_llm=result.composed_by_llm,
                model_used=result.model_used,
            )

        latency_ms = int((time.monotonic() - t0) * 1000)
        await self._turn_log.write(
            turn_id=turn_id,
            phone=phone,
            inbound_text=event.text,
            cls=cls,
            result=result,
            task_name=task.name,
            latency_ms=latency_ms,
            identity_id=identity_id,
            deterministic_only=deterministic_only,
            episodic_used=episodic_used,
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

    async def _handle_media_turn(
        self,
        event: InboundEvent,
        turn_id: uuid.UUID,
        t0: float,
        *,
        identity_id: uuid.UUID | None = None,
    ) -> None:
        assert event.media is not None
        kind = event.media.kind
        logger.info("media turn turn_id=%s kind=%s", turn_id, kind)

        result = TaskResult.with_handoff(
            reply_text=MEDIA_ACK,
            handoff=HandoffArgs(
                reason=f"media_{kind}",
                priority="normal",
                patient_name=event.sender_name,
            ),
        )
        await self._fire_handoff(event.conversation_key, result, None)
        await self._reply(event, turn_id, MEDIA_ACK)
        await self._turn_log.write(
            turn_id=turn_id,
            phone=event.conversation_key,
            inbound_text=f"[{kind}]",
            cls=None,
            result=result,
            task_name="media_deflect",
            latency_ms=int((time.monotonic() - t0) * 1000),
            identity_id=identity_id,
        )

    async def _reply(self, event: InboundEvent, turn_id: uuid.UUID, text: str) -> None:
        await self._outbox.send(
            transport=self._transport.name,
            recipient=self._transport.address_for(event.conversation_key),
            text=text,
            message_class="reply",
            # Keyed on the inbound event, so a re-drive cannot double-answer.
            idempotency_key=f"{event.source}:{event.source_event_id}:reply",
            turn_id=turn_id,
        )

    async def _fire_handoff(
        self, phone: str, result: TaskResult, ctx: TurnContext | None
    ) -> None:
        h = result.handoff
        assert h is not None

        try:
            await self._handoff.create_handoff(
                contact_phone=phone,
                reason=h.reason,
                priority=h.priority,
                contact_id=h.contact_id,
                patient_name=h.patient_name,
                # By-reference: the patient's words do not go into the Zoho Note.
                # The asesora opens the conversation, which she can already read.
                last_message=None,
                conversation_id=h.conversation_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("handoff create failed phone=%s: %s", phone, exc)

        if self._team_group_jid and ctx is not None:
            await self._notify_team(phone, h.reason, ctx)

    async def _notify_team(self, phone: str, reason: str, ctx: TurnContext) -> None:
        text = self._build_team_notification(phone, reason, ctx)
        try:
            await self._outbox.send(
                transport=self._transport.name,
                recipient=self._team_group_jid,
                text=text,
                message_class="team",
                idempotency_key=f"turn:{ctx.turn_id}:team",
                turn_id=ctx.turn_id,
            )
        except Exception as exc:  # noqa: BLE001 - a failed team ping must not fail the turn
            logger.warning("team-group push failed: %s", exc)

    def _build_team_notification(self, phone: str, reason: str, ctx: TurnContext) -> str:
        """
        By-reference. The patient's message is deliberately absent: raw turns in
        the team group are Art. 9 content in a store with no retention or erasure
        path. The asesora opens the chat, where she can read everything.
        """
        label = ctx.sender_name or phone
        return (
            f"🚨 *Handoff* — {label}\n"
            f"📱 {phone}\n"
            f"Motivo: {reason} · Intención: {ctx.classification.intent}\n"
            f"Ref: {str(ctx.turn_id)[:8]}\n\n"
            'Quien toma el caso, responde "TOMO" en este grupo.'
        )

    # -- Group turn: team claim / resume commands ------------------------------

    async def _handle_group_turn(self, event: InboundEvent) -> None:
        if not self._team_group_jid or event.group_id != self._team_group_jid:
            return

        command = _GUTTY_MENTION.sub("", event.text.strip()).strip()
        target_phone = _target_phone(command)

        claimer_phone = event.sender_e164 or event.conversation_key
        claimer_name = event.sender_name or claimer_phone or "Equipo"
        lower = command.lower()

        if not target_phone:
            return
        if lower.startswith(("resume", "ya terminé", "ya termine")):
            await self._cmd_resume(event, target_phone)
        elif lower.startswith(("tomo", "toma")):
            await self._cmd_claim(event, target_phone, claimer_phone, claimer_name)

    async def _group_reply(self, event: InboundEvent, text: str) -> None:
        assert event.group_id is not None
        await self._outbox.send(
            transport=self._transport.name,
            recipient=event.group_id,
            text=text,
            message_class="team",
            idempotency_key=f"{event.source}:{event.source_event_id}:group-reply",
        )

    async def _cmd_resume(self, event: InboundEvent, patient_phone: str) -> None:
        try:
            data = await self._handoff.resume(patient_phone)
            if data.get("success"):
                reply = f"✅ Caso cerrado. Vuelvo a atender a {patient_phone} 🩵"
            else:
                reply = (
                    f"No tengo handoff activo para {patient_phone} "
                    f"({data.get('reason', 'not_found')})."
                )
        except Exception as exc:  # noqa: BLE001
            logger.error("resume command failed: %s", exc)
            reply = f"Error al cerrar el handoff de {patient_phone}."
        await self._group_reply(event, reply)

    async def _cmd_claim(
        self,
        event: InboundEvent,
        patient_phone: str,
        claimer_phone: str,
        claimer_name: str,
    ) -> None:
        try:
            data = await self._handoff.claim(patient_phone, claimer_phone, claimer_name)
            if data.get("success"):
                reply = f"✅ Listo, {claimer_name}. Tomas el caso de {patient_phone}."
            elif data.get("reason") == "already_claimed":
                by = (data.get("state") or {}).get("claimed_by_name", "alguien más")
                reply = f"Ese caso ya lo tomó {by}."
            else:
                reply = f"No tengo handoff activo para {patient_phone}."
        except Exception as exc:  # noqa: BLE001
            logger.error("claim command failed: %s", exc)
            reply = f"Error al tomar el caso de {patient_phone}."
        await self._group_reply(event, reply)
