"""
Installing packages into a registry.

The registrar is the only module allowed to import a task module. What it must
get right: the intents a task claims are *derived* from its package's seeds, and
the name it reports matches the name its manifest declares — because that string
is written to `turn_log.task` and identifies which module answered a patient.
"""
from __future__ import annotations

import pytest

from company_agent.agent_core.tasks.base import RegistryCollision, TaskRegistry
from company_agent.packages.registrar import build_task, install_packages
from company_agent.packages.registry import MalformedPackage, discover_manifests

# The union that `CustomerServiceTask.handled_intents` was hand-maintained as,
# copied verbatim from before the package migration. The derived set must equal
# it exactly — that equality is what makes the move behaviour-preserving, and
# keeping the literal here is what would catch an accidental seed deletion.
INTENTS_BEFORE_THE_MOVE = {
    "faq_location",
    "faq_services",
    "faq_consultation_plans",
    "faq_payment_methods",
    "faq_consultation_call",
    "faq_protocol_3r",
    "faq_supplements_general",
    "faq_exams_general",
    "handoff_specialist_recommendation",
    "handoff_scheduling",
    "handoff_discount",
    "handoff_medical_advice",
    "handoff_refund",
    "handoff_post_payment_logistics",
    "handoff_english",
    "handoff_distress",
    "patient_plan_status",
    "patient_appointment_status",
    "patient_exam_status",
    "greeting",
    "farewell",
    "acknowledgment",
    "unknown",
}


class _NoLLM:
    """The task is constructed, never invoked, so the client is never touched."""


def test_installing_claims_exactly_the_intents_the_monolith_claimed() -> None:
    registry = TaskRegistry()
    install_packages(registry, llm=_NoLLM())
    assert registry.claimed_intents() == INTENTS_BEFORE_THE_MOVE


def test_the_claimed_intents_are_derived_not_declared() -> None:
    """
    The seeds are the source. If someone deletes an intent from seeds.yaml, the
    task stops claiming it — rather than claiming an intent that can never fire.
    """
    (package,) = discover_manifests()
    seeded = set(package.intents)
    assert package.handled_intents == seeded | {"unknown"}
    assert "unknown" not in seeded


def test_a_registered_task_resolves_for_its_intents() -> None:
    registry = TaskRegistry()
    install_packages(registry, llm=_NoLLM())
    assert registry.resolve("faq_location").name == "customer_service"
    assert registry.resolve("unknown").name == "customer_service"


def test_task_name_must_match_the_manifest() -> None:
    """turn_log.task is written from `.name`; a mismatch mislabels every row."""
    (package,) = discover_manifests()
    renamed = package.manifest.model_copy(update={"task_name": "something_else"})
    mismatched = type(package)(manifest=renamed, intents=package.intents)
    with pytest.raises(MalformedPackage, match="task_name"):
        build_task(mismatched, llm=_NoLLM())


def test_a_task_reference_that_does_not_resolve_fails_at_install() -> None:
    (package,) = discover_manifests()
    broken = package.manifest.model_copy(
        update={"task": "company_agent.packages.customer_service.task:NoSuchTask"}
    )
    with pytest.raises(MalformedPackage, match="no attribute"):
        build_task(type(package)(manifest=broken, intents=package.intents), llm=_NoLLM())


def test_installing_the_same_package_twice_is_a_collision() -> None:
    """Two packages claiming one intent must fail at startup, not first-match-win."""
    registry = TaskRegistry()
    install_packages(registry, llm=_NoLLM())
    with pytest.raises(RegistryCollision):
        install_packages(registry, llm=_NoLLM())
