"""
The import boundary that keeps package discovery cheap and safe.

rag-api and the intent seeder both read package manifests and seeds. Neither may
end up importing the Anthropic client, which `agent_core/llm/anthropic.py` pulls
in at module scope — that would put a customer-facing API's cold start behind an
SDK it never calls, and it would drag agent-core's settings into two services
that have their own.

Each check runs in a **subprocess**. In-process assertions on `sys.modules` are
non-deterministic here: another test module may already have imported anthropic,
and the assertion would pass or fail depending on collection order.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"

# Probe template. Prints the forbidden modules that ended up loaded.
PROBE = """
import sys
sys.path.insert(0, {src!r})
{body}
forbidden = {forbidden!r}
loaded = sorted(
    m for m in sys.modules
    if m.split(".")[0] in forbidden or m.startswith("company_agent.agent_core")
)
print(";".join(loaded))
"""


def _loaded_forbidden(body: str, forbidden: set[str]) -> list[str]:
    script = PROBE.format(src=str(SRC), body=body, forbidden=sorted(forbidden))
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"probe failed:\n{result.stderr}"
    out = result.stdout.strip()
    return out.split(";") if out else []


def test_discovering_packages_does_not_import_a_task_module() -> None:
    leaked = _loaded_forbidden(
        body=(
            "from company_agent.packages.registry import discover_manifests, merge_seeds\n"
            "merge_seeds(discover_manifests())\n"
        ),
        forbidden={"anthropic", "langfuse", "fastapi"},
    )
    assert leaked == [], (
        "package discovery must stay pure — these were imported: "
        f"{leaked}. Only packages/registrar.py may import a task module."
    )


def test_the_intent_seeder_does_not_import_the_anthropic_client() -> None:
    """openai is legitimate here (embeddings); anthropic and agent-core are not."""
    leaked = _loaded_forbidden(
        body="import company_agent.intent_seeder.main\n",
        forbidden={"anthropic", "langfuse", "fastapi"},
    )
    assert leaked == [], f"the seeder pulled in: {leaked}"


def test_the_packages_anchor_imports_nothing() -> None:
    """
    `packages/__init__.py` is the anchor of the boundary: importing it must not
    execute any of the packages it contains.
    """
    leaked = _loaded_forbidden(
        body="import company_agent.packages\n",
        forbidden={"anthropic", "langfuse", "fastapi", "yaml", "pydantic"},
    )
    assert leaked == [], f"importing the anchor pulled in: {leaked}"


@pytest.mark.parametrize(
    "module",
    ["company_agent.packages.registry", "company_agent.packages.manifest"],
)
def test_registry_modules_are_importable_without_the_src_tree_on_sys_path(module: str) -> None:
    """Guards the installed-in-a-container case, where only site-packages exists."""
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=SRC,
    )
    assert result.returncode == 0, result.stderr
