"""Env resolution for packages/llm.

Mirrors packages/persistence/db.py: no orchestrator injects these vars, so
this module loads .env.local / .env itself. Model selection is entirely
env-driven (CLAUDE.md: "resolved from env — never hardcoded") — a purpose
with no LLM_PURPOSE_<NAME> mapping, or an alias with no LLM_MODEL_<ALIAS>,
is a configuration error, not a silently-guessed default.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env.local")
load_dotenv(_REPO_ROOT / ".env")

PROVIDER_NAME = "opencode"

DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1"
RAW_BASE_URL = os.getenv("OPENCODE_BASE_URL", DEFAULT_BASE_URL).strip()
API_KEY = os.getenv("OPENCODE_API_KEY", "").strip()

MAX_CONCURRENCY = int(os.getenv("LLM_MAX_CONCURRENCY", "4"))
TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))

# Model aliases -> concrete model id. Only these three exist today (probe
# results, docs/ARCHITECTURE_REVIEW_AND_ROADMAP.md); a fourth alias just
# needs an LLM_MODEL_<ALIAS> env var, no code change.
_MODEL_ALIAS_ENV = {
    "reasoning": "LLM_MODEL_REASONING",
    "fast": "LLM_MODEL_FAST",
    "vision": "LLM_MODEL_VISION",
}


class LlmConfigError(RuntimeError):
    """Raised when a purpose or alias can't be resolved to a model from env."""


def chat_completions_url(base_url: str = RAW_BASE_URL) -> str:
    """Accept either the bare base ('.../v1') or the full endpoint
    ('.../v1/chat/completions') and normalize to the full endpoint."""
    trimmed = base_url.rstrip("/")
    if trimmed.endswith("/chat/completions"):
        trimmed = trimmed[: -len("/chat/completions")]
    return f"{trimmed.rstrip('/')}/chat/completions"


def resolve_model_for_purpose(purpose: str) -> str:
    """purpose (e.g. "plan") -> LLM_PURPOSE_PLAN=reasoning -> LLM_MODEL_REASONING=deepseek-v4-pro."""
    purpose_env = f"LLM_PURPOSE_{purpose.upper()}"
    alias = os.getenv(purpose_env, "").strip()
    if not alias:
        raise LlmConfigError(f"No {purpose_env} set in env — cannot resolve a model for purpose={purpose!r}.")
    return resolve_model_for_alias(alias, source=purpose_env)


def resolve_model_for_alias(alias: str, *, source: str | None = None) -> str:
    alias_env = _MODEL_ALIAS_ENV.get(alias)
    if alias_env is None:
        known = ", ".join(sorted(_MODEL_ALIAS_ENV))
        raise LlmConfigError(
            f"Unknown model alias {alias!r}" + (f" (from {source})" if source else "") + f" — known aliases: {known}."
        )
    model = os.getenv(alias_env, "").strip()
    if not model:
        raise LlmConfigError(f"No {alias_env} set in env — cannot resolve alias={alias!r}.")
    return model


def _cost_env_key(model: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", model).strip("_").upper()
    return f"LLM_COST_RATE_{slug}"


def get_cost_rate_per_million(model: str) -> tuple[float, float] | None:
    """(input_usd_per_1M_tokens, output_usd_per_1M_tokens), or None if unset.

    Never guessed: a model with no LLM_COST_RATE_<MODEL> env var logs
    cost_usd=NULL rather than an invented number (CLAUDE.md error-handling
    principle, applied to cost tracking).
    """
    raw = os.getenv(_cost_env_key(model), "").strip()
    if not raw:
        return None
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != 2:
        raise LlmConfigError(
            f"{_cost_env_key(model)} must be 'input_rate,output_rate' (USD per 1M tokens), got {raw!r}."
        )
    try:
        return float(parts[0]), float(parts[1])
    except ValueError as exc:
        raise LlmConfigError(f"{_cost_env_key(model)} is not two numbers: {raw!r}.") from exc
