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

            client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
        except ImportError:
            logger.warning("langfuse not installed — LLM traces disabled")
            return None
        except Exception:
            logger.exception("langfuse client failed to build — LLM traces disabled")
            return None

        # The v3 SDK dropped `.trace()`, which these call sites are written
        # against. Detected once here rather than raising per turn: with the
        # attribute missing, every composed answer died before the model was
        # called and the patient got the canned failure line instead.
        if not hasattr(client, "trace"):
            logger.error(
                "langfuse exposes no .trace() — v3 SDK against v2 call sites. "
                "Traces are OFF until the observability rework; answers are not "
                "affected."
            )
            return None
        return client

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

        generation = self._trace_start(
            turn_id=turn_id,
            trace_name=trace_name,
            model=model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
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

            self._trace_end(
                generation, output=text, usage={"input": tokens_in, "output": tokens_out}
            )
            return text, tokens_in, tokens_out

        except Exception as exc:
            self._trace_end(generation, level="ERROR", status_message=str(exc))
            raise

    # ── Tracing: a side effect, never a dependency ────────────────────────────
    #
    # Every call below is swallowed. An observability tool changing its API, or
    # its host going down, must not cost a patient their answer — which is
    # exactly what happened: `.trace()` disappeared in the v3 SDK, the call sat
    # outside the try, and the model was never reached.

    def _trace_start(
        self,
        *,
        turn_id: uuid.UUID,
        trace_name: str,
        model: str,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> Any | None:
        if not self._lf:
            return None
        try:
            trace = self._lf.trace(id=str(turn_id), name="gutty_turn")
            return trace.generation(
                name=trace_name,
                model=model,
                input={"system": system, "messages": messages},
                model_parameters={"max_tokens": max_tokens},
            )
        except Exception:
            logger.exception("langfuse trace failed to start — answering anyway")
            return None

    def _trace_end(self, generation: Any | None, **fields: Any) -> None:
        try:
            if generation is not None:
                generation.end(**fields)
            if self._lf:
                self._lf.flush()
        except Exception:
            logger.exception("langfuse trace failed to close — the answer already went")
