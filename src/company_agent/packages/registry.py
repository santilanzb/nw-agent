"""
Discovery and seed merging for function packages.

Reads manifests and seed fragments off disk and validates them. Deliberately
**pure**: it imports pydantic, yaml and importlib.resources, and never imports a
task module. rag-api and the intent seeder both call `discover_manifests()`, and
neither may end up importing the Anthropic client. `packages.registrar` is the
only module allowed to resolve `manifest.task` into a class.

"Malformed packages fail at import" cannot literally mean Python import time for
a YAML manifest. What it means operationally: `discover_manifests()` is the first
call in every process's startup path, so a malformed package raises before any
request is served or any row is written.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable

import yaml
from pydantic import ValidationError

from .manifest import INTENT_CLASS, PackageManifest, SeedIntent

PACKAGES_ANCHOR = "company_agent.packages"
MANIFEST_FILENAME = "manifest.yaml"


class MalformedPackage(RuntimeError):
    """A package directory does not satisfy the contract."""


class SeedCollision(RuntimeError):
    """Two packages claim the same intent class or task name."""


@dataclass(frozen=True, slots=True)
class LoadedPackage:
    manifest: PackageManifest
    intents: dict[str, SeedIntent]

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def handled_intents(self) -> frozenset[str]:
        """
        Derived, never declared.

        The monolith hand-maintained a frozenset of 22 intent names whose only
        job was to equal the keys of a YAML file in another directory, with
        nothing asserting they matched. Deriving it removes the drift class
        rather than detecting it.
        """
        return frozenset(self.intents) | self.manifest.synthetic_intents


def _read_yaml(where: Traversable, label: str) -> dict:
    try:
        raw = yaml.safe_load(where.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise MalformedPackage(f"{label}: not valid YAML: {exc}") from exc
    if raw is None:
        raise MalformedPackage(f"{label}: file is empty")
    if not isinstance(raw, dict):
        raise MalformedPackage(f"{label}: expected a mapping, got {type(raw).__name__}")
    return raw


def _load_seed_fragment(directory: Traversable, manifest: PackageManifest) -> dict[str, SeedIntent]:
    label = f"package {manifest.name!r} seeds ({manifest.seeds})"
    seeds_file = directory / manifest.seeds
    if not seeds_file.is_file():
        raise MalformedPackage(f"{label}: file not found")

    raw = _read_yaml(seeds_file, label)
    intents = raw.get("intents")
    if not isinstance(intents, dict) or not intents:
        raise MalformedPackage(f"{label}: expected a non-empty top-level 'intents' mapping")

    parsed: dict[str, SeedIntent] = {}
    for intent_class, data in intents.items():
        if not INTENT_CLASS.match(str(intent_class)):
            raise MalformedPackage(f"{label}: malformed intent class {intent_class!r}")
        try:
            parsed[intent_class] = SeedIntent.model_validate(data)
        except ValidationError as exc:
            raise MalformedPackage(f"{label}: intent {intent_class!r}: {exc}") from exc

    overlap = sorted(set(parsed) & manifest.synthetic_intents)
    if overlap:
        raise MalformedPackage(
            f"package {manifest.name!r}: {overlap} are declared as synthetic_intents "
            "and also seeded — an intent is one or the other"
        )
    return parsed


def _load_one(directory: Traversable) -> LoadedPackage:
    label = f"package directory {directory.name!r}"
    manifest_file = directory / MANIFEST_FILENAME
    if not manifest_file.is_file():
        # Skipping silently is how a package quietly stops being installed.
        raise MalformedPackage(f"{label}: no {MANIFEST_FILENAME}")

    raw = _read_yaml(manifest_file, f"{label} {MANIFEST_FILENAME}")
    try:
        manifest = PackageManifest.model_validate(raw)
    except ValidationError as exc:
        raise MalformedPackage(f"{label}: invalid {MANIFEST_FILENAME}: {exc}") from exc

    if manifest.name != directory.name:
        raise MalformedPackage(
            f"{label}: manifest name is {manifest.name!r}; it must match the directory"
        )

    if manifest.evals is not None:
        evals_dir = directory / manifest.evals
        if not evals_dir.is_dir():
            raise MalformedPackage(f"package {manifest.name!r}: evals dir {manifest.evals!r} not found")
        if not any(child.is_file() for child in evals_dir.iterdir()):
            raise MalformedPackage(f"package {manifest.name!r}: evals dir {manifest.evals!r} is empty")

    return LoadedPackage(manifest=manifest, intents=_load_seed_fragment(directory, manifest))


def _candidate_directories(anchor: Traversable) -> list[Traversable]:
    return sorted(
        (
            child
            for child in anchor.iterdir()
            if child.is_dir()
            and not child.name.startswith(("_", "."))
            and child.name != "__pycache__"
        ),
        key=lambda child: child.name,
    )


def discover_manifests(anchor: Traversable | None = None) -> list[LoadedPackage]:
    """
    Every installed package, validated. Raises `MalformedPackage` on the first
    directory that does not satisfy the contract.
    """
    root = anchor if anchor is not None else files(PACKAGES_ANCHOR)
    return [_load_one(directory) for directory in _candidate_directories(root)]


def merge_seeds(packages: list[LoadedPackage]) -> dict[str, SeedIntent]:
    """
    One intent table from N packages. Two packages claiming the same intent
    class is the seed-level twin of `TaskRegistry`'s RegistryCollision, and it
    fires earlier — before anything is written to `intent_vectors`.
    """
    merged: dict[str, SeedIntent] = {}
    owner: dict[str, str] = {}
    task_names: dict[str, str] = {}

    for package in packages:
        previous = task_names.get(package.manifest.task_name)
        if previous is not None:
            raise SeedCollision(
                f"task_name {package.manifest.task_name!r} claimed by both "
                f"{previous!r} and {package.name!r} — turn_log.task would be ambiguous"
            )
        task_names[package.manifest.task_name] = package.name

        for intent_class, intent in package.intents.items():
            if intent_class in merged:
                raise SeedCollision(
                    f"intent {intent_class!r} seeded by both "
                    f"{owner[intent_class]!r} and {package.name!r}"
                )
            merged[intent_class] = intent
            owner[intent_class] = package.name

    return merged


def dispatch_table(packages: list[LoadedPackage]) -> dict[str, dict]:
    """The `{intent: {tool, params}}` view, for the seeder and for rag-api."""
    return {
        intent_class: intent.dispatch.model_dump()
        for intent_class, intent in merge_seeds(packages).items()
    }
