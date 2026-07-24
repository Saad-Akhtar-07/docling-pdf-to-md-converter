"""POST /sessions, POST /sessions/{id}/turns, GET /sessions/{id}, GET
/sessions/{id}/turns (Module 4 -- docs/ARCHITECTURE_REVIEW_AND_ROADMAP.md
§2.11, §2.17's packages/graph).

Single-user MVP: no authentication, matching apps/api/routers/documents.py.
All turn execution goes through slidevision.graph.run_turn -- this router's
only job is HTTP framing (status codes, request/response shapes) around
that single entry point; no session/turn logic of its own lives here.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from apps.api.deps import get_db
from apps.api.schemas import (
    ObjectiveProgressOut,
    ProgressOut,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionOut,
    TurnHistoryItem,
    TurnOut,
    TurnRequest,
)
from slidevision.graph import SessionCompleteError, SessionNotFoundError, TutorTurn, run_turn
from slidevision.persistence.enums import ObjectiveStatus, PedagogicalAction, PlanStatus
from slidevision.persistence.models import Session as SessionModel
from slidevision.persistence.repositories import PlanRepository, SessionRepository

router = APIRouter(tags=["sessions"])


def _progress(objectives: list) -> ProgressOut:
    resolved = sum(1 for o in objectives if o.status.value == "resolved")
    deferred = sum(1 for o in objectives if o.status.value == "deferred")
    return ProgressOut(resolved=resolved, deferred=deferred, total=len(objectives))


def _serialize_turn(turn: TutorTurn) -> TurnOut:
    return TurnOut(
        turn_id=turn.turn_id,
        turn_index=turn.turn_index,
        session_id=turn.session_id,
        action=PedagogicalAction(turn.action.value),
        objective_id=turn.objective_id,
        objective_statement=turn.objective_statement,
        tutor_message=turn.tutor_message,
        student_message=turn.student_message,
        session_complete=turn.session_complete,
        progress=_progress(turn.objectives),
    )


def _serialize_session(db_session: SessionModel, plan_repo: PlanRepository) -> SessionOut:
    objectives = plan_repo.get_ordered_objectives(db_session.plan_id)
    states_by_id = {row.objective_id: row for row in db_session.objective_states}
    objectives_out = [
        ObjectiveProgressOut(
            objective_id=objective.id,
            statement=objective.statement,
            status=states_by_id[objective.id].status if objective.id in states_by_id else ObjectiveStatus.UNSEEN,
        )
        for objective in objectives
    ]
    return SessionOut(
        id=db_session.id,
        document_id=db_session.document_id,
        plan_id=db_session.plan_id,
        status=db_session.status,
        current_objective_id=db_session.current_objective_id,
        turn_count=db_session.turn_count,
        started_at=db_session.started_at,
        ended_at=db_session.ended_at,
        progress=_progress(objectives_out),
        objectives=objectives_out,
    )


@router.post("/sessions", response_model=SessionCreateResponse, status_code=status.HTTP_201_CREATED)
def create_session(body: SessionCreateRequest, db: Session = Depends(get_db)) -> SessionCreateResponse:
    plan_repo = PlanRepository(db)
    plan = plan_repo.get_plan(body.plan_id)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found.")
    if plan.document_id != body.document_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Plan does not belong to document.")
    if plan.status != PlanStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Plan must be approved before a session can start (status={plan.status.value}).",
        )

    objectives = plan_repo.get_ordered_objectives(plan.id)
    if not objectives:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Plan has no objectives.")

    session_repo = SessionRepository(db)
    db_session = session_repo.create_session(document_id=body.document_id, plan_id=body.plan_id)
    for objective in objectives:
        session_repo.upsert_objective_state(
            session_id=db_session.id, objective_id=objective.id, status=ObjectiveStatus.UNSEEN
        )
    db.commit()

    # The opening PROBE, with no student message yet -- a deterministic,
    # server-generated idempotency_key (not client-supplied) since this
    # call has no request body of its own to carry one.
    turn = run_turn(db_session.id, message=None, idempotency_key=f"session:{db_session.id}:init")

    db.expire_all()
    db_session = session_repo.get_session(db_session.id)
    return SessionCreateResponse(session=_serialize_session(db_session, plan_repo), turn=_serialize_turn(turn))


@router.post("/sessions/{session_id}/turns")
def post_turn(session_id: uuid.UUID, body: TurnRequest, db: Session = Depends(get_db)) -> StreamingResponse:
    try:
        turn = run_turn(session_id, message=body.message, idempotency_key=body.idempotency_key)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SessionCompleteError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    # Generation in this module is a deterministic template, not a
    # token-by-token LLM stream (see packages/graph/nodes.py::generate_turn),
    # so the whole turn is ready before the stream opens -- this emits it as
    # a single SSE event rather than genuinely streaming tokens. Real
    # streaming arrives with Module 7's generation.
    payload = _serialize_turn(turn).model_dump_json()

    def _events():
        yield f"event: turn\ndata: {payload}\n\n"

    return StreamingResponse(_events(), media_type="text/event-stream")


@router.get("/sessions/{session_id}", response_model=SessionOut)
def get_session(session_id: uuid.UUID, db: Session = Depends(get_db)) -> SessionOut:
    session_repo = SessionRepository(db)
    db_session = session_repo.get_session(session_id)
    if db_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    return _serialize_session(db_session, PlanRepository(db))


@router.get("/sessions/{session_id}/turns", response_model=list[TurnHistoryItem])
def get_turns(
    session_id: uuid.UUID,
    after: int | None = Query(default=None, description="Return only turns with index > after"),
    db: Session = Depends(get_db),
) -> list[TurnHistoryItem]:
    session_repo = SessionRepository(db)
    if session_repo.get_session(session_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    turns = session_repo.get_turns(session_id, after_index=after)
    return [TurnHistoryItem.model_validate(turn) for turn in turns]
