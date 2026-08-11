"""
Reading dispatch from Postgres, and reloading it without a restart.

The seeder has always written `metadata = {"dispatch": ...}` onto every
`intent_vectors` row; rag-api never read it and parsed a YAML file instead. That
let the two disagree — the seeder read a bind-mounted copy while rag-api read the
one baked into its image — with nothing detecting it.

Reading dispatch from the same rows the vectors live in makes that class of
disagreement impossible.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from company_agent.rag_api.config import RagSettings
from company_agent.rag_api.intent import IntentClassifier, load_dispatch_table_from_db


def _settings() -> RagSettings:
    return RagSettings(INTERNAL_API_KEY="test")


def _rows(*pairs: tuple[str, dict | None]) -> list[dict]:
    return [{"intent_class": name, "metadata": meta} for name, meta in pairs]


def _with_rows(rows: list[dict]):
    """Patch the sync connection the classifier uses, returning `rows`."""
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = rows
    patcher = patch("company_agent.rag_api.intent.connect")
    mock_connect = patcher.start()
    mock_connect.return_value.__enter__.return_value = mock_conn
    return patcher


def test_dispatch_is_read_from_the_metadata_column() -> None:
    patcher = _with_rows(
        _rows(
            ("faq_location", {"dispatch": {"tool": "faq_location", "params": {}}}),
            (
                "handoff_medical_advice",
                {"dispatch": {"tool": "handoff_human", "params": {"reason": "medical_advice"}}},
            ),
        )
    )
    try:
        table = load_dispatch_table_from_db("postgresql://unused/unused")
    finally:
        patcher.stop()

    assert table["faq_location"].tool == "faq_location"
    assert table["handoff_medical_advice"].tool == "handoff_human"
    assert table["handoff_medical_advice"].params["reason"] == "medical_advice"


def test_a_row_without_dispatch_metadata_becomes_classify_but_do_not_act() -> None:
    """An absent dispatch already meant this; rows seeded before the column must not crash."""
    patcher = _with_rows(_rows(("greeting", None), ("farewell", {})))
    try:
        table = load_dispatch_table_from_db("postgresql://unused/unused")
    finally:
        patcher.stop()

    assert table["greeting"].tool is None
    assert table["greeting"].params == {}
    assert table["farewell"].tool is None


def test_reload_reports_what_changed() -> None:
    classifier = IntentClassifier(settings=_settings(), embeddings=MagicMock())

    patcher = _with_rows(_rows(("faq_location", {"dispatch": {"tool": "faq_location", "params": {}}})))
    try:
        added, removed, changed = classifier.reload_dispatch()
    finally:
        patcher.stop()
    assert (added, removed, changed) == (["faq_location"], [], [])

    patcher = _with_rows(
        _rows(
            ("faq_location", {"dispatch": {"tool": "kb_search", "params": {}}}),
            ("greeting", {"dispatch": {"tool": None, "params": {}}}),
        )
    )
    try:
        added, removed, changed = classifier.reload_dispatch()
    finally:
        patcher.stop()
    assert added == ["greeting"]
    assert removed == []
    assert changed == ["faq_location"]


def test_reload_replaces_the_table_rather_than_mutating_it() -> None:
    """
    classify_intent is a sync def, so FastAPI runs it in a threadpool. A
    concurrent lookup must see the whole old table or the whole new one — never
    a half-cleared dict.
    """
    classifier = IntentClassifier(settings=_settings(), embeddings=MagicMock())

    patcher = _with_rows(_rows(("faq_location", {"dispatch": {"tool": "faq_location", "params": {}}})))
    try:
        classifier.reload_dispatch()
    finally:
        patcher.stop()
    before = classifier.dispatch_table

    patcher = _with_rows(_rows(("greeting", {"dispatch": {"tool": None, "params": {}}})))
    try:
        classifier.reload_dispatch()
    finally:
        patcher.stop()

    assert classifier.dispatch_table is not before
    # The object a concurrent reader was holding is still intact and complete.
    assert "faq_location" in before


def test_the_reload_endpoint_requires_the_internal_api_key() -> None:
    from fastapi.testclient import TestClient

    from company_agent.rag_api import main as rag_main

    with TestClient(rag_main.app) as client:
        assert client.post("/v1/admin/reload_dispatch").status_code == 401
        assert client.post(
            "/v1/admin/reload_dispatch", headers={"X-Internal-API-Key": "wrong"}
        ).status_code == 401
