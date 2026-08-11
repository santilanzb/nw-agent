"""
Unit tests for IntentClassifier decision logic.
Uses a mock EmbeddingClient and stub DB results — no Postgres or OpenAI required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from company_agent.rag_api.config import RagSettings
from company_agent.rag_api.intent import IntentClassifier, load_dispatch_table
from company_agent.rag_api.schemas import ClassifyIntentRequest


def _settings(**overrides) -> RagSettings:
    base = {"INTERNAL_API_KEY": "test"}
    base.update(overrides)
    return RagSettings(**base)


def _make_embedding_client(enabled: bool = True) -> MagicMock:
    client = MagicMock()
    client.enabled = enabled
    client.embed.return_value = [0.1] * 1536
    return client


def _make_classifier(settings: RagSettings | None = None, enabled: bool = True) -> IntentClassifier:
    s = settings or _settings()
    embeddings = _make_embedding_client(enabled=enabled)
    # The dispatch table comes from the installed function packages. Passing it
    # explicitly keeps these tests about decision logic while still exercising
    # the real seeds, so an assertion like "faq_location dispatches to
    # faq_location" continues to mean what it did before the package move.
    return IntentClassifier(
        settings=s, embeddings=embeddings, dispatch_table=load_dispatch_table()
    )


def _fake_rows(scores: list[tuple[str, float, str]]) -> list[dict]:
    return [
        {"intent_class": intent, "score": score, "example_text": example}
        for intent, score, example in scores
    ]


# ── Decision logic tests ─────────────────────────────────────────────────────

def test_execute_when_high_confidence():
    classifier = _make_classifier()
    rows = _fake_rows([
        ("faq_location", 0.92, "donde están ubicados"),
        ("faq_services", 0.70, "qué servicios tienen"),
    ])
    with patch("company_agent.rag_api.intent.connect") as mock_connect:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = rows
        mock_connect.return_value.__enter__.return_value = mock_conn

        result = classifier.classify(ClassifyIntentRequest(message="donde están ubicados"))

    assert result.decision == "execute"
    assert result.intent == "faq_location"
    assert result.confidence == pytest.approx(0.92, abs=1e-4)
    assert result.dispatch is not None
    assert result.dispatch.tool == "faq_location"


def test_clarify_when_mid_confidence():
    classifier = _make_classifier()
    rows = _fake_rows([
        ("handoff_scheduling", 0.71, "agendar cita"),
        ("faq_location", 0.50, "donde están"),
    ])
    with patch("company_agent.rag_api.intent.connect") as mock_connect:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = rows
        mock_connect.return_value.__enter__.return_value = mock_conn

        result = classifier.classify(ClassifyIntentRequest(message="agendar"))

    assert result.decision == "clarify"
    assert result.dispatch is None


def test_fallback_llm_when_low_confidence():
    classifier = _make_classifier()
    rows = _fake_rows([
        ("faq_location", 0.40, "donde están"),
    ])
    with patch("company_agent.rag_api.intent.connect") as mock_connect:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = rows
        mock_connect.return_value.__enter__.return_value = mock_conn

        result = classifier.classify(ClassifyIntentRequest(message="xyz"))

    assert result.decision == "fallback_llm"
    assert result.dispatch is None


def test_tiebreak_downgrades_to_clarify():
    classifier = _make_classifier()
    # Both intents score >= 0.80 and are within 0.05 margin
    rows = _fake_rows([
        ("handoff_specialist_recommendation", 0.85, "qué especialista"),
        ("handoff_scheduling", 0.83, "disponibilidad"),
    ])
    with patch("company_agent.rag_api.intent.connect") as mock_connect:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = rows
        mock_connect.return_value.__enter__.return_value = mock_conn

        result = classifier.classify(ClassifyIntentRequest(message="quién me puede atender"))

    assert result.decision == "clarify"
    assert result.dispatch is None


def test_tiebreak_does_not_trigger_if_top2_same_intent():
    """Same intent class in top-2 should not trigger tiebreak."""
    classifier = _make_classifier()
    rows = _fake_rows([
        ("faq_location", 0.90, "donde están"),
        ("faq_location", 0.88, "ubicación"),  # same class
    ])
    with patch("company_agent.rag_api.intent.connect") as mock_connect:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = rows
        mock_connect.return_value.__enter__.return_value = mock_conn

        result = classifier.classify(ClassifyIntentRequest(message="donde están"))

    assert result.decision == "execute"


def test_disabled_embeddings_returns_fallback():
    classifier = _make_classifier(enabled=False)
    result = classifier.classify(ClassifyIntentRequest(message="hola"))
    assert result.decision == "fallback_llm"
    assert result.intent == "unknown"
    assert result.confidence == 0.0


def test_handoff_dispatch_has_reason():
    classifier = _make_classifier()
    rows = _fake_rows([
        ("handoff_medical_advice", 0.91, "me duele el estómago"),
    ])
    with patch("company_agent.rag_api.intent.connect") as mock_connect:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = rows
        mock_connect.return_value.__enter__.return_value = mock_conn

        result = classifier.classify(ClassifyIntentRequest(message="me duele el estómago"))

    assert result.decision == "execute"
    assert result.dispatch is not None
    assert result.dispatch.tool == "handoff_human"
    assert result.dispatch.params.get("reason") == "medical_advice"


def test_acknowledgment_dispatch_tool_is_null():
    classifier = _make_classifier()
    rows = _fake_rows([
        ("acknowledgment", 0.93, "ok"),
    ])
    with patch("company_agent.rag_api.intent.connect") as mock_connect:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = rows
        mock_connect.return_value.__enter__.return_value = mock_conn

        result = classifier.classify(ClassifyIntentRequest(message="ok"))

    assert result.decision == "execute"
    assert result.dispatch is not None
    assert result.dispatch.tool is None
