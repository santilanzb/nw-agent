from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import TaskResult, TurnContext


@runtime_checkable
class TaskModule(Protocol):
    name: str
    handled_intents: frozenset[str]

    async def handle(self, ctx: TurnContext) -> TaskResult: ...


class TaskRegistry:
    def __init__(self) -> None:
        self._tasks: list[TaskModule] = []

    def register(self, task: TaskModule) -> None:
        self._tasks.append(task)

    def resolve(self, intent: str) -> TaskModule:
        for task in self._tasks:
            if intent in task.handled_intents:
                return task
        # Default to the first registered task (customer_service)
        return self._tasks[0]
