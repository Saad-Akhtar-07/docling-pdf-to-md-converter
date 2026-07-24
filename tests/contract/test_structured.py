"""Offline contract tests for packages/llm/structured.py's repair-retry path,
exercised through complete(schema=...): primary json_object attempt, one
repair retry with the validation error appended and response_format
dropped (the prompt-only fallback), and a typed error if both fail."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from pydantic import BaseModel

from slidevision.llm import config
from slidevision.llm.client import complete
from slidevision.llm.errors import StructuredOutputError

ENDPOINT = config.chat_completions_url()


class AnimalFact(BaseModel):
    animal: str
    legs: int


@respx.mock
def test_structured_success_first_attempt(logged_calls, load_fixture):
    route = respx.post(ENDPOINT).mock(
        return_value=httpx.Response(200, json=load_fixture("json_object_valid.json"))
    )

    result = complete(
        "plan",
        [{"role": "user", "content": "Describe a four-legged animal."}],
        schema=AnimalFact,
        prompt_id="animal_fact",
        prompt_version="v1",
    )

    assert route.call_count == 1
    assert result.parsed == AnimalFact(animal="dog", legs=4)
    request_body = json.loads(route.calls[0].request.content)
    assert request_body["response_format"] == {"type": "json_object"}
    assert len(logged_calls) == 1
    assert logged_calls[0]["ok"] is True


@respx.mock
def test_structured_repair_retry_succeeds(logged_calls, load_fixture):
    route = respx.post(ENDPOINT).mock(
        side_effect=[
            httpx.Response(200, json=load_fixture("json_object_malformed.json")),
            httpx.Response(200, json=load_fixture("json_object_repaired.json")),
        ]
    )

    result = complete("plan", [{"role": "user", "content": "Describe a four-legged animal."}], schema=AnimalFact)

    assert route.call_count == 2
    assert result.parsed == AnimalFact(animal="cat", legs=4)

    first_body = json.loads(route.calls[0].request.content)
    second_body = json.loads(route.calls[1].request.content)
    assert first_body["response_format"] == {"type": "json_object"}
    assert "response_format" not in second_body
    # repair message carries the validation error forward
    repair_prompt = second_body["messages"][-1]["content"]
    assert "invalid" in repair_prompt.lower()

    # both HTTP attempts succeeded at the transport level -> both logged ok=True;
    # the parse failure on attempt 1 is a structured-output concern, not a
    # transport one (see client.py's module docstring).
    assert len(logged_calls) == 2
    assert logged_calls[0]["ok"] is True
    assert logged_calls[1]["ok"] is True


@respx.mock
def test_structured_repair_retry_fails_raises_typed_error(logged_calls, load_fixture):
    route = respx.post(ENDPOINT).mock(
        return_value=httpx.Response(200, json=load_fixture("json_object_malformed.json"))
    )

    with pytest.raises(StructuredOutputError) as exc_info:
        complete("plan", [{"role": "user", "content": "Describe a four-legged animal."}], schema=AnimalFact)

    assert route.call_count == 2  # primary attempt + exactly one repair retry, then give up
    err = exc_info.value
    assert err.raw_response
    assert "attempt 1" in err.validation_errors and "attempt 2" in err.validation_errors
    assert len(logged_calls) == 2
