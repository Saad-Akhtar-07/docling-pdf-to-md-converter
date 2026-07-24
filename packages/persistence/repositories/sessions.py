"""Repository for the session aggregate (sessions, session_objective_states,
turns, turn_events, llm_calls, session_reports).

CRUD only — no policy, no LLM calls. Those belong to packages/tutor_core and
packages/llm respectively.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from slidevision.persistence.enums import ObjectiveStatus, SessionStatus
from slidevision.persistence.models import (
    LlmCall,
    Session as SessionModel,
    SessionObjectiveState,
    SessionReport,
    Turn,
    TurnEvent,
)


class SessionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_session(
        self, *, document_id: uuid.UUID, plan_id: uuid.UUID, user_id: uuid.UUID | None = None
    ) -> SessionModel:
        db_session = SessionModel(
            document_id=document_id,
            plan_id=plan_id,
            user_id=user_id,
            status=SessionStatus.ACTIVE,
        )
        self.session.add(db_session)
        self.session.flush()
        return db_session

    def get_session(self, session_id: uuid.UUID) -> SessionModel | None:
        return self.session.get(SessionModel, session_id)

    def get_turn_by_idempotency_key(self, session_id: uuid.UUID, idempotency_key: str) -> Turn | None:
        stmt = select(Turn).where(
            Turn.session_id == session_id, Turn.idempotency_key == idempotency_key
        )
        return self.session.scalars(stmt).first()

    def add_turn(
        self,
        *,
        session_id: uuid.UUID,
        index: int,
        idempotency_key: str,
        student_message: str,
        intent=None,
        action=None,
        tutor_message: str | None = None,
        objective_id: uuid.UUID | None = None,
        latency_ms: int | None = None,
    ) -> Turn:
        turn = Turn(
            session_id=session_id,
            index=index,
            idempotency_key=idempotency_key,
            student_message=student_message,
            intent=intent,
            action=action,
            tutor_message=tutor_message,
            objective_id=objective_id,
            latency_ms=latency_ms,
        )
        self.session.add(turn)
        self.session.flush()
        return turn

    def get_turns(self, session_id: uuid.UUID, after_index: int | None = None) -> list[Turn]:
        stmt = select(Turn).where(Turn.session_id == session_id)
        if after_index is not None:
            stmt = stmt.where(Turn.index > after_index)
        stmt = stmt.order_by(Turn.index)
        return list(self.session.scalars(stmt))

    def add_turn_event(
        self, *, session_id: uuid.UUID, event_type: str, payload: dict, turn_id: uuid.UUID | None = None
    ) -> TurnEvent:
        event = TurnEvent(session_id=session_id, turn_id=turn_id, event_type=event_type, payload=payload)
        self.session.add(event)
        self.session.flush()
        return event

    def get_events(self, session_id: uuid.UUID) -> list[TurnEvent]:
        stmt = (
            select(TurnEvent)
            .where(TurnEvent.session_id == session_id)
            .order_by(TurnEvent.created_at)
        )
        return list(self.session.scalars(stmt))

    def upsert_objective_state(
        self,
        *,
        session_id: uuid.UUID,
        objective_id: uuid.UUID,
        status: ObjectiveStatus = ObjectiveStatus.UNSEEN,
        **fields,
    ) -> SessionObjectiveState:
        stmt = (
            pg_insert(SessionObjectiveState)
            .values(session_id=session_id, objective_id=objective_id, status=status, **fields)
            .on_conflict_do_update(
                index_elements=["session_id", "objective_id"],
                set_={"status": status, **fields},
            )
            .returning(SessionObjectiveState)
        )
        result = self.session.execute(stmt).scalar_one()
        self.session.flush()
        return result

    def record_llm_call(
        self,
        *,
        purpose: str,
        provider: str,
        model: str,
        prompt_id: str,
        prompt_version: str,
        session_id: uuid.UUID | None = None,
        turn_id: uuid.UUID | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        latency_ms: int | None = None,
        cost_usd: float | None = None,
        ok: bool = True,
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

    def create_report(
        self,
        *,
        session_id: uuid.UUID,
        summary: str,
        resolved: list[uuid.UUID] | None = None,
        deferred: list[uuid.UUID] | None = None,
        misconceptions: dict | None = None,
        effective_actions: dict | None = None,
    ) -> SessionReport:
        report = SessionReport(
            session_id=session_id,
            summary=summary,
            resolved=resolved or [],
            deferred=deferred or [],
            misconceptions=misconceptions or {},
            effective_actions=effective_actions or {},
        )
        self.session.add(report)
        self.session.flush()
        return report
