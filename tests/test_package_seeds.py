"""
What the shipped customer_service seeds actually say.

`test_intent_classifier.py` was doing two jobs: decision logic (thresholds,
tie-break, disabled embeddings) and pinning the real seed file's dispatch
payloads. The second job belongs here, at the source, where it does not need a
mocked database to make its point.

These assertions are about the *contract with the runtime*: an intent whose
dispatch tool changes reroutes live traffic, and `dispatch.params` is passed
straight through to the handoff as `reason` and `priority`.
"""
from __future__ import annotations

import pytest

from company_agent.packages.registry import discover_manifests, merge_seeds

PACKAGES = discover_manifests()
MERGED = merge_seeds(PACKAGES)


def test_exactly_one_package_is_installed() -> None:
    assert [p.name for p in PACKAGES] == ["customer_service"]


def test_every_seeded_intent_survived_the_move() -> None:
    """22 intents, 281 examples — the counts before the package migration."""
    assert len(MERGED) == 22
    assert sum(len(intent.examples) for intent in MERGED.values()) == 281


def test_a_deterministic_faq_dispatches_to_its_own_tool() -> None:
    assert MERGED["faq_location"].dispatch.tool == "faq_location"


def test_a_handoff_intent_carries_its_reason_and_priority() -> None:
    dispatch = MERGED["handoff_medical_advice"].dispatch
    assert dispatch.tool == "handoff_human"
    assert dispatch.params["reason"] == "medical_advice"
    assert dispatch.params["priority"] == "high"


def test_a_conversational_intent_dispatches_to_no_tool() -> None:
    assert MERGED["acknowledgment"].dispatch.tool is None


@pytest.mark.parametrize("intent_class", sorted(MERGED))
def test_every_intent_has_examples_and_a_description(intent_class: str) -> None:
    intent = MERGED[intent_class]
    assert intent.examples, f"{intent_class} can never be classified"
    assert intent.description.strip()


def test_unknown_is_claimed_but_never_seeded() -> None:
    """
    `unknown` is synthesised by the FSM when the classifier call fails and by
    rag-api when embeddings are off. It must be handled by exactly one package
    and must not be seeded, or it would compete in the nearest-neighbour query.
    """
    (package,) = PACKAGES
    assert "unknown" in package.manifest.synthetic_intents
    assert "unknown" not in MERGED
    assert "unknown" in package.handled_intents
