from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RetrieveRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)
    top_k: int = Field(default=5, ge=1, le=20)
    corpus: str = Field(default="default")
    product: str | None = None
    language: str | None = None


class RetrievedPassage(BaseModel):
    chunk_id: str
    document_id: str
    chunk_index: int
    title: str
    content: str
    source_uri: str
    citation: str
    score: float
    matched_by: list[str]
    metadata: dict


class RetrieveResponse(BaseModel):
    query: str
    strategy: list[str]
    results: list[RetrievedPassage]


class HealthResponse(BaseModel):
    status: str


# ── Intent classifier schemas ────────────────────────────────────────────────

class ClassifyIntentRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    language_hint: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)


class IntentMatch(BaseModel):
    intent: str
    score: float
    example: str


class IntentDispatch(BaseModel):
    tool: str | None
    params: dict


class ClassifyIntentResponse(BaseModel):
    intent: str
    confidence: float
    decision: Literal["execute", "clarify", "fallback_llm"]
    dispatch: IntentDispatch | None
    top_matches: list[IntentMatch]

