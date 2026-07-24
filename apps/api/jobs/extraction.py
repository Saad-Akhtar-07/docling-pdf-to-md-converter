"""Background extraction job: an uploaded file becomes provenance-tagged
blocks in Postgres. Runs via FastAPI BackgroundTasks (see
apps/api/routers/documents.py). No LLM calls anywhere in this path —
packages/extraction is pure PyMuPDF4LLM + RapidOCR, per this module's scope.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from slidevision.extraction import config as extraction_config
from slidevision.extraction.office import convert_office_to_pdf
from slidevision.extraction.pipeline import extract_document
from slidevision.persistence.db import SessionLocal
from slidevision.persistence.enums import DocumentStatus, Provenance
from slidevision.persistence.repositories import DocumentRepository

logger = logging.getLogger(__name__)

POWERPOINT_SUFFIXES = {".ppt", ".pptx", ".odp"}


def run_extraction_job(document_id: uuid.UUID, saved_path: Path) -> None:
    """Runs (or retries) extraction for one document and persists its blocks.

    Each block is committed individually so a failure partway through
    leaves whatever was already extracted in place ("on failure: persist
    partial blocks, store per-stage error"). packages/extraction already
    tolerates a single bad slide internally (blocks.py catches per-slide OCR
    errors and just warns) — a Postgres write failing partway through the
    block list is the realistic way "partial" happens at this layer.
    """
    session = SessionLocal()
    repo = DocumentRepository(session)
    try:
        document = repo.get(document_id)
        if document is None:
            return  # deleted between being scheduled and running

        document.status = DocumentStatus.EXTRACTING
        document.error = None
        session.commit()

        pdf_path = saved_path
        if saved_path.suffix.lower() in POWERPOINT_SUFFIXES:
            pdf_path, _warnings = convert_office_to_pdf(saved_path, saved_path.parent)

        result = extract_document(
            pdf_path,
            document_name=saved_path.name,
            images_scale=extraction_config.DEFAULT_IMAGES_SCALE,
            ocr_language=extraction_config.DEFAULT_OCR_LANGUAGE,
            force_ocr=extraction_config.FORCE_OCR_RETRY,
            document_id=str(document_id),
        )

        repo.delete_blocks(document_id)  # clear any rows left by a prior failed attempt
        session.commit()

        persisted = 0
        for block in result["blocks"]:
            repo.add_block(
                block_id=block["block_id"],
                document_id=document_id,
                slide_no=block["slide_no"],
                order_index=block["order_index"],
                text=block["text"],
                provenance=Provenance(block["provenance"]),
                ocr_confidence=block.get("ocr_confidence"),
                producer=block.get("producer"),
                bbox=block.get("bbox"),
            )
            session.commit()
            persisted += 1

        document.status = DocumentStatus.READY
        session.commit()
        logger.info(
            "document %s extracted: %d/%d blocks persisted", document_id, persisted, len(result["blocks"])
        )

    except Exception as exc:
        session.rollback()
        document = repo.get(document_id)
        if document is not None:
            document.status = DocumentStatus.FAILED
            document.error = str(exc)[:2000]
            session.commit()
        logger.exception("extraction failed for document %s", document_id)
    finally:
        session.close()
