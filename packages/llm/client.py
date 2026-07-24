"""The one entrypoint that talks to model providers (CLAUDE.md #6).

complete(purpose, messages, schema=None) resolves a model from env by
purpose, sends the request with 2 retries / exponential backoff on
timeout/5xx/429 (non-retryable 4xx fails immediately), limits concurrent
outbound requests to LLM_MAX_CONCURRENCY, and logs every attempt to
llm_calls (packages/llm/logging.py) — one row per HTTP attempt actually
sent to the gateway (transport retries are invisible plumbing and don't get
their own rows; a structured-output repair retry is a second real request
and does).

`llm_calls.ok` reflects transport/response success (HTTP 200, parseable
envelope) — not whether the content later validated against a caller's
Pydantic schema. Schema-validation failures surface to the caller as
StructuredOutputError instead (see structured.py); duplicating that into
the same `ok` column would conflate two different failure modes the
architecture already treats differently (§2.13: transport failure vs.
parse failure have different recovery paths).
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel

from slidevision.llm import config, logging as llm_logging, structured
from slidevision.llm.errors import LlmRequestError

_BACKOFF_BASE_SECONDS = 0.5
_MAX_ATTEMPTS = 3  # 1 initial + 2 retries

_concurrency_semaphore = threading.Semaphore(config.MAX_CONCURRENCY)
_http_client = httpx.Client(timeout=config.TIMEOUT_SECONDS)


@dataclass
class CompleteResult:
    content: str
    parsed: BaseModel | None
    model: str
    usage: dict[str, Any] | None
    llm_call_id: uuid.UUID


def _headers() -> dict[str, str]:
    return {"authorization": f"Bearer {config.API_KEY}", "content-type": "application/json"}


def _do_request(payload: dict[str, Any]) -> tuple[int, str | None, str | None, dict[str, Any] | None]:
    """One HTTP attempt. Returns (status, content, error_body, usage);
    content/error_body are mutually exclusive."""
    if payload.get("stream"):
        return _do_stream_request(payload)

    endpoint = config.chat_completions_url()
    resp = _http_client.post(endpoint, headers=_headers(), json=payload)
    if resp.status_code != 200:
        return resp.status_code, None, resp.text, None
    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage")
    except Exception as exc:
        return resp.status_code, None, f"malformed response body: {exc}: {resp.text[:500]}", None
    return resp.status_code, content, None, usage


def _do_stream_request(payload: dict[str, Any]) -> tuple[int, str | None, str | None, dict[str, Any] | None]:
    endpoint = config.chat_completions_url()
    content_parts: list[str] = []
    usage: dict[str, Any] | None = None
    with _http_client.stream("POST", endpoint, headers=_headers(), json=payload) as resp:
        if resp.status_code != 200:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status_code, None, body, None
        for line in resp.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            data_str = line[len("data:") :].strip()
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            delta = (chunk.get("choices") or [{}])[0].get("delta", {})
            piece = delta.get("content")
            if piece:
                content_parts.append(piece)
            if chunk.get("usage"):
                usage = chunk["usage"]
    return resp.status_code, "".join(content_parts), None, usage


def _post_with_transport_retries(payload: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    """Retries on timeout / connection error / 429 / 5xx only. Any other
    non-200 (bad request, auth, etc.) is not our failure to retry — it
    fails immediately. Raises LlmRequestError; caller logs it."""
    last_error = "unknown error"
    for attempt in range(_MAX_ATTEMPTS):
        try:
            status, content, error_body, usage = _do_request(payload)
        except httpx.TimeoutException as exc:
            last_error = f"timeout: {exc}"
            status = None
        except httpx.TransportError as exc:
            last_error = f"transport error: {exc}"
            status = None
        else:
            if status == 200:
                return content or "", usage
            if status == 429 or status >= 500:
                last_error = f"HTTP {status}: {(error_body or '')[:500]}"
            else:
                raise LlmRequestError(f"HTTP {status}: {(error_body or '')[:500]}")

        if attempt < _MAX_ATTEMPTS - 1:
            time.sleep(_BACKOFF_BASE_SECONDS * (2**attempt))
            continue
        raise LlmRequestError(f"gave up after {attempt + 1} attempt(s): {last_error}")

    raise LlmRequestError(f"gave up: {last_error}")  # unreachable, satisfies type-checker


def complete(
    purpose: str,
    messages: list[dict[str, Any]],
    schema: type[BaseModel] | None = None,
    *,
    stream: bool = False,
    prompt_id: str = "adhoc",
    prompt_version: str = "unversioned",
    session_id: uuid.UUID | None = None,
    turn_id: uuid.UUID | None = None,
    max_tokens: int = 1024,
    temperature: float | None = None,
) -> CompleteResult:
    """One call = one purpose-resolved model, logged to llm_calls.

    schema=None returns the raw completion text (parsed=None). schema set
    returns a validated instance of it (parsed set) via structured.py's
    json_object-primary / prompt-only-fallback strategy, with one repair
    retry on failure — see structured.py for why.
    """
    model = config.resolve_model_for_purpose(purpose)
    last_call_id: list[uuid.UUID] = []

    def _send(
        attempt_messages: list[dict[str, Any]], response_format: dict[str, Any] | None
    ) -> tuple[str, dict[str, Any] | None]:
        payload: dict[str, Any] = {"model": model, "messages": attempt_messages, "max_tokens": max_tokens}
        if temperature is not None:
            payload["temperature"] = temperature
        if response_format is not None:
            payload["response_format"] = response_format
        if stream:
            payload["stream"] = True

        started = time.perf_counter()
        with _concurrency_semaphore:
            try:
                content, usage = _post_with_transport_retries(payload)
            except LlmRequestError as exc:
                latency_ms = round((time.perf_counter() - started) * 1000)
                call_id = llm_logging.record_llm_call(
                    purpose=purpose,
                    model=model,
                    prompt_id=prompt_id,
                    prompt_version=prompt_version,
                    ok=False,
                    session_id=session_id,
                    turn_id=turn_id,
                    latency_ms=latency_ms,
                    error=str(exc),
                )
                last_call_id.append(call_id)
                raise

        latency_ms = round((time.perf_counter() - started) * 1000)
        input_tokens = usage.get("prompt_tokens") if usage else None
        output_tokens = usage.get("completion_tokens") if usage else None
        call_id = llm_logging.record_llm_call(
            purpose=purpose,
            model=model,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            ok=True,
            session_id=session_id,
            turn_id=turn_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )
        last_call_id.append(call_id)
        return content, usage

    if schema is None:
        content, usage = _send(messages, None)
        return CompleteResult(
            content=content, parsed=None, model=model, usage=usage, llm_call_id=last_call_id[-1]
        )

    parsed, raw_content, usage_1, usage_2 = structured.complete_structured(_send, messages, schema)
    usage = usage_2 or usage_1
    return CompleteResult(
        content=raw_content, parsed=parsed, model=model, usage=usage, llm_call_id=last_call_id[-1]
    )
