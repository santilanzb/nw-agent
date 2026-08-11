"""
The seeder's two refusals.

Removing a package must remove its intents from `intent_vectors` — orphans are
not inert, because the classifier's nearest-neighbour query has no class filter,
so a patient can still classify to an intent nobody owns.

But a prune is a delete driven by what discovery found, and the dangerous case is
discovery finding *less than it should*. Package data that failed to install
produces an empty merge, and an unguarded prune would turn a bad build into a
dead classifier — while every host-side test still passed, because pytest reads
the source tree rather than the install.

No database: `_prune_orphans` takes a connection and these stub it.
"""
from __future__ import annotations

import logging

import pytest

from company_agent.intent_seeder.main import RefusedToPrune, _prune_orphans, sync_seeds

LOGGER = logging.getLogger("test-seeder")


class _FakeConn:
    """Records executed statements; answers the existing-classes query."""

    def __init__(self, existing: set[str]) -> None:
        self._existing = existing
        self.executed: list[tuple[str, dict | None]] = []

    def execute(self, sql: str, params: dict | None = None):
        self.executed.append((sql, params))

        class _Result:
            @staticmethod
            def fetchall() -> list[dict]:
                return [{"intent_class": name} for name in sorted(self._existing)]

        return _Result()

    @property
    def pruned(self) -> bool:
        return any("<> ALL" in sql for sql, _ in self.executed)


def test_an_orphaned_intent_class_is_pruned() -> None:
    conn = _FakeConn({"faq_location", "greeting", "retired_intent"})
    _prune_orphans(conn, {"faq_location", "greeting"}, logger=LOGGER, force=False)
    assert conn.pruned


def test_nothing_is_deleted_when_there_are_no_orphans() -> None:
    conn = _FakeConn({"faq_location", "greeting"})
    _prune_orphans(conn, {"faq_location", "greeting"}, logger=LOGGER, force=False)
    assert not conn.pruned


def test_a_prune_that_would_remove_most_classes_is_refused() -> None:
    """Four of five disappearing is a discovery failure, not a removal."""
    conn = _FakeConn({"a_intent", "b_intent", "c_intent", "d_intent", "e_intent"})
    with pytest.raises(RefusedToPrune, match="discovery failure"):
        _prune_orphans(conn, {"a_intent"}, logger=LOGGER, force=False)
    assert not conn.pruned


def test_force_allows_a_deliberate_large_prune() -> None:
    conn = _FakeConn({"a_intent", "b_intent", "c_intent", "d_intent", "e_intent"})
    _prune_orphans(conn, {"a_intent"}, logger=LOGGER, force=True)
    assert conn.pruned


def test_an_empty_discovery_refuses_to_touch_the_table(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    The build-failure case, and the reason the guard exists at all: if package
    data did not survive installation, discovery returns nothing and every row
    in intent_vectors looks orphaned.
    """
    monkeypatch.setattr("company_agent.intent_seeder.main.discover_manifests", list)
    monkeypatch.setattr("company_agent.intent_seeder.main.merge_seeds", lambda _packages: {})

    def _explode(*_args, **_kwargs):
        raise AssertionError("connected to the database on an empty discovery")

    monkeypatch.setattr("company_agent.intent_seeder.main.connect", _explode)

    with pytest.raises(RefusedToPrune, match="no function packages discovered"):
        sync_seeds(_settings())


def _settings():
    from company_agent.intent_seeder.config import IntentSeederSettings

    return IntentSeederSettings(DATABASE_URL="postgresql://unused/unused")
