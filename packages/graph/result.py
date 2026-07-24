"""Client-facing turn result -- what run_turn() returns and what
apps/api/routers/sessions.py serializes into HTTP responses."""

from __future__ import annotations

import uuid

from pydantic import BaseModel

from slidevision.tutor_core import ObjectiveStatus, PedagogicalAction


class ObjectiveProgress(BaseModel):
    objective_id: uuid.UUID
    statement: str
    status: ObjectiveStatus


class TutorTurn(BaseModel):
    turn_id: uuid.UUID
    turn_index: int
    session_id: uuid.UUID
    action: PedagogicalAction
    objective_id: uuid.UUID | None
    objective_statement: str | None
    tutor_message: str
    student_message: str | None
    session_complete: bool
    objectives: list[ObjectiveProgress]  # full plan-order progress, for the progress rail
