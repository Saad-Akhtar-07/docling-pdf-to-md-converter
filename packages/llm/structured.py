"""Structured output that does not depend on native JSON-schema mode.

Probe results (scripts/probe_gateway.py, run against deepseek-v4-pro,
deepseek-v4-flash, mimo-v2.5) ruled out `response_format: json_schema`:
deepseek-v4-* reject it outright (HTTP 400), mimo-v2.5 returns HTTP 200 but
silently ignores the schema. `response_format: json_object` works on all
three but is only a "valid JSON" guarantee, not a shape guarantee, and
deepseek models occasionally (~10-20% observed) return empty content when
their hidden reasoning consumes the token budget.

So: the target schema is always described in the prompt text (not just via
response_format), attempt 1 asks for json_object, and any failure — HTTP-
level, empty content, invalid JSON, or a Pydantic validation error — goes
through exactly one repair retry with the error appended, per
docs/ARCHITECTURE_REVIEW_AND_ROADMAP.md §2.13. A second failure raises
StructuredOutputError; this module never invents a fallback value.

No I/O here — `send` is injected by packages/llm/client.py, which owns the
HTTP transport, retries, and concurrency limiting.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, ValidationError

from slidevision.llm.errors import StructuredOutputError

SchemaT = TypeVar("SchemaT", bound=BaseModel)

# (messages, response_format) -> (raw_content, usage_dict_or_None). Raises on
# transport failure (client.py has already exhausted its own retries).
SendFn = Callable[[list[dict[str, Any]], dict[str, Any] | None], tuple[str, dict[str, Any] | None]]


def schema_instructions(schema: type[BaseModel]) -> str:
    schema_json = json.dumps(schema.model_json_schema(), indent=2)
    return (
        "Respond with ONLY a single JSON object matching this JSON Schema — "
        "no prose, no markdown code fences, no explanation:\n\n"
        f"{schema_json}"
    )


def append_schema_instructions(
    messages: list[dict[str, Any]], schema: type[BaseModel]
) -> list[dict[str, Any]]:
    return [*messages, {"role": "user", "content": schema_instructions(schema)}]


def extract_json_object(content: str) -> dict[str, Any]:
    """Parses a JSON object out of raw model output: clean JSON, JSON wrapped
    in ```json fences, or JSON with leading/trailing prose around it."""
    text = (content or "").strip()
    if not text:
        raise ValueError("model returned empty content")

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"could not parse JSON from model output: {text[:300]!r}")


def validate_against_schema(data: dict[str, Any], schema: type[SchemaT]) -> SchemaT:
    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


def complete_structured(
    send: SendFn,
    messages: list[dict[str, Any]],
    schema: type[SchemaT],
) -> tuple[SchemaT, str, dict[str, Any] | None, dict[str, Any] | None]:
    """Returns (parsed, final_raw_content, usage_attempt1, usage_attempt2).

    usage_attempt2 is None if attempt 1 succeeded (no repair retry needed).
    """
    annotated_messages = append_schema_instructions(messages, schema)

    raw_content_1 = ""
    usage_1: dict[str, Any] | None = None
    try:
        raw_content_1, usage_1 = send(annotated_messages, {"type": "json_object"})
        parsed = validate_against_schema(extract_json_object(raw_content_1), schema)
        return parsed, raw_content_1, usage_1, None
    except Exception as exc:
        first_error = str(exc)

    repair_messages = [
        *annotated_messages,
        {"role": "assistant", "content": raw_content_1 or "(no content returned)"},
        {
            "role": "user",
            "content": (
                f"That response was invalid: {first_error}\n\n"
                "Return ONLY a corrected JSON object matching the schema above. "
                "No prose, no markdown fences."
            ),
        },
    ]

    raw_content_2 = ""
    try:
        raw_content_2, usage_2 = send(repair_messages, None)
        parsed = validate_against_schema(extract_json_object(raw_content_2), schema)
        return parsed, raw_content_2, usage_1, usage_2
    except Exception as exc:
        raise StructuredOutputError(
            f"Structured output failed after repair retry: {exc}",
            raw_response=raw_content_2 or raw_content_1,
            validation_errors=f"attempt 1: {first_error}; attempt 2 (repair): {exc}",
        ) from exc
