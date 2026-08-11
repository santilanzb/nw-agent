"""
Availability probes for the local stack.

Kept out of conftest.py because pytest imports conftest specially — test modules
import this one normally. Every value is read from the environment at call time,
after conftest.py has set it.
"""
from __future__ import annotations

import os


def db_url() -> str:
    return os.environ["DATABASE_URL"]


def db_available() -> bool:
    """True when Postgres is up and carries the Stage 0 schema."""
    try:
        import psycopg

        with psycopg.connect(db_url(), connect_timeout=3) as conn:
            conn.execute("select 1 from intake_events limit 1")
        return True
    except Exception:  # noqa: BLE001 - any failure means "skip"
        return False


def service_available(url: str) -> bool:
    try:
        import httpx

        return httpx.get(f"{url}/health", timeout=3).status_code == 200
    except Exception:  # noqa: BLE001
        return False


def stack_available() -> bool:
    """Postgres + rag-api + crm-adapter, i.e. everything an FSM turn touches."""
    return (
        db_available()
        and service_available(os.environ["RAG_API_URL"])
        and service_available(os.environ["CRM_ADAPTER_URL"])
    )


SKIP_DB = "no Postgres with the Stage 0 schema; see tests/conftest.py"
SKIP_STACK = (
    "local stack not running: docker compose -f docker-compose.yml "
    "-f docker-compose.local.yml up -d postgres rag-api crm-adapter"
)
