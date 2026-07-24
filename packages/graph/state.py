"""LangGraph state for Module 4's turn skeleton
(docs/ARCHITECTURE_REVIEW_AND_ROADMAP.md §2.7, nodes 1, 7(stub), 8, 9, 10).

A TypedDict, not a Pydantic model: it carries a live SQLAlchemy `Session`
(`db`) between nodes, and this graph is built with no checkpointer
(CLAUDE.md invariant #3) -- nothing here is ever serialized or resumed from
a saved state, so there is no benefit to validating it on every node
transition, only cost.
"""

from __future__ import annotations

import uuid
from typing import TypedDict

from sqlalchemy.orm import Session as DbSession

from slidevision.graph.result import TutorTurn
from slidevision.tutor_core import ConsistencyRepair, EvidenceCard, ObjectiveAssessment, ObjectiveState, PedagogicalAction


class OrderedObjective(TypedDict):
    objective_id: uuid.UUID
    statement: str


class TurnState(TypedDict, total=False):
    # --- input (run_turn) ---
    db: DbSession
    session_id: uuid.UUID
    message: str | None
    idempotency_key: str

    # --- load_state ---
    is_duplicate: bool
    existing_turn_id: uuid.UUID | None
    plan_id: uuid.UUID
    document_id: uuid.UUID
    turn_index: int
    current_objective_id: uuid.UUID | None
    objectives: list[OrderedObjective]  # plan (curriculum) order
    objective_states: dict[str, ObjectiveState]  # keyed by str(objective_id)
    node_start_perf: float  # time.perf_counter() at load_state, for latency_ms

    # --- assess_response (node 4) / consistency_check (node 5) ---
    raw_assessment: ObjectiveAssessment | None  # pre-repair, straight from the LLM (or the safe default)
    evidence_card: EvidenceCard | None
    assessed_objective_id: uuid.UUID | None
    assessment_used_safe_default: bool
    assessment: ObjectiveAssessment | None  # post-repair; None whenever there was no answer to assess
    assessment_repairs: list[ConsistencyRepair]

    # --- select_action (stub) ---
    action: PedagogicalAction
    target_objective_id: uuid.UUID | None
    updated_objective_states: dict[str, ObjectiveState]
    session_complete: bool

    # --- retrieve_grounding ---
    target_statement: str | None

    # --- generate_turn ---
    tutor_message: str

    # --- persist_turn / return_existing ---
    result: TutorTurn
