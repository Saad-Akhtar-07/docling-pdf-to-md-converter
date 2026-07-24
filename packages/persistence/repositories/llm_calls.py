"""Repository for the llm_calls table.

CRUD only, matching the style of repositories/documents.py. packages/llm's
logging.py is the only caller — every LLM call, successful or not, gets a
row here (CLAUDE.md invariant #6).
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from slidevision.persistence.models import LlmCall


class LlmCallRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        purpose: str,
        provider: str,
        model: str,
        prompt_id: str,
        prompt_version: str,
        ok: bool,
        session_id: uuid.UUID | None = None,
        turn_id: uuid.UUID | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        latency_ms: int | None = None,
        cost_usd: float | None = None,
        error: str | None = None,
    ) -> LlmCall:
        call = LlmCall(
            session_id=session_id,
            turn_id=turn_id,
            purpose=purpose,
            provider=provider,
            model=model,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            ok=ok,
            error=error,
        )
        self.session.add(call)
        self.session.flush()
        return call

    def get(self, call_id: uuid.UUID) -> LlmCall | None:
        return self.session.get(LlmCall, call_id)
