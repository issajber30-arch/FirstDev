# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import logging
from types import SimpleNamespace

import anthropic
import httpx2 as httpx
import pytest
from pydantic import BaseModel

from firstdev.llm import (
    AnthropicLLM,
    FakeLLM,
    LLMInvalidOutput,
    LLMPermanentError,
    LLMRefused,
    LLMTransientError,
    LLMTruncated,
)


class Out(BaseModel):
    name: str


SECRET = "Jane Doe secret CV text 0541234567"


def fake_client(*, stop_reason="end_turn", parsed=None, raises=None):
    seen = {}

    def parse(**kw):
        seen.update(kw)
        if raises:
            raise raises
        return SimpleNamespace(
            model="claude-opus-5-5",
            _request_id="req_1",
            stop_reason=stop_reason,
            stop_details=SimpleNamespace(category="cyber"),
            parsed_output=parsed,
            usage=SimpleNamespace(input_tokens=11, output_tokens=7),
        )

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse)))
    return client, seen


def test_success_and_request_shape(caplog):
    client, seen = fake_client(parsed=Out(name="x"))
    with caplog.at_level(logging.INFO, logger="firstdev.llm"):
        r = AnthropicLLM(client).extract(Out, "sys prompt", SECRET)
    assert (r.data, r.request_id, r.input_tokens, r.output_tokens) == (
        Out(name="x"),
        "req_1",
        11,
        7,
    )
    assert seen["fallbacks"] == "default" and seen["output_format"] is Out
    assert seen["output_config"] == {"effort": "medium"}
    assert "thinking" not in seen and "temperature" not in seen and "tools" not in seen
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "req_1" in logged
    assert SECRET not in logged and "sys prompt" not in logged and "Jane" not in logged


@pytest.mark.parametrize(
    ("kw", "exc"),
    [
        ({"stop_reason": "refusal"}, LLMRefused),
        ({"stop_reason": "max_tokens", "parsed": Out(name="x")}, LLMTruncated),
        ({"stop_reason": "end_turn", "parsed": None}, LLMInvalidOutput),
    ],
)
def test_stop_reason_mapping(kw, exc, caplog):
    client, _ = fake_client(**kw)
    with caplog.at_level(logging.INFO, logger="firstdev.llm"), pytest.raises(exc):
        AnthropicLLM(client).extract(Out, "s", SECRET)
    assert SECRET not in " ".join(r.getMessage() for r in caplog.records)


def test_refusal_category():
    client, _ = fake_client(stop_reason="refusal")
    with pytest.raises(LLMRefused) as e:
        AnthropicLLM(client).extract(Out, "s", "u")
    assert e.value.category == "cyber"


def _status_err(code):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(code, request=req)
    cls = anthropic.RateLimitError if code == 429 else anthropic.APIStatusError
    return cls(SECRET, response=resp, body=None)


@pytest.mark.parametrize(
    ("err", "exc"),
    [
        (_status_err(429), LLMTransientError),
        (_status_err(500), LLMTransientError),
        (_status_err(529), LLMTransientError),
        (
            anthropic.APIConnectionError(
                request=httpx.Request("POST", "https://api.anthropic.com")
            ),
            LLMTransientError,
        ),
        (_status_err(400), LLMPermanentError),
        (_status_err(401), LLMPermanentError),
    ],
)
def test_sdk_error_mapping(err, exc):
    client, _ = fake_client(raises=err)
    with pytest.raises(exc) as e:
        AnthropicLLM(client).extract(Out, "s", "u")
    assert SECRET not in str(e.value)


def test_no_client_built_at_construction():
    assert AnthropicLLM()._client is None


def test_fake_llm_records_and_raises():
    fake = FakeLLM([Out(name="a"), LLMTransientError("x")])
    assert fake.extract(Out, "s", "u").data == Out(name="a")
    with pytest.raises(LLMTransientError):
        fake.extract(Out, "s2", "u2")
    assert fake.calls == [(Out, "s", "u"), (Out, "s2", "u2")]


def test_schema_validation_error_mapped():
    from firstdev.llm import AnthropicLLM, LLMInvalidOutput

    def bad(**kw):
        Out.model_validate({})  # raises pydantic.ValidationError like a schema mismatch

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=bad)))
    with pytest.raises(LLMInvalidOutput):
        AnthropicLLM(client).extract(Out, "sys", "user")
