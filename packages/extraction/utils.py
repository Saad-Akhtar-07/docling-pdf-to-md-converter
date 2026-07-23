import hashlib
import json
import math
import re
import subprocess
from datetime import datetime, timezone
from typing import Any

from . import config


def clamp_render_scale(value: float) -> float:
    if not math.isfinite(value) or value <= 0:
        return config.DEFAULT_IMAGES_SCALE
    return min(value, config.MAX_RENDER_SCALE)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def estimate_data_uri_bytes(source: str) -> int:
    if not source:
        return 0

    encoded = source.split(",", 1)[1] if "," in source else source
    return round((len(encoded.strip()) * 3) / 4)


def compact_page_text(page_text: str) -> str:
    return re.sub(r"\s+", " ", str(page_text or "")).strip()[: config.OPENCODE_VISION_PAGE_TEXT_CHARS]


def get_no_window_flag() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def format_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items if item)


def _repair_truncated_json(text: str) -> str:
    """Best-effort repair of JSON that was cut off at a token limit.

    Strategy:
    1. Close any open string (add a closing quote).
    2. Close any open arrays and objects from the inside out.
    3. Return the repaired text so json.loads() can succeed.
    """
    # Walk the string tracking state
    in_string = False
    escape_next = False
    depth_stack: list[str] = []  # '{' or '['

    for ch in text:
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if not in_string:
            if ch in "{":
                depth_stack.append("}")
            elif ch in "[":
                depth_stack.append("]")
            elif ch in "}]":
                if depth_stack and depth_stack[-1] == ch:
                    depth_stack.pop()

    # Close open string first
    repaired = text
    if in_string:
        repaired += '"'

    # Close open containers in reverse order
    for closer in reversed(depth_stack):
        repaired += closer

    return repaired


def normalize_json_content(content: str, is_truncated: bool = False) -> dict[str, Any]:
    """Parse JSON from model output.

    Handles three cases:
    - Clean JSON string
    - JSON wrapped in ```json...``` fences
    - Truncated JSON (token limit hit) — repaired before parsing
    """
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    # Fast path: valid JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting outermost {...} object
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    # If the model was cut off at the token limit, attempt structural repair
    if is_truncated and start != -1:
        repaired = _repair_truncated_json(text[start:])
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

    # Nothing worked — let the original error surface
    raise json.JSONDecodeError("Could not parse model output as JSON", text, 0)
