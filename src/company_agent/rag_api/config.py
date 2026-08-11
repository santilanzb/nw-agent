from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RagSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "rag-api"
    database_url: str = Field(
        default="postgresql://agent:agent@postgres:5432/company_agent",
        alias="DATABASE_URL",
    )
    internal_api_key: str = Field(alias="INTERNAL_API_KEY")
    embedding_provider: str = Field(default="disabled", alias="EMBEDDING_PROVIDER")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        alias="OPENAI_EMBEDDING_MODEL",
    )
    retrieval_top_k_default: int = 5
    retrieval_candidate_pool: int = 12

    # Intent classifier thresholds
    intent_threshold_execute: float = Field(default=0.80, alias="INTENT_THRESHOLD_EXECUTE")
    intent_threshold_clarify: float = Field(default=0.55, alias="INTENT_THRESHOLD_CLARIFY")
    intent_tiebreak_margin: float = Field(default=0.05, alias="INTENT_TIEBREAK_MARGIN")
    # No INTENT_SEEDS_PATH: seeds are discovered from the installed function
    # packages, not from a configurable path. A path that could be wrong was a
    # path that silently produced an empty dispatch table.
