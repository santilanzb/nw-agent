"""
The package contract, rule by rule.

Verdict graft 7 requires that malformed packages fail at load rather than
degrading. The failure mode being designed out is the one the old loader had:
`_load_dispatch_table` returned `{}` for a missing seeds file and logged
nothing, so a mis-pathed config looked exactly like a working one.

`discover_manifests()` takes a Traversable, and `pathlib.Path` satisfies it, so
every case here builds a real package tree in tmp_path.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from company_agent.packages.registry import (
    MalformedPackage,
    SeedCollision,
    discover_manifests,
    merge_seeds,
)

VALID_MANIFEST = {
    "name": "customer_service",
    "version": "1.0.0",
    "description": "Patient-facing customer service.",
    "task": "company_agent.packages.customer_service.task:CustomerServiceTask",
    "task_name": "customer_service",
    "seeds": "seeds.yaml",
    "evals": "evals",
    "synthetic_intents": ["unknown"],
    "write_actions": [{"action": "create_note", "autonomy": "shadow"}],
    "cost_budget": {"monthly_usd": 50.0, "per_turn_usd": 0.02},
}

VALID_SEEDS = {
    "intents": {
        "faq_location": {
            "description": "Patient asks where NutriWhite is located",
            "dispatch": {"tool": "faq_location", "params": {}},
            "examples": ["donde estan ubicados", "cual es la direccion"],
        },
        "greeting": {
            "description": "Patient greets",
            "dispatch": {"tool": None, "params": {}},
            "examples": ["hola", "buenos dias"],
        },
    }
}


def _write_package(
    root: Path,
    *,
    name: str = "customer_service",
    manifest: dict | None = None,
    seeds: dict | str | None = None,
    with_evals: bool = True,
) -> Path:
    directory = root / name
    directory.mkdir(parents=True)

    payload = copy.deepcopy(VALID_MANIFEST) if manifest is None else manifest
    (directory / "manifest.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")

    if seeds != "__omit__":
        body = copy.deepcopy(VALID_SEEDS) if seeds is None else seeds
        text = body if isinstance(body, str) else yaml.safe_dump(body)
        (directory / "seeds.yaml").write_text(text, encoding="utf-8")

    if with_evals:
        (directory / "evals").mkdir()
        (directory / "evals" / "cases.yaml").write_text("cases: []\n", encoding="utf-8")
    return directory


def test_a_valid_package_loads(tmp_path: Path) -> None:
    _write_package(tmp_path)
    (package,) = discover_manifests(tmp_path)
    assert package.name == "customer_service"
    assert package.manifest.version == "1.0.0"
    assert set(package.intents) == {"faq_location", "greeting"}


def test_handled_intents_are_derived_from_the_seeds_not_declared(tmp_path: Path) -> None:
    """The drift this whole contract exists to remove."""
    _write_package(tmp_path)
    (package,) = discover_manifests(tmp_path)
    assert package.handled_intents == {"faq_location", "greeting", "unknown"}


def test_an_empty_packages_dir_discovers_nothing(tmp_path: Path) -> None:
    assert discover_manifests(tmp_path) == []


def test_dunder_and_underscore_directories_are_skipped(tmp_path: Path) -> None:
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "_scratch").mkdir()
    _write_package(tmp_path)
    assert len(discover_manifests(tmp_path)) == 1


def test_a_directory_without_a_manifest_is_an_error_not_a_skip(tmp_path: Path) -> None:
    (tmp_path / "halfbuilt").mkdir()
    with pytest.raises(MalformedPackage, match=r"no manifest\.yaml"):
        discover_manifests(tmp_path)


def test_an_unknown_manifest_key_is_rejected(tmp_path: Path) -> None:
    manifest = copy.deepcopy(VALID_MANIFEST)
    manifest["write_action"] = []  # singular: the typo this guards against
    _write_package(tmp_path, manifest=manifest)
    with pytest.raises(MalformedPackage, match="write_action"):
        discover_manifests(tmp_path)


def test_the_manifest_name_must_match_the_directory(tmp_path: Path) -> None:
    manifest = copy.deepcopy(VALID_MANIFEST)
    manifest["name"] = "something_else"
    _write_package(tmp_path, manifest=manifest)
    with pytest.raises(MalformedPackage, match="must match the directory"):
        discover_manifests(tmp_path)


def test_a_task_reference_must_not_be_an_arbitrary_string(tmp_path: Path) -> None:
    manifest = copy.deepcopy(VALID_MANIFEST)
    manifest["task"] = "company_agent.packages.customer_service.task"  # no ':Class'
    _write_package(tmp_path, manifest=manifest)
    with pytest.raises(MalformedPackage, match=r"module\.path:ClassName"):
        discover_manifests(tmp_path)


def test_a_missing_cost_budget_is_rejected(tmp_path: Path) -> None:
    """A default budget is a budget nobody chose."""
    manifest = copy.deepcopy(VALID_MANIFEST)
    del manifest["cost_budget"]
    _write_package(tmp_path, manifest=manifest)
    with pytest.raises(MalformedPackage, match="cost_budget"):
        discover_manifests(tmp_path)


def test_a_missing_seeds_file_is_an_error_not_an_empty_table(tmp_path: Path) -> None:
    """The exact regression: the old loader returned {} and said nothing."""
    _write_package(tmp_path, seeds="__omit__")
    with pytest.raises(MalformedPackage, match="file not found"):
        discover_manifests(tmp_path)


def test_seeds_without_an_intents_mapping_are_rejected(tmp_path: Path) -> None:
    _write_package(tmp_path, seeds={"intenst": {}})
    with pytest.raises(MalformedPackage, match="non-empty top-level 'intents'"):
        discover_manifests(tmp_path)


def test_an_intent_with_no_examples_is_rejected(tmp_path: Path) -> None:
    """It would exist in the registry and never be classifiable."""
    seeds = copy.deepcopy(VALID_SEEDS)
    seeds["intents"]["faq_location"]["examples"] = []
    _write_package(tmp_path, seeds=seeds)
    with pytest.raises(MalformedPackage, match="faq_location"):
        discover_manifests(tmp_path)


def test_an_intent_without_dispatch_is_rejected(tmp_path: Path) -> None:
    seeds = copy.deepcopy(VALID_SEEDS)
    del seeds["intents"]["faq_location"]["dispatch"]
    _write_package(tmp_path, seeds=seeds)
    with pytest.raises(MalformedPackage, match="dispatch"):
        discover_manifests(tmp_path)


def test_a_null_dispatch_tool_is_allowed(tmp_path: Path) -> None:
    """Conversational intents converse; they do not act."""
    _write_package(tmp_path)
    (package,) = discover_manifests(tmp_path)
    assert package.intents["greeting"].dispatch.tool is None


def test_a_malformed_intent_class_name_is_rejected(tmp_path: Path) -> None:
    seeds = copy.deepcopy(VALID_SEEDS)
    seeds["intents"]["FAQ Location"] = seeds["intents"].pop("faq_location")
    _write_package(tmp_path, seeds=seeds)
    with pytest.raises(MalformedPackage, match="malformed intent class"):
        discover_manifests(tmp_path)


def test_an_intent_cannot_be_both_seeded_and_synthetic(tmp_path: Path) -> None:
    manifest = copy.deepcopy(VALID_MANIFEST)
    manifest["synthetic_intents"] = ["greeting"]
    _write_package(tmp_path, manifest=manifest)
    with pytest.raises(MalformedPackage, match="one or the other"):
        discover_manifests(tmp_path)


def test_a_declared_but_empty_evals_dir_is_rejected(tmp_path: Path) -> None:
    """An eval-less package is what graft 7 exists to prevent."""
    _write_package(tmp_path, with_evals=False)
    with pytest.raises(MalformedPackage, match="evals"):
        discover_manifests(tmp_path)


def test_two_packages_cannot_seed_the_same_intent(tmp_path: Path) -> None:
    _write_package(tmp_path)
    other = copy.deepcopy(VALID_MANIFEST)
    other.update(name="second_package", task_name="second_package", synthetic_intents=[])
    _write_package(tmp_path, name="second_package", manifest=other)
    with pytest.raises(SeedCollision, match="faq_location"):
        merge_seeds(discover_manifests(tmp_path))


def test_two_packages_cannot_share_a_task_name(tmp_path: Path) -> None:
    """turn_log.task would stop identifying which module answered."""
    _write_package(tmp_path)
    other = copy.deepcopy(VALID_MANIFEST)
    other.update(name="second_package", synthetic_intents=[])
    seeds = {"intents": {"faq_other": copy.deepcopy(VALID_SEEDS["intents"]["faq_location"])}}
    _write_package(tmp_path, name="second_package", manifest=other, seeds=seeds)
    with pytest.raises(SeedCollision, match="task_name"):
        merge_seeds(discover_manifests(tmp_path))
