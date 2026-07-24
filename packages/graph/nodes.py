"""LangGraph nodes for Module 4's turn skeleton.

Six nodes wired by build.py: load_state -> select_action(stub) ->
retrieve_grounding -> generate_turn -> persist_turn, plus one short-circuit
node (`return_existing`) reached instead of the rest whenever load_state
finds the idempotency_key already used -- see
docs/ARCHITECTURE_REVIEW_AND_ROADMAP.md §2.13, "Duplicate idempotency key ->
Return the stored turn, do not re-execute."

State only ever comes from `state["db"]` (Postgres) at load_state and is
written back by persist_turn (or read back unchanged by return_existing)
before the graph returns -- no LangGraph checkpointer, no in-memory session
state, matching CLAUDE.md invariants #1 and #3 and the turn contract's
rules 1/2 (§2.5).
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from slidevision.graph.errors import SessionCompleteError, SessionNotFoundError
from slidevision.graph.hydrate import to_tutor_core_state
from slidevision.graph.result import ObjectiveProgress, TutorTurn
from slidevision.graph.state import OrderedObjective, TurnState
from slidevision.persistence.enums import ObjectiveStatus as StoredStatus
from slidevision.persistence.enums import PedagogicalAction as StoredAction
from slidevision.persistence.enums import SessionStatus
from slidevision.persistence.models import Session as SessionModel
from slidevision.persistence.models import SessionObjectiveState, Turn
from slidevision.persistence.repositories import PlanRepository, SessionRepository
from slidevision.tutor_core import ObjectiveState, ObjectiveStatus, PedagogicalAction, select_action


def load_state(state: TurnState) -> dict:
    db: DbSession = state["db"]
    session_repo = SessionRepository(db)

    # Row lock for the rest of this turn's transaction: serializes any
    # concurrent turn on the same session so turn_count/current_objective_id
    # can never be a lost update (two concurrent POSTs to the same session
    # must not corrupt state -- part of the turn contract this module is
    # built to prove).
    db_session = db.execute(
        select(SessionModel).where(SessionModel.id == state["session_id"]).with_for_update()
    ).scalar_one_or_none()
    if db_session is None:
        raise SessionNotFoundError(f"no session with id={state['session_id']}")

    existing = session_repo.get_turn_by_idempotency_key(db_session.id, state["idempotency_key"])
    if existing is not None:
        return {"is_duplicate": True, "existing_turn_id": existing.id}

    if db_session.status != SessionStatus.ACTIVE:
        raise SessionCompleteError(f"session {db_session.id} is {db_session.status.value}, not active")

    plan_repo = PlanRepository(db)
    ordered = plan_repo.get_ordered_objectives(db_session.plan_id)
    objectives: list[OrderedObjective] = [
        OrderedObjective(objective_id=objective.id, statement=objective.statement) for objective in ordered
    ]

    state_rows: dict[uuid.UUID, SessionObjectiveState] = {row.objective_id: row for row in db_session.objective_states}
    objective_states: dict[str, ObjectiveState] = {
        str(objective.id): (
            to_tutor_core_state(state_rows[objective.id])
            if objective.id in state_rows
            else ObjectiveState(objective_id=str(objective.id))
        )
        for objective in ordered
    }

    return {
        "is_duplicate": False,
        "plan_id": db_session.plan_id,
        "document_id": db_session.document_id,
        "turn_index": db_session.turn_count,
        "current_objective_id": db_session.current_objective_id,
        "objectives": objectives,
        "objective_states": objective_states,
        "node_start_perf": time.perf_counter(),
    }


def select_action_node(state: TurnState) -> dict:
    probing_id = str(state["current_objective_id"]) if state["current_objective_id"] else None
    order = [str(o["objective_id"]) for o in state["objectives"]]

    result = select_action(
        objective_order=order,
        objective_states=state["objective_states"],
        probing_objective_id=probing_id,
        has_answer=state["message"] is not None,
    )

    return {
        "action": result.action,
        "target_objective_id": uuid.UUID(result.objective_id) if result.objective_id else None,
        "updated_objective_states": result.objective_states,
        "session_complete": result.session_complete,
    }


def retrieve_grounding(state: TurnState) -> dict:
    """Action-specific evidence assembly (§2.7 node 8) -- for this module's
    always-PROBE stub, "grounding" is just the target objective's own
    statement. Real span-anchored retrieval is Module 7."""
    target_id = state.get("target_objective_id")
    if target_id is None:
        return {"target_statement": None}
    statement = next((o["statement"] for o in state["objectives"] if o["objective_id"] == target_id), None)
    return {"target_statement": statement}


def generate_turn(state: TurnState) -> dict:
    """Deterministic template, not an LLM call: this module proves state
    plumbing only, not language generation (Module 7). Nothing here is
    logged to llm_calls because nothing here calls an LLM -- CLAUDE.md
    invariant #6 only binds actual LLM calls."""
    if state["session_complete"]:
        message = (
            "Nice work -- you've worked through every objective in this plan. "
            "That's the end of this session."
        )
    else:
        message = f"Let's check your understanding: {state['target_statement']}"
    return {"tutor_message": message}


