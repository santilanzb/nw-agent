from __future__ import annotations

import pytest

from company_agent.agent_core.models import TaskResult
from company_agent.agent_core.tasks.base import (
    NoFallbackHandler,
    RegistryCollision,
    TaskRegistry,
)


class _Task:
    def __init__(self, name: str, intents: set[str]) -> None:
        self.name = name
        self.handled_intents = frozenset(intents)

    async def handle(self, ctx: object) -> TaskResult:
        return TaskResult.canned(self.name)


def test_resolve_returns_the_claiming_task() -> None:
    reg = TaskRegistry()
    greeter = _Task("greeter", {"greeting"})
    faqs = _Task("faqs", {"faq_location", "faq_services"})
    reg.register(greeter)
    reg.register(faqs)

    assert reg.resolve("faq_location") is faqs
    assert reg.resolve("greeting") is greeter


def test_collision_is_a_startup_error_naming_the_intent() -> None:
    reg = TaskRegistry()
    reg.register(_Task("customer_service", {"greeting", "farewell"}))

    with pytest.raises(RegistryCollision) as exc:
        reg.register(_Task("sales", {"greeting", "objection_price"}))

    assert "greeting" in str(exc.value)
    assert "customer_service" in str(exc.value)


def test_unclaimed_intent_goes_to_the_fallback_not_the_first_task() -> None:
    """
    The regression this guards: resolve() used to `return self._tasks[0]`, so a
    typo in intent_seeds.yaml silently answered as customer_service.
    """
    reg = TaskRegistry()
    first_registered = _Task("customer_service", {"greeting"})
    fallback = _Task("fallback", set())
    reg.register(first_registered)
    reg.set_fallback(fallback)

    resolved = reg.resolve("intent_que_nadie_reclamo")

    assert resolved is fallback
    assert resolved is not first_registered


def test_unclaimed_intent_without_a_fallback_raises() -> None:
    reg = TaskRegistry()
    reg.register(_Task("customer_service", {"greeting"}))

    with pytest.raises(NoFallbackHandler):
        reg.resolve("intent_que_nadie_reclamo")


def test_claimed_intents_reports_the_union() -> None:
    reg = TaskRegistry()
    reg.register(_Task("a", {"greeting", "farewell"}))
    reg.register(_Task("b", {"faq_location"}))

    assert reg.claimed_intents() == frozenset({"greeting", "farewell", "faq_location"})
