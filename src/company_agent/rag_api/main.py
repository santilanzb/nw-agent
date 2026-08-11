from __future__ import annotations

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

app = FastAPI(title="RAG API", version="0.1.0")
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


def run() -> None:
    uvicorn.run("company_agent.rag_api.main:app", host="0.0.0.0", port=8081, reload=False)


if __name__ == "__main__":
    run()
