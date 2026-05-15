from __future__ import annotations

import logging
import uuid
from typing import Any

import anthropic

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Thin async wrapper around the Anthropic SDK.
    Emits Langfuse traces when keys are configured; silently skips otherwise.
    """

    def __init__(
        self,
        api_key: str,
        default_model: str,
        escalation_model: str,
        langfuse_public_key: str = "",
        langfuse_secret_key: str = "",
        langfuse_host: str = "",
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._default_model = default_model
        self._escalation_model = escalation_model
        self._lf = self._init_langfuse(langfuse_public_key, langfuse_secret_key, langfuse_host)

    def _init_langfuse(
        self, public_key: str, secret_key: str, host: str
    ) -> Any | None:
        if not (public_key and secret_key):
            return None
        try:
            from langfuse import Langfuse  # type: ignore[import-untyped]

            return Langfuse(public_key=public_key, secret_key=secret_key, host=host)
        except ImportError:
            logger.warning("langfuse not installed — LLM traces disabled")
            return None

    def model(self, tier: str) -> str:
        return self._escalation_model if tier == "escalation" else self._default_model

    async def compose(
        self,
        *,
        turn_id: uuid.UUID,
        tier: str,
        system: str,
        user_message: str,
        max_tokens: int = 512,
        trace_name: str = "compose",
    ) -> tuple[str, int, int]:
        """
        Call the LLM, return (text, tokens_in, tokens_out).
        Wraps with a Langfuse generation if the client is configured.
        """
        model = self.model(tier)
        messages = [{"role": "user", "content": user_message}]

        generation = None
        trace = None
        if self._lf:
            trace = self._lf.trace(id=str(turn_id), name="gutty_turn")
            generation = trace.generation(
                name=trace_name,
                model=model,
                input={"system": system, "messages": messages},
                model_parameters={"max_tokens": max_tokens},
            )

        try:
            resp = await self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
            )
            text = resp.content[0].text if resp.content else ""
            tokens_in = resp.usage.input_tokens
            tokens_out = resp.usage.output_tokens

            if generation:
                generation.end(
                    output=text,
                    usage={"input": tokens_in, "output": tokens_out},
                )
            if self._lf:
                self._lf.flush()

            return text, tokens_in, tokens_out

        except Exception as exc:
            if generation:
                generation.end(level="ERROR", status_message=str(exc))
            if self._lf:
                self._lf.flush()
            raise
