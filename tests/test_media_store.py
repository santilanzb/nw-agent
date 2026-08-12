"""
What happens to a payment proof.

The failure being closed: `waha.py` returned None for every image, so receipts
vanished. Stage 0 stopped that, but the FSM only acknowledged them — the asesora
picking up the conversation was handed the word "[image]" and had to go find the
receipt in WhatsApp herself.

What must hold now: the bytes land on disk, a row points at them so erasure can
find them, and the asesora gets a *reference* rather than the content.
"""
from __future__ import annotations

import asyncio
import random
import sys
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from _stack import SKIP_DB, db_available, db_url

from company_agent.agent_core.identity import IdentityBroker, canonicalize
from company_agent.agent_core.media import MediaStore
from company_agent.agent_core.transport.base import InboundMedia
from company_agent.common.db import make_async_pool

pytestmark = pytest.mark.skipif(not db_available(), reason=SKIP_DB)

_LOOP_FACTORY = asyncio.SelectorEventLoop if sys.platform == "win32" else None

RECEIPT = b"\x89PNG\r\n\x1a\n" + b"comprobante-de-pago" * 8


def run_with_pool[T](fn: Callable[[Any], Awaitable[T]]) -> T:
    async def main() -> T:
        pool = make_async_pool(db_url(), min_size=1, max_size=3)
        await pool.open(wait=True, timeout=10)
        try:
            return await fn(pool)
        finally:
            await pool.close()

    return asyncio.run(main(), loop_factory=_LOOP_FACTORY)


def _serving(payload: bytes = RECEIPT, status: int = 200):
    """A MediaStore whose fetch is answered in-process — no network."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=payload)

    return httpx.MockTransport(handler)


def _patched_store(pool, root, transport) -> MediaStore:
    store = MediaStore(pool, str(root), api_key="k")

    async def _fetch(url: str) -> bytes | None:
        async with httpx.AsyncClient(transport=transport) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content

    # Substituting the one call that leaves the process; everything else is real.
    store._fetch = _fetch
    return store


def _media(url: str | None = "http://waha/api/files/x.png") -> InboundMedia:
    return InboundMedia(
        kind="image", mime_type="image/png", url=url, caption="mi pago", provider_media_id="wamid.1"
    )


def _phone() -> str:
    return f"+58414{random.randint(1_000_000, 9_999_999)}"


def _rows(sql: str, params: tuple) -> list[tuple]:
    import psycopg

    with psycopg.connect(db_url()) as conn:
        return conn.execute(sql, params).fetchall()


def test_a_receipt_is_fetched_stored_and_recorded(tmp_path) -> None:
    phone = _phone()
    turn_id = uuid.uuid4()

    async def scenario(pool):
        identity = await IdentityBroker(pool).resolve(canonicalize(phone))
        store = _patched_store(pool, tmp_path, _serving())
        return identity, await store.store(
            _media(), identity_id=identity.id, turn_id=turn_id, source="waha"
        )

    _identity, stored = run_with_pool(scenario)

    assert stored.stored is True
    assert stored.id is not None

    rows = _rows(
        "select storage_path, byte_size, status, mime_type, kind from media_artifacts where id = %s",
        (stored.id,),
    )
    storage_path, byte_size, status, mime_type, kind = rows[0]
    assert status == "stored"
    assert byte_size == len(RECEIPT)
    assert mime_type == "image/png"
    assert kind == "image"

    # The bytes are on disk, not in Postgres.
    assert (tmp_path / storage_path).read_bytes() == RECEIPT


def test_the_asesora_gets_a_reference_not_the_content(tmp_path) -> None:
    """Graft 10: patient media never travels in a Note or the team group."""
    phone = _phone()

    async def scenario(pool):
        identity = await IdentityBroker(pool).resolve(canonicalize(phone))
        store = _patched_store(pool, tmp_path, _serving())
        return await store.store(
            _media(), identity_id=identity.id, turn_id=uuid.uuid4(), source="waha"
        )

    stored = run_with_pool(scenario)
    summary = stored.summary

    assert "image" in summary
    assert str(stored.id)[:8] in summary
    assert "comprobante" not in summary
    assert "http" not in summary


def test_a_failed_download_is_recorded_loudly_not_swallowed(tmp_path) -> None:
    """Silence is what this whole path exists to stop."""
    phone = _phone()

    async def scenario(pool):
        identity = await IdentityBroker(pool).resolve(canonicalize(phone))
        store = _patched_store(pool, tmp_path, _serving(status=404))
        return await store.store(
            _media(), identity_id=identity.id, turn_id=uuid.uuid4(), source="waha"
        )

    stored = run_with_pool(scenario)

    assert stored.stored is False
    assert "NO SE PUDO DESCARGAR" in stored.summary
    rows = _rows("select status, last_error from media_artifacts where id = %s", (stored.id,))
    assert rows[0][0] == "fetch_failed"
    assert rows[0][1]


def test_media_with_no_url_is_still_recorded(tmp_path) -> None:
    phone = _phone()

    async def scenario(pool):
        identity = await IdentityBroker(pool).resolve(canonicalize(phone))
        store = _patched_store(pool, tmp_path, _serving())
        return await store.store(
            _media(url=None), identity_id=identity.id, turn_id=uuid.uuid4(), source="waha"
        )

    stored = run_with_pool(scenario)
    assert stored.stored is False
    rows = _rows("select last_error from media_artifacts where id = %s", (stored.id,))
    assert "no media url" in rows[0][0]


def test_the_same_receipt_twice_is_one_artifact(tmp_path) -> None:
    phone = _phone()

    async def scenario(pool):
        identity = await IdentityBroker(pool).resolve(canonicalize(phone))
        store = _patched_store(pool, tmp_path, _serving())
        first = await store.store(
            _media(), identity_id=identity.id, turn_id=uuid.uuid4(), source="waha"
        )
        second = await store.store(
            _media(), identity_id=identity.id, turn_id=uuid.uuid4(), source="waha"
        )
        return identity, first, second

    _identity, first, second = run_with_pool(scenario)
    assert first.id == second.id

    rows = _rows(
        "select count(*) from media_artifacts where identity_id = %s", (_identity.id,)
    )
    assert rows[0][0] == 1


def test_erasing_an_identity_takes_its_media_rows(tmp_path) -> None:
    """
    The reason this is a table and not just a folder: Art. 17 enumerates stores
    keyed on identity_registry, and a directory nobody has a row for is the store
    an erasure drill finds too late.
    """
    phone = _phone()

    async def scenario(pool):
        identity = await IdentityBroker(pool).resolve(canonicalize(phone))
        store = _patched_store(pool, tmp_path, _serving())
        await store.store(_media(), identity_id=identity.id, turn_id=uuid.uuid4(), source="waha")
        async with pool.connection() as conn:
            await conn.execute("DELETE FROM identity_registry WHERE id = %s", (identity.id,))
        return identity.id

    identity_id = run_with_pool(scenario)
    rows = _rows("select count(*) from media_artifacts where identity_id = %s", (identity_id,))
    assert rows[0][0] == 0
