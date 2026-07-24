"""Response models for apps/api. This is also what openapi-typescript reads
(via apps/api/export_openapi.py) to generate apps/web's typed API client —
apps/web must never hand-write these shapes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from slidevision.persistence.enums import (
    DocumentStatus,
    ObjectiveStatus,
    PedagogicalAction,
    PlanEditAction,
    PlanStatus,
    Provenance,
    SessionStatus,
)


class DocumentCreateResponse(BaseModel):
    document_id: uuid.UUID
    status: DocumentStatus


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    source_filename: str
    mime: str
    status: DocumentStatus
    error: str | None
    created_at: datetime


class BlockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: uuid.UUID
    slide_no: int
    order_index: int
    text: str
    provenance: Provenance
    ocr_confidence: float | None
    producer: str | None
    bbox: list[float] | None


class DocumentBlocksResponse(BaseModel):
    document_id: uuid.UUID
    slide: int | None
    blocks: list[BlockOut]


class ExpectedIdeaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    idea: str
    block_id: str
    char_start: int
    char_end: int


class MisconceptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    text: str


class ObjectiveOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    statement: str
    order_index: int
    low_confidence: bool
    reviewed: bool
    expected_ideas: list[ExpectedIdeaOut]
    misconceptions: list[MisconceptionOut]


class ExpectedIdeaIn(BaseModel):
    """`id` present + matching an existing row -> edit in place (this is how
    manual re-anchoring changes block_id/char_start/char_end); `id` absent ->
    insert a new idea. Any existing idea whose id isn't included in the
    PATCH's `expected_ideas` list is deleted -- see
    PlanRepository.replace_expected_ideas."""

    id: uuid.UUID | None = None
    idea: str
    block_id: str
    char_start: int
    char_end: int


class ObjectivePatch(BaseModel):
    statement: str | None = None
    reviewed: bool | None = None
    expected_ideas: list[ExpectedIdeaIn] | None = None


class UnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    order_index: int
    summary: str | None
    slide_ids: list[int]
    objectives: list[ObjectiveOut]


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    version: int
    status: PlanStatus
    builder_prompt_version: str | None
    model: str | None
    created_at: datetime
    units: list[UnitOut]


class PlanBuildResponse(BaseModel):
    job_id: uuid.UUID
    plan_id: uuid.UUID
    status: PlanStatus


class PlanEditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_id: uuid.UUID
    objective_id: uuid.UUID | None
    action: PlanEditAction
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    created_at: datetime


# --- Module 4: session runtime skeleton (docs/…§2.11) -----------------------


class ProgressOut(BaseModel):
    resolved: int
    deferred: int
    total: int


class ObjectiveProgressOut(BaseModel):
    objective_id: uuid.UUID
    statement: str
    status: ObjectiveStatus


class SessionCreateRequest(BaseModel):
    document_id: uuid.UUID
    plan_id: uuid.UUID


class TurnOut(BaseModel):
    turn_id: uuid.UUID
    turn_index: int
    session_id: uuid.UUID
    action: PedagogicalAction
    objective_id: uuid.UUID | None
    objective_statement: str | None
    tutor_message: str
    student_message: str | None
    session_complete: bool
    progress: ProgressOut


class SessionOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    plan_id: uuid.UUID
    status: SessionStatus
    current_objective_id: uuid.UUID | None
    turn_count: int
    started_at: datetime
    ended_at: datetime | None
    progress: ProgressOut
    objectives: list[ObjectiveProgressOut]


class SessionCreateResponse(BaseModel):
    session: SessionOut
    turn: TurnOut


class TurnRequest(BaseModel):
    message: str
    idempotency_key: str


class TurnHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    index: int
    student_message: str
    action: PedagogicalAction | None
    tutor_message: str | None
    objective_id: uuid.UUID | None
    created_at: datetime
