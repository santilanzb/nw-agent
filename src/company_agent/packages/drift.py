"""
Does what is installed agree with what is claimed, and with what is seeded?

Three sets that must line up, and today nothing compares them. A seeded intent
that no task claims is discovered one patient turn at a time, by
`TaskRegistry.resolve` logging loudly and escalating that patient to a human.

**Only agent-core can run this.** rag-api knows the database and the dispatch
table but must never import the task registry — that would drag the Anthropic
client into a service that never calls it. agent-core already imports task
modules, and `discover_manifests()` is import-pure, so it is the one process that
can see all three sides.

This module is pure: it takes three sets and returns a report. The I/O lives in
the caller.
"""
from __future__ import annotations

from dataclasses import dataclass, field


class PackageDrift(RuntimeError):
    """Installed packages and the tasks registered from them disagree."""


@dataclass(frozen=True, slots=True)
class DriftReport:
    # Seeded or declared by a manifest, but no task claims it. A patient
    # classifying here reaches the fallback handler and a human.
    unclaimed: frozenset[str] = frozenset()
    # Claimed by a task, but in no manifest. The task believes it owns traffic
    # that can never be routed to it.
    unseeded: frozenset[str] = frozenset()
    # In the database but not in any installed manifest. Stale rows still match
    # the nearest-neighbour query, which has no class filter.
    orphaned_in_db: frozenset[str] = frozenset()
    # In a manifest but never seeded into the database. Classification for these
    # is impossible until the seeder runs.
    missing_from_db: frozenset[str] = frozenset()
    checked: frozenset[str] = field(default=frozenset())

    @property
    def fatal(self) -> frozenset[str]:
        """
        Disagreements that a deploy cannot legitimately produce.

        Manifests and tasks ship in the same build from the same repo, so if they
        disagree the build is wrong — there is no environment in which that is
        expected, and starting anyway serves patients from a configuration nobody
        intended.
        """
        return self.unclaimed | self.unseeded

    @property
    def database_drift(self) -> frozenset[str]:
        """
        Operational state a human fixes by re-running the seeder.

        Loud, never fatal: refusing to boot because someone forgot to re-seed
        converts a degraded classifier into a total outage.
        """
        return self.orphaned_in_db | self.missing_from_db

    def as_dict(self) -> dict[str, list[str]]:
        return {
            "unclaimed": sorted(self.unclaimed),
            "unseeded": sorted(self.unseeded),
            "orphaned_in_db": sorted(self.orphaned_in_db),
            "missing_from_db": sorted(self.missing_from_db),
        }


def check_drift(
    *,
    manifest_intents: set[str],
    claimed_intents: set[str],
    seeded_intents: set[str] | None = None,
    db_intents: set[str] | None = None,
) -> DriftReport:
    """
    Compare what packages declare, what tasks claim, and what is in the database.

    `manifest_intents` is everything a package declares — its seeds **plus** its
    synthetic intents. `seeded_intents` is only the ones with example phrases,
    and it is the right set to compare against the database: a synthetic intent
    like `unknown` is emitted by the runtime, never classified, so it must never
    appear in `intent_vectors` and its absence is not drift. Comparing the
    declared set against the database would report `unknown` as missing forever,
    and a check that always fires is a check nobody reads.

    `db_intents=None` skips the database comparison — honest about the difference
    between "agrees" and "not checked".
    """
    expected_in_db = manifest_intents if seeded_intents is None else seeded_intents
    return DriftReport(
        unclaimed=frozenset(manifest_intents - claimed_intents),
        unseeded=frozenset(claimed_intents - manifest_intents),
        orphaned_in_db=frozenset() if db_intents is None else frozenset(db_intents - expected_in_db),
        missing_from_db=frozenset() if db_intents is None else frozenset(expected_in_db - db_intents),
        checked=frozenset(manifest_intents | claimed_intents | (db_intents or set())),
    )
