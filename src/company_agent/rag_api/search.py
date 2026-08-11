from __future__ import annotations

from dataclasses import dataclass, field

from company_agent.common.db import connect, vector_literal
from company_agent.common.embeddings import EmbeddingClient

from .config import RagSettings
from .schemas import RetrievedPassage, RetrieveRequest, RetrieveResponse

LEXICAL_SQL = """
SELECT
  id::text AS chunk_id,
  document_id::text AS document_id,
  chunk_index,
  title,
  content,
  source_uri,
  metadata,
  ts_rank_cd(search_tsv, websearch_to_tsquery('simple', %(query)s)) AS score
FROM knowledge_chunks
WHERE search_tsv @@ websearch_to_tsquery('simple', %(query)s)
  AND corpus = %(corpus)s
  AND (%(product)s::text IS NULL OR metadata->>'product' = %(product)s::text)
  AND (%(language)s::text IS NULL OR metadata->>'language' = %(language)s::text)
ORDER BY score DESC
LIMIT %(limit)s
"""

SEMANTIC_SQL = """
SELECT
  id::text AS chunk_id,
  document_id::text AS document_id,
  chunk_index,
  title,
  content,
  source_uri,
  metadata,
  1 - (embedding <=> %(embedding)s::vector) AS score
FROM knowledge_chunks
WHERE embedding IS NOT NULL
  AND corpus = %(corpus)s
  AND (%(product)s::text IS NULL OR metadata->>'product' = %(product)s::text)
  AND (%(language)s::text IS NULL OR metadata->>'language' = %(language)s::text)
ORDER BY embedding <=> %(embedding)s::vector
LIMIT %(limit)s
"""


@dataclass(slots=True)
class SearchHit:
    chunk_id: str
    document_id: str
    chunk_index: int
    title: str
    content: str
    source_uri: str
    metadata: dict
    score: float
    matched_by: set[str] = field(default_factory=set)

    def to_response(self) -> RetrievedPassage:
        citation = f"{self.source_uri}#chunk-{self.chunk_index}"
        return RetrievedPassage(
            chunk_id=self.chunk_id,
            document_id=self.document_id,
            chunk_index=self.chunk_index,
            title=self.title,
            content=self.content,
            source_uri=self.source_uri,
            citation=citation,
            score=round(self.score, 6),
            matched_by=sorted(self.matched_by),
            metadata=self.metadata or {},
        )


def reciprocal_rank_fuse(rankings: dict[str, list[SearchHit]], top_k: int, rrf_k: int = 60) -> list[SearchHit]:
    fused: dict[str, SearchHit] = {}

    for strategy, hits in rankings.items():
        for rank, hit in enumerate(hits, start=1):
            if hit.chunk_id not in fused:
                fused[hit.chunk_id] = SearchHit(
                    chunk_id=hit.chunk_id,
                    document_id=hit.document_id,
                    chunk_index=hit.chunk_index,
                    title=hit.title,
                    content=hit.content,
                    source_uri=hit.source_uri,
                    metadata=hit.metadata,
                    score=0.0,
                )
            fused_hit = fused[hit.chunk_id]
            fused_hit.score += 1.0 / (rrf_k + rank)
            fused_hit.matched_by.add(strategy)

    return sorted(fused.values(), key=lambda item: item.score, reverse=True)[:top_k]


class KnowledgeSearcher:
    def __init__(self, settings: RagSettings, embeddings: EmbeddingClient) -> None:
        self._settings = settings
        self._embeddings = embeddings

    def search(self, request: RetrieveRequest) -> RetrieveResponse:
        limit = max(request.top_k, self._settings.retrieval_candidate_pool)
        lexical_hits = self._lexical_search(request, limit)
        rankings: dict[str, list[SearchHit]] = {"lexical": lexical_hits}
        strategy = ["lexical"]

        if self._embeddings.enabled:
            semantic_hits = self._semantic_search(request, limit)
            if semantic_hits:
                rankings["semantic"] = semantic_hits
                strategy.append("semantic")

        fused_hits = reciprocal_rank_fuse(rankings, top_k=request.top_k)
        return RetrieveResponse(
            query=request.query,
            strategy=strategy,
            results=[hit.to_response() for hit in fused_hits],
        )

    def _lexical_search(self, request: RetrieveRequest, limit: int) -> list[SearchHit]:
        params = {
            "query": request.query,
            "corpus": request.corpus,
            "product": request.product,
            "language": request.language,
            "limit": limit,
        }

        with connect(self._settings.database_url) as conn:
            rows = conn.execute(LEXICAL_SQL, params).fetchall()

        return [
            SearchHit(
                chunk_id=row["chunk_id"],
                document_id=row["document_id"],
                chunk_index=row["chunk_index"],
                title=row["title"],
                content=row["content"],
                source_uri=row["source_uri"],
                metadata=row["metadata"] or {},
                score=float(row["score"] or 0.0),
                matched_by={"lexical"},
            )
            for row in rows
        ]

    def _semantic_search(self, request: RetrieveRequest, limit: int) -> list[SearchHit]:
        embedding = self._embeddings.embed(request.query)
        if not embedding:
            return []

        params = {
            "embedding": vector_literal(embedding),
            "corpus": request.corpus,
            "product": request.product,
            "language": request.language,
            "limit": limit,
        }

        with connect(self._settings.database_url) as conn:
            rows = conn.execute(SEMANTIC_SQL, params).fetchall()

        return [
            SearchHit(
                chunk_id=row["chunk_id"],
                document_id=row["document_id"],
                chunk_index=row["chunk_index"],
                title=row["title"],
                content=row["content"],
                source_uri=row["source_uri"],
                metadata=row["metadata"] or {},
                score=float(row["score"] or 0.0),
                matched_by={"semantic"},
            )
            for row in rows
        ]

