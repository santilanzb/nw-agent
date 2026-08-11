from __future__ import annotations

from dataclasses import dataclass

from openai import OpenAI


@dataclass(slots=True)
class EmbeddingConfig:
    provider: str = "disabled"
    api_key: str | None = None
    model: str = "text-embedding-3-small"


class EmbeddingClient:
    def __init__(self, config: EmbeddingConfig) -> None:
        self._config = config
        self._client = None

        if config.provider == "openai" and config.api_key:
            self._client = OpenAI(api_key=config.api_key)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def embed(self, text: str) -> list[float] | None:
        if not self._client:
            return None

        response = self._client.embeddings.create(
            model=self._config.model,
            input=text,
        )
        return list(response.data[0].embedding)

