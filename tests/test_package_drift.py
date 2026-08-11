"""
The drift check, and the difference between fatal and loud.

Manifests and tasks ship in the same build from the same repository. If they
disagree, no environment explains it — that is fatal. The database is
operational state a human fixes by re-running the seeder; refusing to boot over
it would convert a degraded classifier into a total outage.
"""
from __future__ import annotations

from company_agent.packages.drift import check_drift
from company_agent.packages.registry import discover_manifests


def test_a_healthy_build_reports_no_drift() -> None:
    report = check_drift(
        manifest_intents={"faq_location", "unknown"},
        claimed_intents={"faq_location", "unknown"},
        seeded_intents={"faq_location"},
        db_intents={"faq_location"},
    )
    assert not report.fatal
    assert not report.database_drift


def test_a_seeded_intent_no_task_claims_is_fatal() -> None:
    """Today this is discovered one patient at a time, by escalating them."""
    report = check_drift(
        manifest_intents={"faq_location", "faq_orphan"},
        claimed_intents={"faq_location"},
        seeded_intents={"faq_location", "faq_orphan"},
    )
    assert report.unclaimed == {"faq_orphan"}
    assert report.fatal == {"faq_orphan"}


def test_a_claimed_intent_no_package_declares_is_fatal() -> None:
    report = check_drift(
        manifest_intents={"faq_location"},
        claimed_intents={"faq_location", "faq_ghost"},
        seeded_intents={"faq_location"},
    )
    assert report.unseeded == {"faq_ghost"}
    assert report.fatal == {"faq_ghost"}


def test_a_synthetic_intent_is_not_expected_in_the_database() -> None:
    """
    `unknown` is emitted by the runtime, never classified. Comparing the declared
    set against the database would report it missing forever, and a check that
    always fires is a check nobody reads.
    """
    report = check_drift(
        manifest_intents={"faq_location", "unknown"},
        claimed_intents={"faq_location", "unknown"},
        seeded_intents={"faq_location"},
        db_intents={"faq_location"},
    )
    assert report.missing_from_db == frozenset()
    assert not report.database_drift


def test_stale_database_rows_are_loud_but_not_fatal() -> None:
    report = check_drift(
        manifest_intents={"faq_location"},
        claimed_intents={"faq_location"},
        seeded_intents={"faq_location"},
        db_intents={"faq_location", "removed_package_intent"},
    )
    assert report.orphaned_in_db == {"removed_package_intent"}
    assert report.database_drift
    assert not report.fatal


def test_an_unseeded_database_is_loud_but_not_fatal() -> None:
    report = check_drift(
        manifest_intents={"faq_location"},
        claimed_intents={"faq_location"},
        seeded_intents={"faq_location"},
        db_intents=set(),
    )
    assert report.missing_from_db == {"faq_location"}
    assert not report.fatal


def test_skipping_the_database_is_not_the_same_as_agreeing() -> None:
    report = check_drift(
        manifest_intents={"faq_location"},
        claimed_intents={"faq_location"},
        seeded_intents={"faq_location"},
        db_intents=None,
    )
    assert not report.database_drift


def test_the_shipped_package_does_not_drift_against_itself() -> None:
    """The real installed package, checked the way the lifespan checks it."""
    packages = discover_manifests()
    report = check_drift(
        manifest_intents={i for p in packages for i in p.handled_intents},
        claimed_intents={i for p in packages for i in p.handled_intents},
        seeded_intents={i for p in packages for i in p.intents},
    )
    assert not report.fatal
