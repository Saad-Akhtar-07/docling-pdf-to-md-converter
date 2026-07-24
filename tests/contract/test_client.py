"""Offline contract tests for packages/llm/client.py: plain completions,
transport retry/backoff on 5xx/429, no retry on other 4xx, and that every
attempt gets an llm_calls row (ok=True/False as appropriate)."""

from __future__ import annotations

import httpx
import pytest
import respx

from slidevision.llm import config
from slidevision.llm.client import complete
from slidevision.llm.errors import LlmRequestError

ENDPOINT = config.chat_completions_url()


@respx.mock
def test_plain_completion_success(logged_calls, load_fixture):
    route = respx.post(ENDPOINT).mock(
        return_value=httpx.Response(200, json=load_fixture("chat_completion_ok.json"))
    )

    result = complete("generate", [{"role": "user", "content": "ping"}], prompt_id="test", prompt_version="v1")

    assert route.call_count == 1
    assert result.content == "pong"
    assert result.parsed is None
    assert result.usage == {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}
    assert len(logged_calls) == 1
    assert logged_calls[0]["ok"] is True
    assert logged_calls[0]["purpose"] == "generate"
    assert logged_calls[0]["prompt_id"] == "test"
    assert logged_calls[0]["input_tokens"] == 12
    assert logged_calls[0]["output_tokens"] == 3


@respx.mock
def test_transport_retry_then_success(logged_calls, load_fixture):
    route = respx.post(ENDPOINT).mock(
        side_effect=[
            httpx.Response(500, json=load_fixture("http_error_500.json")),
            httpx.Response(200, json=load_fixture("chat_completion_ok.json")),
        ]
    )

    result = complete("generate", [{"role": "user", "content": "ping"}])

    assert route.call_count == 2
    assert result.content == "pong"
    # transport retries are invisible plumbing -> exactly one logged attempt
    assert len(logged_calls) == 1
    assert logged_calls[0]["ok"] is True


@respx.mock
def test_transport_retries_exhausted_raises(logged_calls, load_fixture):
    route = respx.post(ENDPOINT).mock(
        return_value=httpx.Response(500, json=load_fixture("http_error_500.json"))
    )

    with pytest.raises(LlmRequestError):
        complete("generate", [{"role": "user", "content": "ping"}])

    assert route.call_count == 3  # 1 initial + 2 retries
    assert len(logged_calls) == 1
    assert logged_calls[0]["ok"] is False
    assert "HTTP 500" in logged_calls[0]["error"]


@respx.mock
def test_non_retryable_4xx_fails_immediately(logged_calls, load_fixture):
    route = respx.post(ENDPOINT).mock(
        return_value=httpx.Response(400, json=load_fixture("http_error_400.json"))
    )

    with pytest.raises(LlmRequestError):
        complete("generate", [{"role": "user", "content": "ping"}])

    assert route.call_count == 1  # no retry on a plain bad request
    assert logged_calls[0]["ok"] is False


@respx.mock
def test_429_retries_like_5xx(logged_calls, load_fixture):
    route = respx.post(ENDPOINT).mock(
        side_effect=[
            httpx.Response(429, json={"error": {"message": "rate limited"}}),
            httpx.Response(200, json=load_fixture("chat_completion_ok.json")),
        ]
    )

    result = complete("generate", [{"role": "user", "content": "ping"}])

    assert route.call_count == 2
    assert result.content == "pong"
