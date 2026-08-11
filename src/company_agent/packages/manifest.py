"""
The function-package manifest and seed-fragment schemas.

Everything here is a Pydantic model with `extra="forbid"`, which is the single
most load-bearing line in the file. A typo'd key in a YAML config is a silent
no-op almost everywhere else in this repo — `_load_dispatch_table` returned an
empty table for a missing file and said nothing. Here a misspelled key fails
loudly, naming the offending key, before a request is served.

Imports pydantic and nothing else. See `packages/__init__.py` for why.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# An intent class keys the task registry and lands in `turn_log.classified_intent`.
INTENT_CLASS = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
# "package.module:AttrName" — validated as a shape only. Resolving it is an
# import, and discover_manifests() must never import a task module.
TASK_REF = re.compile(r"^[a-zA-Z_][\w.]*:[A-Za-z_]\w*$")


class SeedDispatch(BaseModel):
    """What to do when an intent fires. `tool: null` means "converse, don't act"."""

    model_config = ConfigDict(extra="forbid")

    tool: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class SeedIntent(BaseModel):
    """One intent class: what it means, what it dispatches to, how it sounds."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1)
    dispatch: SeedDispatch
    # An intent with no examples can never be classified, so it is an intent
    # that exists in the registry and can never fire. The old seeder read
    # `.get("examples", [])` and seeded it as zero rows, silently.
    examples: list[str] = Field(min_length=1)


class WriteAction(BaseModel):
    """A CRM write this package may perform, and how much autonomy it gets."""

    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1)
    autonomy: Literal["shadow", "auto_with_audit", "ask_first"]


class CostBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monthly_usd: float = Field(gt=0)
    per_turn_usd: float = Field(gt=0)


class PackageManifest(BaseModel):
    """
    A package's identity and contract.

    `write_actions` and `cost_budget` are declared but nothing reads them yet —
    there is no CrmWriteGate and no budget governor. They are here anyway
    because `extra="forbid"` makes adding a field later a breaking change for
    every package, and there is exactly one package today. This is the cheapest
    moment in the project's life to get the schema right.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{2,39}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    description: str = Field(min_length=1, max_length=200)

    # "company_agent.packages.customer_service.task:CustomerServiceTask"
    task: str
    # Must equal the task class's `.name`. It is written to `turn_log.task`, so
    # a change here silently re-labels history.
    task_name: str = Field(pattern=r"^[a-z][a-z0-9_]{2,39}$")

    seeds: str = "seeds.yaml"
    evals: str | None = "evals"

    # Intent classes this package claims that are NOT seeded — synthesised at
    # runtime rather than classified. `unknown` is the real case: the FSM emits
    # it when the classifier call fails, and rag-api when embeddings are off.
    # Declaring it is what makes "exactly one owner" enforceable.
    synthetic_intents: frozenset[str] = frozenset()

    write_actions: list[WriteAction] = Field(default_factory=list)
    cost_budget: CostBudget

    @field_validator("task")
    @classmethod
    def _task_is_a_reference_not_an_import(cls, value: str) -> str:
        if not TASK_REF.match(value):
            raise ValueError(
                f"task must look like 'module.path:ClassName', got {value!r}"
            )
        return value

    @field_validator("synthetic_intents")
    @classmethod
    def _synthetic_intents_are_well_formed(cls, value: frozenset[str]) -> frozenset[str]:
        bad = sorted(i for i in value if not INTENT_CLASS.match(i))
        if bad:
            raise ValueError(f"malformed intent class names: {bad}")
        return value
