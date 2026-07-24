"""Response models for apps/api. This is also what openapi-typescript reads
(via apps/api/export_openapi.py) to generate apps/web's typed API client —
apps/web must never hand-write these shapes.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from slidevision.persistence.enums import DocumentStatus, Provenance


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
