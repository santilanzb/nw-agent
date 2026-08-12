"""
Composed answers are grounded in retrieval and in the conversation so far.

`build_fallback_prompt` passed the patient's message and nothing else, so every
off-FAQ answer came from a model that knows nothing about NutriWhite. The system
prompt asked it not to invent prices — a request, not a mechanism.

These tests exercise the prompt builder and the task's grounding step directly.
Whether the *model* obeys is the eval harness's question; whether it is even
given the chance is this one's.
"""
from __future__ import annotations

import asyncio
import uuid

from company_agent.agent_core.brain.episodes import Episode
from company_agent.agent_core.llm.composition import build_fallback_prompt
from company_agent.agent_core.models import ClassificationResult, TurnContext
from company_agent.agent_core.routing.retrieval_client import RetrievedChunk
from company_agent.packages.customer_service.task import CustomerServiceTask


class _RecordingLLM:
    """Captures the prompt instead of composing."""

    def __init__(self) -> None:
        self.prompt: str | None = None

    def model(self, tier: str) -> str:
        return f"model-{tier}"

    async def compose(self, **kwargs) -> tuple[str, int, int]:
        self.prompt = kwargs["user_message"]
        return "respuesta", 10, 5


class _StubRetrieval:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self._chunks = chunks
        self.queries: list[str] = []

    async def retrieve(self, query: str, top_k: int = 4) -> list[RetrievedChunk]:
        self.queries.append(query)
        return self._chunks


class _StubEpisodes:
    def __init__(self, history: list[Episode]) -> None:
        self._history = history
        self.calls = 0

    async def recent(self, identity_id, limit: int = 6) -> list[Episode]:
        self.calls += 1
        return self._history


def _ctx(text: str, intent: str = "unknown", decision: str = "fallback_llm") -> TurnContext:
    return TurnContext(
        turn_id=uuid.uuid4(),
        phone="+584145610594",
        contact_id=None,
        inbound_text=text,
        inbound_event_id="evt-1",
        classification=ClassificationResult(
            intent=intent, confidence=0.2, decision=decision, dispatch=None, top_matches=[]
        ),
        identity_id=uuid.uuid4(),
    )


CHUNKS = [
    RetrievedChunk(
        content="El Protocolo 3R: Remover, Reponer, Recuperar.",
        source_uri="knowledge/raw/06_faq.md",
        score=0.9,
    )
]


# ── The prompt builder ───────────────────────────────────────────────────────

def test_an_ungrounded_prompt_still_works() -> None:
    prompt = build_fallback_prompt("hola")
    assert "hola" in prompt
    assert "asesora" in prompt


def test_retrieved_documentation_reaches_the_prompt() -> None:
    prompt = build_fallback_prompt("qué es el protocolo 3R", context=CHUNKS)
    assert "Remover, Reponer, Recuperar" in prompt
    assert "knowledge/raw/06_faq.md" in prompt


def test_grounded_prompts_forbid_deduction() -> None:
    """The instruction that makes an invented price a visible failure."""
    prompt = build_fallback_prompt("cuánto cuesta", context=CHUNKS)
    assert "ÚNICAMENTE" in prompt


def test_conversation_history_reaches_the_prompt() -> None:
    history = [
        Episode(direction="inbound", text="tienen plan de 3 consultas?"),
        Episode(direction="outbound", text="Sí, el plan de 3 consultas cuesta $559."),
    ]
    prompt = build_fallback_prompt("y cuánto cuesta ese?", history=history)
    assert "tienen plan de 3 consultas?" in prompt
    assert "Gutty: Sí, el plan de 3 consultas cuesta $559." in prompt
    # Without history "ese" has no antecedent and the model answers a question
    # nobody asked.
    assert prompt.index("tienen plan") < prompt.index("y cuánto cuesta ese?")


def test_context_is_bounded() -> None:
    """A long corpus must not push the patient's actual question out of the window."""
    huge = [
        RetrievedChunk(content="x" * 2000, source_uri=f"doc{i}.md", score=0.5) for i in range(10)
    ]
    prompt = build_fallback_prompt("pregunta", context=huge)
    assert len(prompt) < 8000
    assert "pregunta" in prompt


# ── The task's grounding step ────────────────────────────────────────────────

def _handle(task: CustomerServiceTask, ctx: TurnContext):
    return asyncio.run(task.handle(ctx))


def test_a_composed_turn_is_grounded() -> None:
    llm, retrieval, episodes = _RecordingLLM(), _StubRetrieval(CHUNKS), _StubEpisodes([])
    task = CustomerServiceTask(llm=llm, retrieval=retrieval, episodes=episodes)

    _handle(task, _ctx("qué es el protocolo 3R"))

    assert retrieval.queries == ["qué es el protocolo 3R"]
    assert episodes.calls == 1
    assert "Remover, Reponer, Recuperar" in llm.prompt


def test_a_deterministic_turn_pays_for_no_retrieval() -> None:
    """
    An FAQ hit answers from a constant. Embedding the message and reading the
    conversation history would be latency on the hot path for nothing.
    """
    llm, retrieval, episodes = _RecordingLLM(), _StubRetrieval(CHUNKS), _StubEpisodes([])
    task = CustomerServiceTask(llm=llm, retrieval=retrieval, episodes=episodes)

    result = _handle(task, _ctx("dónde están", intent="faq_location", decision="execute"))

    assert result.composed_by_llm is False
    assert retrieval.queries == []
    assert episodes.calls == 0


def test_the_real_client_degrades_instead_of_raising() -> None:
    """
    Retrieval is additive, so its failure must not become the turn's failure.
    Pointed at a port nothing is listening on: the client returns no context and
    the caller composes ungrounded.
    """
    from company_agent.agent_core.routing.retrieval_client import RetrievalClient

    client = RetrievalClient(base_url="http://127.0.0.1:1", api_key="k")

    async def scenario():
        try:
            return await client.retrieve("cualquier cosa")
        finally:
            await client.aclose()

    assert asyncio.run(scenario()) == []


def test_a_retrieval_outage_still_produces_a_composed_answer() -> None:
    """
    The whole point of degrading rather than raising: the patient gets a real
    answer, hedged by the ungrounded prompt's instruction to defer to an asesora
    — not the canned technical-problem line.
    """

    class _EmptyRetrieval:
        async def retrieve(self, query: str, top_k: int = 4):
            return []

    llm = _RecordingLLM()
    task = CustomerServiceTask(llm=llm, retrieval=_EmptyRetrieval(), episodes=_StubEpisodes([]))

    result = _handle(task, _ctx("algo raro"))

    assert result.composed_by_llm is True
    assert "ÚNICAMENTE" not in llm.prompt
    assert "asesora" in llm.prompt
