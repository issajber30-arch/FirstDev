# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import logging
import time
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

import anthropic
import pydantic
from pydantic import BaseModel

from firstdev.config import get_settings
from firstdev.errors import TransientError

log = logging.getLogger("firstdev.llm")


class LLMError(Exception):
    pass


class LLMRefused(LLMError):
    def __init__(self, category: str | None):
        super().__init__(f"model refused (category: {category})")
        self.category = category


class LLMTruncated(LLMError):
    pass


class LLMInvalidOutput(LLMError):
    pass


class LLMTransientError(LLMError, TransientError):
    pass


class LLMPermanentError(LLMError):
    pass


@dataclass(frozen=True)
class LLMResult[T: BaseModel]:
    data: T
    model: str
    request_id: str | None
    input_tokens: int
    output_tokens: int


class LLM(Protocol):
    def extract[T: BaseModel](
        self, schema: type[T], system: str, user_content: str, *, max_tokens: int = 16000
    ) -> LLMResult[T]: ...


class AnthropicLLM:
    def __init__(self, client: Any = None):
        self._client = client  # built lazily so importing never touches the network or the key

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = anthropic.Anthropic()  # key comes from ANTHROPIC_API_KEY
        return self._client

    def extract[T: BaseModel](
        self, schema: type[T], system: str, user_content: str, *, max_tokens: int = 16000
    ) -> LLMResult[T]:
        settings = get_settings()
        start = time.monotonic()
        try:
            # No tools and no thinking override (Opus 5.5 is adaptive by default).
            resp = self.client.beta.messages.parse(
                model=settings.llm_model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_content}],
                output_format=schema,
                output_config={"effort": settings.llm_effort},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except pydantic.ValidationError:  # JSON came back but didn't fit the schema
            raise LLMInvalidOutput("output failed schema validation") from None
        except (anthropic.RateLimitError, anthropic.APIConnectionError) as e:
            raise LLMTransientError(type(e).__name__) from None
        except anthropic.APIStatusError as e:
            if e.status_code >= 500:
                raise LLMTransientError(f"API status {e.status_code}") from None
            raise LLMPermanentError(f"API status {e.status_code}") from None
        usage = resp.usage
        # Never log prompt or output content: CVs are PII.
        log.info(
            "llm call model=%s request_id=%s input_tokens=%s output_tokens=%s stop_reason=%s "
            "latency_ms=%d",
            resp.model,
            getattr(resp, "_request_id", None),
            usage.input_tokens,
            usage.output_tokens,
            resp.stop_reason,
            (time.monotonic() - start) * 1000,
        )
        if resp.stop_reason == "refusal":
            raise LLMRefused(getattr(resp.stop_details, "category", None))
        if resp.stop_reason == "max_tokens":
            raise LLMTruncated("output hit max_tokens")
        if resp.parsed_output is None:
            raise LLMInvalidOutput("no parsed output")
        return LLMResult(
            resp.parsed_output,
            resp.model,
            getattr(resp, "_request_id", None),
            usage.input_tokens,
            usage.output_tokens,
        )


class FakeLLM:
    """Test double: replays queued responses (model instances, or exceptions to raise)."""

    def __init__(self, responses: list[BaseModel | Exception]):
        self._queue = deque(responses)
        self.calls: list[tuple[type[BaseModel], str, str]] = []

    def extract[T: BaseModel](
        self, schema: type[T], system: str, user_content: str, *, max_tokens: int = 16000
    ) -> LLMResult[T]:
        self.calls.append((schema, system, user_content))
        item = self._queue.popleft()
        if isinstance(item, Exception):
            raise item
        return LLMResult(item, "fake-model", None, 0, 0)  # type: ignore[arg-type]


@lru_cache
def get_llm() -> LLM:
    return AnthropicLLM()
