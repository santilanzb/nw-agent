"""
Installing function packages into a live TaskRegistry.

**This is the only module permitted to import a task module.** Everything else
that touches packages — rag-api's dispatch table, the intent seeder, the drift
check — goes through `packages.registry`, which reads YAML and never imports
anything from a package directory. Importing `task.py` pulls in the Anthropic
client transitively, and rag-api and the seeder must not pay for that.

Only agent-core calls `install_packages`. `tests/test_package_boundary.py`
enforces the rest of the boundary in a subprocess.
"""
from __future__ import annotations

import importlib
import logging
from typing import Any, Protocol

from .registry import LoadedPackage, MalformedPackage, discover_manifests

logger = logging.getLogger(__name__)


class SupportsRegister(Protocol):
    """The slice of TaskRegistry this module needs. Keeps agent_core out of the imports."""

    def register(self, task: Any) -> None: ...


def _resolve(reference: str) -> type:
    """
    Turn "module.path:ClassName" into the class.

    The manifest validated this string's *shape* at discovery; this is where it
    becomes an import, and where a package that names something that does not
    exist fails — before any turn is served.
    """
    module_path, _, attribute = reference.partition(":")
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise MalformedPackage(f"task module {module_path!r} could not be imported: {exc}") from exc
    try:
        return getattr(module, attribute)
    except AttributeError as exc:
        raise MalformedPackage(f"{module_path!r} has no attribute {attribute!r}") from exc


def build_task(package: LoadedPackage, **dependencies: Any) -> Any:
    """
    Construct one package's task with its derived `handled_intents`.

    The intents are computed from the package's own seeds plus its declared
    synthetic intents — never restated by the task class, which is what used to
    drift.
    """
    task_class = _resolve(package.manifest.task)
    task = task_class(handled_intents=package.handled_intents, **dependencies)

    declared = package.manifest.task_name
    actual = getattr(task, "name", None)
    if actual != declared:
        # turn_log.task is written from `.name`, so a mismatch silently
        # mislabels every row this package produces.
        raise MalformedPackage(
            f"package {package.name!r} declares task_name={declared!r} "
            f"but the class reports name={actual!r}"
        )
    return task


def install_packages(registry: SupportsRegister, **dependencies: Any) -> list[LoadedPackage]:
    """
    Discover, construct and register every installed package.

    Intent collisions are caught by the registry's own explicit-claim check, so
    two packages claiming the same intent is a startup error rather than a
    first-match-wins surprise at runtime.
    """
    packages = discover_manifests()
    for package in packages:
        registry.register(build_task(package, **dependencies))
        logger.info(
            "installed package=%s version=%s intents=%d",
            package.name,
            package.manifest.version,
            len(package.handled_intents),
        )
    return packages
