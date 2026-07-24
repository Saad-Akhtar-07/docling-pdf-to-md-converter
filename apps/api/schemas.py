"""Response models for apps/api. This is also what openapi-typescript reads
(via apps/api/export_openapi.py) to generate apps/web's typed API client —
apps/web must never hand-write these shapes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from slidevision.persistence.enums import DocumentStatus, PlanEditAction, PlanStatus, Provenance


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
