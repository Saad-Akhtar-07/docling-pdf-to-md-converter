"""Writes every packages/llm call to the llm_calls table (CLAUDE.md #6).

Opens and commits its own DB session, independent of whatever transaction
the caller is in: a logging failure must never roll back — or be rolled
back by — the caller's business logic, and a call must be logged even if
the caller's own transaction later fails.
"""

from __future__ import annotations

import uuid

from slidevision.llm import config
from slidevision.persistence.db import get_session
from slidevision.persistence.repositories.llm_calls import LlmCallRepository


def _compute_cost_usd(model: str, input_tokens: int | None, output_tokens: int | None) -> float | None:
    if input_tokens is None or output_tokens is None:
        return None
    rate = config.get_cost_rate_per_million(model)
    if rate is None:
        return None
    input_rate, output_rate = rate
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


def record_llm_call(
    *,
    purpose: str,
    model: str,
    prompt_id: str,
    prompt_version: str,
    ok: bool,
    provider: str = config.PROVIDER_NAME,
    session_id: uuid.UUID | None = None,
    turn_id: uuid.UUID | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    latency_ms: int | None = None,
    error: str | None = None,
) -> uuid.UUID:
    cost_usd = _compute_cost_usd(model, input_tokens, output_tokens)
    db_session = get_session()
    try:
        repo = LlmCallRepository(db_session)
        call = repo.create(
            purpose=purpose,
            provider=provider,
            model=model,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            ok=ok,
            session_id=session_id,
            turn_id=turn_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            error=error,
        )
        db_session.commit()
        return call.id
    finally:
        db_session.close()