def persist_turn(state: TurnState) -> dict:
    """Turn row + every turn_event, atomically (§2.7 node 10): nothing here
    is visible to another connection until this function's db.commit(), so
    a crash at any point before that leaves the session exactly as it was
    before this turn -- a retry with the same idempotency_key then runs the
    turn fresh rather than seeing a half-written one."""
    db: DbSession = state["db"]
    session_repo = SessionRepository(db)
    session_id = state["session_id"]
    turn_index = state["turn_index"]
    target_id = state.get("target_objective_id")
    message = state["message"]
    action = state["action"]

    turn = session_repo.add_turn(
        session_id=session_id,
        index=turn_index,
        idempotency_key=state["idempotency_key"],
        student_message=message or "",  # turn zero has no answer yet -- see apps/api/routers/sessions.py
        action=StoredAction(action.value),
        tutor_message=state["tutor_message"],
        objective_id=target_id,
        latency_ms=int((time.perf_counter() - state["node_start_perf"]) * 1000),
    )

    if message is not None:
        session_repo.add_turn_event(
            session_id=session_id, turn_id=turn.id, event_type="STUDENT_ANSWER", payload={"message": message}
        )

    session_repo.add_turn_event(
        session_id=session_id,
        turn_id=turn.id,
        event_type="POLICY_DECISION",
        payload={
            "action": action.value,
            "objective_id": str(target_id) if target_id else None,
            "session_complete": state["session_complete"],
        },
    )

    objectives_out: list[ObjectiveProgress] = []
    for objective in state["objectives"]:
        oid_str = str(objective["objective_id"])
        new_state = state["updated_objective_states"][oid_str]
        session_repo.upsert_objective_state(
            session_id=session_id,
            objective_id=objective["objective_id"],
            status=StoredStatus(new_state.status.value),
            attempts=new_state.attempts,
            hint_level=new_state.hint_level,
            deepen_count=new_state.deepen_count,
            prereq_revisits=new_state.prereq_revisits,
            met_count=new_state.met_count,
            active_misconception_id=new_state.active_misconception_id,
            last_action=StoredAction(new_state.last_action.value) if new_state.last_action else None,
        )
        objectives_out.append(
            ObjectiveProgress(objective_id=objective["objective_id"], statement=objective["statement"], status=new_state.status)
        )

    if not state["session_complete"]:
        session_repo.add_turn_event(
            session_id=session_id,
            turn_id=turn.id,
            event_type="TUTOR_QUESTION",
            payload={"objective_id": str(target_id), "message": state["tutor_message"]},
        )

    session_repo.add_turn_event(
        session_id=session_id,
        turn_id=turn.id,
        event_type="TUTOR_RESPONSE",
        payload={"message": state["tutor_message"], "action": action.value},
    )

    db_session = db.get(SessionModel, session_id)
    db_session.turn_count = turn_index + 1
    db_session.current_objective_id = target_id
    if state["session_complete"]:
        db_session.status = SessionStatus.COMPLETED
        db_session.ended_at = datetime.now(timezone.utc)

    db.commit()

    result = TutorTurn(
        turn_id=turn.id,
        turn_index=turn_index,
        session_id=session_id,
        action=action,
        objective_id=target_id,
        objective_statement=state.get("target_statement"),
        tutor_message=state["tutor_message"],
        student_message=message,
        session_complete=state["session_complete"],
        objectives=objectives_out,
    )
    return {"result": result}


def return_existing(state: TurnState) -> dict:
    """Duplicate idempotency_key path: read back exactly what an earlier
    call already persisted, without touching any state. Still needs to
    release the row lock load_state took, via a (no-op) commit."""
    db: DbSession = state["db"]
    turn = db.get(Turn, state["existing_turn_id"])
    db_session = db.get(SessionModel, state["session_id"])
    plan_repo = PlanRepository(db)
    ordered = plan_repo.get_ordered_objectives(db_session.plan_id)

    state_rows: dict[uuid.UUID, SessionObjectiveState] = {row.objective_id: row for row in db_session.objective_states}
    objectives_out = [
        ObjectiveProgress(
            objective_id=objective.id,
            statement=objective.statement,
            status=(
                ObjectiveStatus(state_rows[objective.id].status.value)
                if objective.id in state_rows
                else ObjectiveStatus.UNSEEN
            ),
        )
        for objective in ordered
    ]
    target_statement = next((objective.statement for objective in ordered if objective.id == turn.objective_id), None)

    db.commit()  # releases the row lock acquired in load_state; nothing changed

    result = TutorTurn(
        turn_id=turn.id,
        turn_index=turn.index,
        session_id=db_session.id,
        action=PedagogicalAction(turn.action.value) if turn.action else PedagogicalAction.PROBE,
        objective_id=turn.objective_id,
        objective_statement=target_statement,
        tutor_message=turn.tutor_message or "",
        student_message=turn.student_message or None,
        session_complete=db_session.status == SessionStatus.COMPLETED,
        objectives=objectives_out,
    )
    return {"result": result}
