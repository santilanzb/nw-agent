from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from ..models import TaskResult, TurnContext

logger = logging.getLogger(__name__)


@runtime_checkable
class TaskModule(Protocol):
    name: str
    handled_intents: frozenset[str]

    async def handle(self, ctx: TurnContext) -> TaskResult: ...


class RegistryCollision(RuntimeError):
    """Two task modules claimed the same intent. Raised at startup, never in a turn."""


class NoFallbackHandler(RuntimeError):
    """An intent reached the registry that nobody claimed, and no fallback is set."""


class TaskRegistry:
    """
    Explicit-claim registry: an intent belongs to exactly one task module.

    The previous first-match-wins lookup made every unclaimed intent land silently
    in whichever module registered first (in practice customer_service), so a
    typo in a package's seeds.yaml looked like working software. Collisions are now a
    startup error and unclaimed intents go to a fallback that logs loudly.
    """

    def __init__(self, fallback: TaskModule | None = None) -> None:
        self._tasks: list[TaskModule] = []
        self._by_intent: dict[str, TaskModule] = {}
        self._fallback = fallback

    def set_fallback(self, task: TaskModule) -> None:
        self._fallback = task

    def register(self, task: TaskModule) -> None:
        collisions = {
            intent: self._by_intent[intent].name
            for intent in task.handled_intents
            if intent in self._by_intent
        }
        if collisions:
            detail = ", ".join(f"{i} (claimed by {owner})" for i, owner in sorted(collisions.items()))
            raise RegistryCollision(f"task {task.name!r} re-claims intents: {detail}")

        self._tasks.append(task)
        for intent in task.handled_intents:
            self._by_intent[intent] = task

    def resolve(self, intent: str) -> TaskModule:
        task = self._by_intent.get(intent)
        if task is not None:
            return task

        if self._fallback is None:
            raise NoFallbackHandler(
                f"intent {intent!r} is claimed by no task module and no fallback is registered"
            )

        logger.error(
            "unclaimed_intent intent=%s fallback=%s — either add it to a package's "
            "handled_intents or drop it from that package's seeds.yaml",
            intent,
            self._fallback.name,
        )
        return self._fallback

    @property
    def tasks(self) -> list[TaskModule]:
        return list(self._tasks)

    def claimed_intents(self) -> frozenset[str]:
        return frozenset(self._by_intent)
