"""
The tracer must never be able to cost a patient their answer.

It did. Langfuse's v3 SDK dropped `.trace()`, the call sat outside the try, and
every composed reply raised `AttributeError` *before the model was ever called*.
The patient got the canned failure line, the log said "compose failed", and
nothing pointed at the observability library — verified live on 2026-08-12, on
the first two real messages this deployment ever answered.

Tracing is a side effect. Its failure modes — a changed API, a host that is down,
a full disk — belong nowhere near the path of a reply.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, ClassVar

import pytest

from company_agent.agent_core.llm.anthropic import LLMClient


class _Usage:
    input_tokens = 11
    output_tokens = 22


class _Block:
    text = "Claro que sí, te cuento 🩵"


class _Response:
    content: ClassVar[list[_Block]] = [_Block()]
    usage = _Usage()


def _client_with_tracer(tracer: Any) -> LLMClient:
    client = LLMClient(api_key="test-key", default_model="m", escalation_model="m")
    client._lf = tracer

    async def fake_create(**_: object) -> _Response:
        return _Response()

    client._client.messages.create = fake_create  # type: ignore[method-assign]
    return client


def _compose(client: LLMClient) -> tuple[str, int, int]:
    return asyncio.run(
        client.compose(
            turn_id=uuid.uuid4(),
            tier="escalation",
            system="eres Gutty",
            user_message="hola",
        )
    )


class _V3Langfuse:
    """The real shape of the failure: v3 has no `.trace`."""

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(f"'Langfuse' object has no attribute '{name}'")


class _ExplodingTracer:
    def trace(self, **_: object) -> Any:
        raise RuntimeError("langfuse host unreachable")

    def flush(self) -> None:
        raise RuntimeError("still unreachable")


class _HalfBrokenTracer:
    """Starts fine, dies on close — after the model has already answered."""

    def trace(self, **_: object) -> Any:
        return self

    def generation(self, **_: object) -> Any:
        return self

    def end(self, **_: object) -> None:
        raise RuntimeError("died on close")

    def flush(self) -> None:
        raise RuntimeError("died on flush")


@pytest.mark.parametrize(
    "tracer", [_V3Langfuse(), _ExplodingTracer(), _HalfBrokenTracer()],
    ids=["v3-sdk-has-no-trace", "host-unreachable", "dies-on-close"],
)
def test_a_broken_tracer_still_answers_the_patient(tracer: Any) -> None:
    text, tokens_in, tokens_out = _compose(_client_with_tracer(tracer))
    assert text == "Claro que sí, te cuento 🩵"
    assert (tokens_in, tokens_out) == (11, 22)


def test_a_real_model_failure_still_raises() -> None:
    """
    The other half. Swallowing tracing errors must not swallow the one error the
    task layer needs, or a dead model becomes an empty reply instead of a handoff.
    """
    client = _client_with_tracer(_HalfBrokenTracer())

    async def exploding_create(**_: object) -> _Response:
        raise RuntimeError("anthropic is down")

    client._client.messages.create = exploding_create  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="anthropic is down"):
        _compose(client)


def test_a_tracer_without_trace_is_disabled_at_construction(monkeypatch) -> None:
    """
    Detected once, not raised on every patient. This is the check that turns the
    v3 incompatibility from an outage into a log line.
    """
    import sys

    fake_module = type("M", (), {"Langfuse": lambda **_: _V3Langfuse()})
    monkeypatch.setitem(sys.modules, "langfuse", fake_module)

    client = LLMClient(api_key="test-key", default_model="m", escalation_model="m")
    assert client._init_langfuse("pk", "sk", "http://langfuse") is None


def test_no_keys_means_no_tracer_and_no_complaint() -> None:
    client = LLMClient(api_key="test-key", default_model="m", escalation_model="m")
    assert client._init_langfuse("", "", "") is None
