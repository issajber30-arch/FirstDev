# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import logging
import time
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Protocol

import anthropic
import pydantic
from pydantic import BaseModel

from firstdev.config import get_settings
from firstdev.errors import TransientError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

log = logging.getLogger("firstdev.llm")

# USD per million tokens (input, output). The only place prices live.
PRICES: dict[str, tuple[float, float]] = {"claude-opus-5-5": (4.0, 20.0)}


def cost_usd(model: str | None, input_tokens: int, output_tokens: int) -> float:
    """Unknown models (e.g. a fallback model) are priced at the most expensive known rate."""
    p_in, p_out = PRICES.get(model or "") or max(PRICES.values())
    return (input_tokens * p_in + output_tokens * p_out) / 1_000_000


@dataclass(frozen=True)
class LLMContext:
    """Who a call is for; recorded in the budget ledger. `kind` is the job kind."""

    user_id: str | None
    world_id: str | None
    kind: str


def job_context(db: "Session", job) -> LLMContext:
    from firstdev.models import User

    user = db.get(User, job.user_id)
    # World ids arrive with sandboxes (M17); getattr keeps the pipelines unchanged until then.
    return LLMContext(job.user_id, getattr(user, "world_id", None), str(job.kind))


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
        self,
        schema: type[T],
        system: str,
        user_content: str,
        *,
        max_tokens: int = 16000,
        context: LLMContext | None = None,
    ) -> LLMResult[T]: ...


def _release(factory: Any, ledger_id: str) -> None:
    from firstdev import budget

    try:
        budget.release(factory, ledger_id)
    except Exception:  # never mask the original error; the reservation just stays counted
        log.exception("budget release failed ledger=%s", ledger_id)


class AnthropicLLM:
    def __init__(self, client: Any = None, db_factory: Any = None):
        self._client = client  # built lazily so importing never touches the network or the key
        self._db_factory = db_factory  # budget sessions; defaults to the app's sessionmaker

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = anthropic.Anthropic()  # key comes from ANTHROPIC_API_KEY
        return self._client

    def extract[T: BaseModel](
        self,
        schema: type[T],
        system: str,
        user_content: str,
        *,
        max_tokens: int = 16000,
        context: LLMContext | None = None,
    ) -> LLMResult[T]:
        from firstdev import budget  # lazy: budget imports this module's error classes

        settings = get_settings()
        factory = self._db_factory
        if factory is None:
            from firstdev.db import get_sessionmaker

            factory = get_sessionmaker()
        ctx = context or LLMContext(None, None, "unknown")
        # Raises BudgetExceeded before any API call, so there is nothing to release.
        ledger_id = budget.reserve(
            factory, ctx, budget.estimate_worst_usd(system, user_content, max_tokens)
        )
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
            # Tokens were spent but usage is unknown: keep the worst-case reservation counted.
            raise LLMInvalidOutput("output failed schema validation") from None
        except (anthropic.RateLimitError, anthropic.APIConnectionError) as e:
            _release(factory, ledger_id)
            raise LLMTransientError(type(e).__name__) from None
        except anthropic.APIStatusError as e:
            _release(factory, ledger_id)
            if e.status_code >= 500:
                raise LLMTransientError(f"API status {e.status_code}") from None
            raise LLMPermanentError(f"API status {e.status_code}") from None
        except BaseException:
            _release(factory, ledger_id)
            raise
        # The call happened (refusals and truncations are billed too), so settle before checking.
        try:
            budget.settle(
                factory,
                ledger_id,
                SimpleNamespace(
                    model=resp.model,
                    input_tokens=resp.usage.input_tokens,
                    output_tokens=resp.usage.output_tokens,
                ),
            )
        except Exception:  # a ledger hiccup must not lose a paid result; the reservation stands
            log.exception("budget settle failed ledger=%s", ledger_id)
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
        self.contexts: list[LLMContext | None] = []  # parallel to calls

    def extract[T: BaseModel](
        self,
        schema: type[T],
        system: str,
        user_content: str,
        *,
        max_tokens: int = 16000,
        context: LLMContext | None = None,
    ) -> LLMResult[T]:
        self.calls.append((schema, system, user_content))
        self.contexts.append(context)
        item = self._queue.popleft()
        if isinstance(item, Exception):
            raise item
        return LLMResult(item, "fake-model", None, 0, 0)  # type: ignore[arg-type]


@lru_cache
def get_llm() -> LLM:
    if get_settings().llm_mode == "fake":
        from firstdev.canned_llm import CannedLLM  # lazy: it imports the pipeline schemas

        return CannedLLM()
    return AnthropicLLM()
