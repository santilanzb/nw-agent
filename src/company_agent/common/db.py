from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


@contextmanager
def connect(database_url: str) -> Iterator[psycopg.Connection]:
    """Synchronous one-shot connection. Used by the one-shot CLIs and rag-api."""
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        yield connection


def make_async_pool(
    database_url: str, *, min_size: int = 1, max_size: int = 10
) -> AsyncConnectionPool:
    """
    Pool for agent-core's hot paths.

    The inbox runs on every inbound message and the sweeper polls continuously;
    opening a fresh connection per statement would pay TCP setup and auth on the
    latency budget of a patient's reply. Returned unopened — call `await
    pool.open()` from the app's lifespan and `await pool.close()` on shutdown.
    """
    return AsyncConnectionPool(
        conninfo=database_url,
        min_size=min_size,
        max_size=max_size,
        open=False,
        kwargs={"row_factory": dict_row},
    )


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in values) + "]"

