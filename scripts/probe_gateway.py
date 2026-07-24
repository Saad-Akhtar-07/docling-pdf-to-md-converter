"""Capability probe for the OpenCode Zen gateway (packages/llm, Step 1).

Standalone script, deliberately not importing packages/llm (which doesn't
exist yet — this probe's output decides how to build it). Run it directly:

    python scripts/probe_gateway.py

Tests, per model: plain chat completion, streaming, response_format
json_object, response_format json_schema, tool/function calling, whether
`usage` is returned, and latency for a ~200 token completion. Prints a
results table and exits; makes no assumptions about what the gateway
supports beyond the OpenAI-compatible request/response shape.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_REPO_ROOT / ".env.local")
load_dotenv(_REPO_ROOT / ".env")

RAW_BASE_URL = os.getenv("OPENCODE_BASE_URL", "https://opencode.ai/zen/go/v1").strip()
API_KEY = os.getenv("OPENCODE_API_KEY", "").strip()
MODELS = ["deepseek-v4-pro", "deepseek-v4-flash", "mimo-v2.5"]
TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))


def chat_completions_url(base_url: str) -> str:
    """Accept either the bare base ('.../v1') or the full endpoint
    ('.../v1/chat/completions') and normalize to the full endpoint."""
    trimmed = base_url.rstrip("/")
    if trimmed.endswith("/chat/completions"):
        trimmed = trimmed[: -len("/chat/completions")]
    return f"{trimmed.rstrip('/')}/chat/completions"


ENDPOINT = chat_completions_url(RAW_BASE_URL)


@dataclass
class ProbeResult:
    ok: bool
    detail: str
    latency_ms: float | None = None


@dataclass
class ModelReport:
    model: str
    plain_chat: ProbeResult = field(default_factory=lambda: ProbeResult(False, "not run"))
    streaming: ProbeResult = field(default_factory=lambda: ProbeResult(False, "not run"))
    json_object: ProbeResult = field(default_factory=lambda: ProbeResult(False, "not run"))
    json_schema: ProbeResult = field(default_factory=lambda: ProbeResult(False, "not run"))
    tool_calling: ProbeResult = field(default_factory=lambda: ProbeResult(False, "not run"))
    usage_returned: ProbeResult = field(default_factory=lambda: ProbeResult(False, "not run"))
    latency_200tok_ms: float | None = None


def _headers() -> dict[str, str]:
    return {"authorization": f"Bearer {API_KEY}", "content-type": "application/json"}


def _post(payload: dict, *, stream: bool = False) -> tuple[int, str, float]:
    started = time.perf_counter()
    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        if stream:
            with client.stream("POST", ENDPOINT, headers=_headers(), json=payload) as resp:
                body = ""
                for chunk in resp.iter_text():
                    body += chunk
                elapsed_ms = (time.perf_counter() - started) * 1000
                return resp.status_code, body, elapsed_ms
        resp = client.post(ENDPOINT, headers=_headers(), json=payload)
        elapsed_ms = (time.perf_counter() - started) * 1000
        return resp.status_code, resp.text, elapsed_ms


def _truncate(text: str, n: int = 160) -> str:
    text = text.strip().replace("\n", " ")
    return text if len(text) <= n else text[: n - 1] + "…"


def probe_streaming(model: str) -> ProbeResult:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Count from 1 to 5, one number per word."}],
        "max_tokens": 300,
        "stream": True,
    }
    try:
        status, body, elapsed_ms = _post(payload, stream=True)
    except Exception as exc:
        return ProbeResult(False, f"request error: {exc}")
    if status != 200:
        return ProbeResult(False, f"HTTP {status}: {_truncate(body)}", elapsed_ms)
    chunk_lines = [line for line in body.splitlines() if line.startswith("data:")]
    saw_done = any(line.strip() == "data: [DONE]" for line in chunk_lines)
    if not chunk_lines:
        return ProbeResult(False, f"HTTP 200 but no SSE data: lines: {_truncate(body)}", elapsed_ms)
    if len(chunk_lines) < 2 and not saw_done:
        return ProbeResult(False, f"only {len(chunk_lines)} chunk(s) — may not be real streaming", elapsed_ms)
    return ProbeResult(True, f"{len(chunk_lines)} SSE chunks, done={saw_done}", elapsed_ms)


def probe_json_object(model: str) -> ProbeResult:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": 'Return JSON with exactly two keys: "animal" (string) and "legs" (integer). No prose.',
            }
        ],
        "max_tokens": 300,
        "response_format": {"type": "json_object"},
    }
    try:
        status, body, elapsed_ms = _post(payload)
    except Exception as exc:
        return ProbeResult(False, f"request error: {exc}")
    if status != 200:
        return ProbeResult(False, f"HTTP {status}: {_truncate(body)}", elapsed_ms)
    try:
        data = json.loads(body)
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except Exception as exc:
        return ProbeResult(False, f"not valid JSON content: {exc}: {_truncate(body)}", elapsed_ms)
    if "animal" not in parsed or "legs" not in parsed:
        return ProbeResult(False, f"valid JSON but missing requested keys: {_truncate(content)}", elapsed_ms)
    return ProbeResult(True, _truncate(content, 60), elapsed_ms)


def probe_json_schema(model: str) -> ProbeResult:
    schema = {
        "type": "object",
        "properties": {
            "animal": {"type": "string"},
            "legs": {"type": "integer"},
        },
        "required": ["animal", "legs"],
        "additionalProperties": False,
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": "Describe any four-legged animal."},
        ],
        "max_tokens": 400,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "animal_fact", "strict": True, "schema": schema},
        },
    }
    try:
        status, body, elapsed_ms = _post(payload)
    except Exception as exc:
        return ProbeResult(False, f"request error: {exc}")
    if status != 200:
        return ProbeResult(False, f"HTTP {status}: {_truncate(body)}", elapsed_ms)
    try:
        data = json.loads(body)
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except Exception as exc:
        return ProbeResult(False, f"not valid JSON content: {exc}: {_truncate(body)}", elapsed_ms)
    if "animal" not in parsed or "legs" not in parsed:
        return ProbeResult(False, f"valid JSON but missing requested keys: {_truncate(content)}", elapsed_ms)
    return ProbeResult(True, _truncate(content, 60), elapsed_ms)


def probe_tool_calling(model: str) -> ProbeResult:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get the current weather for a city",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }
    ]
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "What's the weather in Lahore right now?"}],
        "max_tokens": 400,
        "tools": tools,
        "tool_choice": "auto",
    }
    try:
        status, body, elapsed_ms = _post(payload)
    except Exception as exc:
        return ProbeResult(False, f"request error: {exc}")
    if status != 200:
        return ProbeResult(False, f"HTTP {status}: {_truncate(body)}", elapsed_ms)
    try:
        data = json.loads(body)
        message = data["choices"][0]["message"]
    except Exception as exc:
        return ProbeResult(False, f"malformed response: {exc}: {_truncate(body)}", elapsed_ms)
    tool_calls = message.get("tool_calls")
    if not tool_calls:
        return ProbeResult(
            False,
            f"HTTP 200 but no tool_calls emitted (content={_truncate(message.get('content') or '', 60)})",
            elapsed_ms,
        )
    fn_name = tool_calls[0].get("function", {}).get("name")
    return ProbeResult(True, f"called {fn_name}", elapsed_ms)


def probe_usage(plain_chat_body_status: int, plain_chat_body: str) -> ProbeResult:
    if plain_chat_body_status != 200:
        return ProbeResult(False, "skipped: plain chat failed")
    try:
        data = json.loads(plain_chat_body)
    except Exception as exc:
        return ProbeResult(False, f"could not parse: {exc}")
    usage = data.get("usage")
    if not usage:
        return ProbeResult(False, "no 'usage' key in response")
    keys = ", ".join(sorted(usage.keys()))
    return ProbeResult(True, f"keys: {keys}")


def probe_latency_200tok(model: str) -> tuple[ProbeResult, float | None]:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": "Write a ~150 word explanation of how MapReduce's shuffle phase works, for a first-year CS student.",
            }
        ],
        "max_tokens": 200,
    }
    try:
        status, body, elapsed_ms = _post(payload)
    except Exception as exc:
        return ProbeResult(False, f"request error: {exc}"), None
    if status != 200:
        return ProbeResult(False, f"HTTP {status}: {_truncate(body)}", elapsed_ms), None
    return ProbeResult(True, f"{elapsed_ms:.0f} ms"), elapsed_ms


def run_probe_for_model(model: str) -> ModelReport:
    report = ModelReport(model=model)

    # plain chat — also reused (raw status/body) for the usage-returned check
    started = time.perf_counter()
    try:
        status, body, elapsed_ms = _post(
            {
                "model": model,
                "messages": [{"role": "user", "content": "Reply with exactly the single word: pong"}],
                "max_tokens": 300,
            }
        )
    except Exception as exc:
        status, body, elapsed_ms = 0, str(exc), (time.perf_counter() - started) * 1000

    if status == 200:
        try:
            data = json.loads(body)
            content = data["choices"][0]["message"]["content"]
            report.plain_chat = ProbeResult(True, _truncate(content, 60), elapsed_ms)
        except Exception as exc:
            report.plain_chat = ProbeResult(False, f"malformed response: {exc}: {_truncate(body)}", elapsed_ms)
    else:
        report.plain_chat = ProbeResult(False, f"HTTP {status}: {_truncate(body)}", elapsed_ms)

    report.usage_returned = probe_usage(status, body)
    report.streaming = probe_streaming(model)
    report.json_object = probe_json_object(model)
    report.json_schema = probe_json_schema(model)
    report.tool_calling = probe_tool_calling(model)
    _, report.latency_200tok_ms = probe_latency_200tok(model)

    return report


def _fmt_cell(result: ProbeResult) -> str:
    mark = "OK" if result.ok else "FAIL"
    return f"{mark}: {result.detail}"


def print_table(reports: list[ModelReport]) -> None:
    columns = [
        ("model", lambda r: r.model),
        ("plain_chat", lambda r: _fmt_cell(r.plain_chat)),
        ("streaming", lambda r: _fmt_cell(r.streaming)),
        ("json_object", lambda r: _fmt_cell(r.json_object)),
        ("json_schema", lambda r: _fmt_cell(r.json_schema)),
        ("tool_calling", lambda r: _fmt_cell(r.tool_calling)),
        ("usage", lambda r: _fmt_cell(r.usage_returned)),
        ("latency_200tok", lambda r: f"{r.latency_200tok_ms:.0f} ms" if r.latency_200tok_ms else "n/a"),
    ]
    rows = [[getter(r) for _, getter in columns] for r in reports]
    headers = [name for name, _ in columns]
    widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(len(headers))]

    def fmt_row(cells: list[str]) -> str:
        return " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))

    print(fmt_row(headers))
    print("-+-".join("-" * w for w in widths))
    for row in rows:
        print(fmt_row(row))


def main() -> None:
    print(f"Endpoint: {ENDPOINT}")
    if not API_KEY:
        raise SystemExit("OPENCODE_API_KEY is not set (.env.local). Aborting probe.")

    reports = []
    for model in MODELS:
        print(f"\nProbing {model} ...")
        reports.append(run_probe_for_model(model))

    print("\n=== Capability table ===\n")
    print_table(reports)


if __name__ == "__main__":
    main()
