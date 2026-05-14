from __future__ import annotations

import argparse
from pathlib import Path

import yaml
from psycopg.types.json import Jsonb

from company_agent.common.db import connect, vector_literal
from company_agent.common.embeddings import EmbeddingClient, EmbeddingConfig
from company_agent.common.logging import configure_logging

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


def load_seeds(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["intents"]


def sync_seeds(settings: IntentSeederSettings, *, reset: bool = False) -> None:
    logger = configure_logging("intent-seeder")
    embedding_client = EmbeddingClient(
        EmbeddingConfig(
            provider=settings.embedding_provider,
            api_key=settings.openai_api_key,
            model=settings.openai_embedding_model,
        )
    )

    seeds_path = Path(settings.intent_seeds_path)
    if not seeds_path.exists():
        raise FileNotFoundError(f"Seeds file not found: {seeds_path}")

    intents = load_seeds(seeds_path)
    total_rows = 0

    with connect(settings.database_url) as conn:
        if reset:
            conn.execute(DELETE_ALL_SQL)
            logger.info("reset: deleted all existing intent_vectors rows")

        for intent_class, intent_data in intents.items():
            examples: list[str] = intent_data.get("examples", [])
            dispatch: dict = intent_data.get("dispatch", {})
            language = "es"  # all seeds go into the 'es' bucket — the agent
            # can't pre-know the patient's language at classify time

            if reset:
                pass  # already cleared above
            else:
                conn.execute(DELETE_CLASS_SQL, {"intent_class": intent_class})

            for example_text in examples:
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
                len(examples),
                embedding_client.enabled,
            )

    logger.info("seeding completed total_rows=%s", total_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Intent vector seeder")
    parser.add_argument("command", choices=["sync"], help="Command to run")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete all rows before seeding (full re-seed)",
    )
    args = parser.parse_args()

    settings = IntentSeederSettings()

    if args.command == "sync":
        sync_seeds(settings, reset=args.reset)


if __name__ == "__main__":
    main()
