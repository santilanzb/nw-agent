from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI

from company_agent.common.auth import require_internal_api_key
from company_agent.common.embeddings import EmbeddingClient, EmbeddingConfig
from company_agent.common.logging import configure_logging

from .config import RagSettings
from .intent import IntentClassifier
from .schemas import (
    ClassifyIntentRequest,
    ClassifyIntentResponse,
    HealthResponse,
    ReloadDispatchResponse,
    RetrieveRequest,
    RetrieveResponse,
)
from .search import KnowledgeSearcher

settings = RagSettings()
logger = configure_logging(settings.app_name)
embedding_client = EmbeddingClient(
    EmbeddingConfig(
        provider=settings.embedding_provider,
        api_key=settings.openai_api_key,
        model=settings.openai_embedding_model,
    )
)
searcher = KnowledgeSearcher(settings=settings, embeddings=embedding_client)
classifier = IntentClassifier(settings=settings, embeddings=embedding_client)

@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """
    Load the dispatch table once at boot.

    A failure here is loud but not fatal: classification is the valuable half and
    works without dispatch, and an unreachable database is already fatal via the
    query path. What must not happen is the old behaviour — an empty table
    produced silently, indistinguishable from a working one.
    """
    try:
        added, _removed, _changed = classifier.reload_dispatch()
        logger.info("dispatch table loaded intents=%d", len(added))
        if not added:
            logger.error(
                "dispatch table is EMPTY — intent_vectors has no rows. "
                "Run the intent seeder; every execute decision will dispatch to nothing."
            )
    except Exception:
        logger.exception("dispatch table failed to load — serving with an empty table")
    yield


app = FastAPI(title="RAG API", version="0.2.0", lifespan=lifespan)
InternalApiKey = Annotated[None, Depends(require_internal_api_key(settings.internal_api_key))]


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/v1/retrieve", response_model=RetrieveResponse)
def retrieve(request: RetrieveRequest, _auth: InternalApiKey) -> RetrieveResponse:
    logger.info("retrieval request query=%r top_k=%s", request.query, request.top_k)
    return searcher.search(request)


@app.post("/v1/classify_intent", response_model=ClassifyIntentResponse)
def classify_intent(request: ClassifyIntentRequest, _auth: InternalApiKey) -> ClassifyIntentResponse:
    logger.info("classify_intent message=%r language=%s", request.message[:80], request.language_hint)
    return classifier.classify(request)


@app.post("/v1/admin/reload_dispatch", response_model=ReloadDispatchResponse)
def reload_dispatch(_auth: InternalApiKey) -> ReloadDispatchResponse:
    """
    Re-read the dispatch table from `intent_vectors` without a restart.

    Under `/v1/` so it inherits the internal-API-key guard. The blast radius is
    "re-read a table you already trust", and every holder of that key is a
    first-party service.

    Note the assumption: **a single rag-api replica.** With two, a reload reaches
    one container and the resulting split-brain dispatch table is undetectable.
    """
    added, removed, changed = classifier.reload_dispatch()
    table = classifier.dispatch_table
    logger.info(
        "dispatch reloaded intents=%d added=%s removed=%s changed=%s",
        len(table),
        added,
        removed,
        changed,
    )
    return ReloadDispatchResponse(
        source="intent_vectors",
        intent_classes=len(table),
        intents=sorted(table),
        added=added,
        removed=removed,
        changed=changed,
    )


def run() -> None:
    uvicorn.run("company_agent.rag_api.main:app", host="0.0.0.0", port=8081, reload=False)


if __name__ == "__main__":
    run()
