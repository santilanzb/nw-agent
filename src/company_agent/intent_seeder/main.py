from __future__ import annotations

import argparse

from psycopg.types.json import Jsonb

from company_agent.common.db import connect, vector_literal
from company_agent.common.embeddings import EmbeddingClient, EmbeddingConfig
from company_agent.common.logging import configure_logging
from company_agent.packages.registry import discover_manifests, merge_seeds

from .config import IntentSeederSettings

UPSERT_SQL = """
INSERT INTO intent_vectors (intent_class, example_text, language, embedding, metadata)
VALUES (%(intent_class)s, %(example_text)s, %(language)s, %(embedding)s::vector, %(metadata)s)
ON CONFLICT (intent_class, example_text, language) DO UPDATE SET
  embedding = EXCLUDED.embedding,
  metadata  = EXCLUDED.metadata
"""

DELETE_CLASS_SQL = "DELETE FROM intent_vectors WHERE intent_class = %(intent_class)s"
DELETE_ALL_SQL = "DELETE FROM intent_vectors"
EXISTING_CLASSES_SQL = "SELECT DISTINCT intent_class FROM intent_vectors"
PRUNE_SQL = "DELETE FROM intent_vectors WHERE intent_class <> ALL(%(desired)s)"


class RefusedToPrune(RuntimeError):
    """A prune that looked like a build failure rather than an intentional removal."""


def _prune_orphans(conn, desired: set[str], *, logger, force: bool) -> None:
    """
    Remove intent classes no installed package claims.

    Orphans are not inert. The classifier's nearest-neighbour query has no class
    filter, so a removed package's vectors still match — a patient's message
    classifies to an intent nobody owns, and the turn escalates to a human on the
    strength of stale seed data.

    Two guards, both about the same failure: package discovery returning less
    than it should. If package-data is misconfigured, `discover_manifests()`
    finds nothing, and an unguarded prune turns a bad build into a dead
    classifier.
    """
    existing = {row["intent_class"] for row in conn.execute(EXISTING_CLASSES_SQL).fetchall()}
    orphans = existing - desired
    if not orphans:
        return

    if not force and len(orphans) > len(existing) / 2:
        raise RefusedToPrune(
            f"pruning would remove {len(orphans)} of {len(existing)} intent classes "
            f"({sorted(orphans)}). That looks like a discovery failure, not a removal. "
            "Re-run with --force if it is deliberate."
        )

    conn.execute(PRUNE_SQL, {"desired": sorted(desired)})
    logger.warning("pruned orphaned intent classes: %s", sorted(orphans))


def sync_seeds(
    settings: IntentSeederSettings,
    *,
    reset: bool = False,
    prune: bool = True,
    force: bool = False,
) -> None:
    logger = configure_logging("intent-seeder")
    embedding_client = EmbeddingClient(
        EmbeddingConfig(
            provider=settings.embedding_provider,
            api_key=settings.openai_api_key,
            model=settings.openai_embedding_model,
        )
    )

    packages = discover_manifests()
    intents = merge_seeds(packages)
    if not intents:
        # Never reachable through a healthy build, which is exactly why it is
        # checked: an empty merge means discovery failed, and everything after
        # this point would delete rows on the strength of that emptiness.
        raise RefusedToPrune(
            "no function packages discovered — refusing to touch intent_vectors. "
            "Check that package data (manifest.yaml, seeds.yaml) survived installation."
        )

    logger.info(
        "discovered packages=%s intents=%s",
        [p.name for p in packages],
        len(intents),
    )

    total_rows = 0
    with connect(settings.database_url) as conn:
        if reset:
            conn.execute(DELETE_ALL_SQL)
            logger.info("reset: deleted all existing intent_vectors rows")
        elif prune:
            _prune_orphans(conn, set(intents), logger=logger, force=force)

        for intent_class, intent in intents.items():
            language = "es"  # all seeds go into the 'es' bucket — the agent
            # can't pre-know the patient's language at classify time

            if not reset:
                conn.execute(DELETE_CLASS_SQL, {"intent_class": intent_class})

            dispatch = intent.dispatch.model_dump()
            for example_text in intent.examples:
                embedding = embedding_client.embed(example_text)
                conn.execute(
                    UPSERT_SQL,
                    {
                        "intent_class": intent_class,
                        "example_text": example_text,
                        "language": language,
                        "embedding": vector_literal(embedding) if embedding else None,
                        "metadata": Jsonb({"dispatch": dispatch}),
                    },
                )
                total_rows += 1

            logger.info(
                "seeded intent_class=%s examples=%s embedded=%s",
                intent_class,
                len(intent.examples),
                embedding_client.enabled,
            )

    logger.info("seeding completed total_rows=%s", total_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Intent vector seeder")
    parser.add_argument("command", choices=["sync"], help="Command to run")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete all rows before seeding (full re-seed, re-embeds everything)",
    )
    parser.add_argument(
        "--no-prune",
        action="store_true",
        help="Keep intent classes that no installed package claims",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow a prune that removes more than half of the existing intent classes",
    )
    args = parser.parse_args()

    settings = IntentSeederSettings()

    if args.command == "sync":
        sync_seeds(
            settings,
            reset=args.reset,
            prune=not args.no_prune,
            force=args.force,
        )


if __name__ == "__main__":
    main()
