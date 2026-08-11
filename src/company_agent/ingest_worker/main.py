from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from psycopg.types.json import Jsonb

from company_agent.common.db import connect, vector_literal
from company_agent.common.embeddings import EmbeddingClient, EmbeddingConfig
from company_agent.common.logging import configure_logging
from company_agent.common.text import chunk_markdown

from .config import IngestSettings

DOCUMENT_SQL = """
INSERT INTO knowledge_documents (source_uri, source_type, title, content_md, metadata, updated_at)
VALUES (%(source_uri)s, %(source_type)s, %(title)s, %(content_md)s, %(metadata)s, NOW())
ON CONFLICT (source_uri) DO UPDATE SET
  source_type = EXCLUDED.source_type,
  title = EXCLUDED.title,
  content_md = EXCLUDED.content_md,
  metadata = EXCLUDED.metadata,
  updated_at = NOW()
RETURNING id::text
"""

DELETE_CHUNKS_SQL = "DELETE FROM knowledge_chunks WHERE document_id = %(document_id)s"

CHUNK_SQL = """
INSERT INTO knowledge_chunks (
  document_id,
  corpus,
  chunk_index,
  title,
  content,
  source_uri,
  metadata,
  embedding,
  updated_at
)
VALUES (
  %(document_id)s::uuid,
  %(corpus)s,
  %(chunk_index)s,
  %(title)s,
  %(content)s,
  %(source_uri)s,
  %(metadata)s,
  %(embedding)s::vector,
  NOW()
)
"""


@dataclass(slots=True)
class SourceDocument:
    source_uri: str
    source_type: str
    title: str
    content: str
    metadata: dict


def iter_source_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.suffix.lower() in {".md", ".txt", ".json"} and path.is_file():
            yield path


def load_documents(path: Path) -> list[SourceDocument]:
    if path.suffix.lower() in {".md", ".txt"}:
        content = path.read_text(encoding="utf-8")
        return [
            SourceDocument(
                source_uri=str(path).replace("\\", "/"),
                source_type=path.suffix.lower().removeprefix("."),
                title=path.stem.replace("-", " ").replace("_", " ").strip().title(),
                content=content,
                metadata={"path": str(path).replace("\\", "/")},
            )
        ]

    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = [payload]

    documents: list[SourceDocument] = []
    for index, item in enumerate(payload):
        title = item.get("title") or f"{path.stem} {index + 1}"
        content = item.get("content", "")
        metadata = item.get("metadata", {})
        source_uri = f"{str(path).replace('\\', '/')}#item-{index}"
        documents.append(
            SourceDocument(
                source_uri=source_uri,
                source_type="json",
                title=title,
                content=content,
                metadata=metadata,
            )
        )
    return documents


def sync_documents(settings: IngestSettings) -> None:
    logger = configure_logging("ingest-worker")
    embedding_client = EmbeddingClient(
        EmbeddingConfig(
            provider=settings.embedding_provider,
            api_key=settings.openai_api_key,
            model=settings.openai_embedding_model,
        )
    )
    root = Path(settings.knowledge_root)

    if not root.exists():
        raise FileNotFoundError(f"Knowledge root does not exist: {root}")

    total_docs = 0
    total_chunks = 0

    with connect(settings.database_url) as conn:
        for path in iter_source_files(root):
            for document in load_documents(path):
                total_docs += 1
                document_row = conn.execute(
                    DOCUMENT_SQL,
                    {
                        "source_uri": document.source_uri,
                        "source_type": document.source_type,
                        "title": document.title,
                        "content_md": document.content,
                        "metadata": Jsonb(document.metadata),
                    },
                ).fetchone()
                document_id = document_row["id"]
                conn.execute(DELETE_CHUNKS_SQL, {"document_id": document_id})

                chunks = chunk_markdown(document.content)
                for chunk in chunks:
                    metadata = {**document.metadata, "path": document.source_uri}
                    embedding = embedding_client.embed(chunk.text)
                    conn.execute(
                        CHUNK_SQL,
                        {
                            "document_id": document_id,
                            "corpus": settings.default_corpus,
                            "chunk_index": chunk.index,
                            "title": document.title,
                            "content": chunk.text,
                            "source_uri": document.source_uri,
                            "metadata": Jsonb(metadata),
                            "embedding": vector_literal(embedding) if embedding else None,
                        },
                    )
                    total_chunks += 1

                logger.info(
                    "ingested source=%s chunks=%s",
                    document.source_uri,
                    len(chunks),
                )

    logger.info("ingestion completed documents=%s chunks=%s", total_docs, total_chunks)


def main() -> None:
    parser = argparse.ArgumentParser(description="Knowledge ingestion worker")
    parser.add_argument("command", choices=["sync"], help="Worker command to run")
    args = parser.parse_args()

    settings = IngestSettings()

    if args.command == "sync":
        sync_documents(settings)


if __name__ == "__main__":
    main()
