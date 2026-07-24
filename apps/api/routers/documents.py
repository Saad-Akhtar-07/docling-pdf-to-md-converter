"""POST /documents, GET /documents/{id}, GET /documents/{id}/blocks.

Single-user MVP: no authentication. Every uploaded document is attributed to
a fixed dev user id — see docs/BACKLOG.md.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from apps.api.deps import get_db
from apps.api.jobs.extraction import run_extraction_job
from apps.api.schemas import BlockOut, DocumentBlocksResponse, DocumentCreateResponse, DocumentOut
from apps.api.settings import get_settings
from slidevision.persistence.enums import DocumentStatus
from slidevision.persistence.repositories import DocumentRepository

router = APIRouter(prefix="/documents", tags=["documents"])

DEV_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

ALLOWED_SUFFIXES = {".pdf", ".ppt", ".pptx", ".odp"}


@router.post("", response_model=DocumentCreateResponse)
async def upload_document(
    response: Response,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> DocumentCreateResponse:
    filename = Path(file.filename or "").name
    suffix = Path(filename).suffix.lower()
    if not filename or suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF, PPT, PPTX, or ODP files are supported.",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")

    content_hash = hashlib.sha256(content).hexdigest()
    repo = DocumentRepository(db)
    existing = repo.get_by_content_hash(content_hash)

    # Idempotent re-upload, keyed on content: identical bytes always resolve
    # to the same document_id. A healthy or in-flight match is a no-op (we
    # already have, or are already producing, this document's blocks — 200,
    # nothing new scheduled). A FAILED match is instead treated as a retry,
    # since re-uploading a file that previously failed is exactly what a
    # user does to ask "try again" — 202, extraction is (re-)scheduled. See
    # docs/BACKLOG.md for the full rationale.
    if existing is not None and existing.status != DocumentStatus.FAILED:
        response.status_code = status.HTTP_200_OK
        return DocumentCreateResponse(document_id=existing.id, status=existing.status)

    settings = get_settings()
    document_id = existing.id if existing is not None else uuid.uuid4()

    upload_path = settings.upload_dir / str(document_id) / filename
    upload_path.parent.mkdir(parents=True, exist_ok=True)
    upload_path.write_bytes(content)

    if existing is not None:
        document = existing
        document.status = DocumentStatus.UPLOADED
        document.error = None
        document.storage_uri = upload_path.as_posix()
        db.commit()
    else:
        document = repo.create(
            id=document_id,
            title=filename,
            source_filename=filename,
            mime=file.content_type or "application/octet-stream",
            content_hash=content_hash,
            storage_uri=upload_path.as_posix(),
            user_id=DEV_USER_ID,
        )
        db.commit()

    background_tasks.add_task(run_extraction_job, document.id, upload_path)

    response.status_code = status.HTTP_202_ACCEPTED
    return DocumentCreateResponse(document_id=document.id, status=document.status)


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: uuid.UUID, db: Session = Depends(get_db)) -> DocumentOut:
    repo = DocumentRepository(db)
    document = repo.get(document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return DocumentOut.model_validate(document)


@router.get("/{document_id}/blocks", response_model=DocumentBlocksResponse)
def get_document_blocks(
    document_id: uuid.UUID,
    slide: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
) -> DocumentBlocksResponse:
    repo = DocumentRepository(db)
    document = repo.get(document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    blocks = repo.get_blocks(document_id, slide_no=slide)
    return DocumentBlocksResponse(
        document_id=document_id,
        slide=slide,
        blocks=[BlockOut.model_validate(block) for block in blocks],
    )
