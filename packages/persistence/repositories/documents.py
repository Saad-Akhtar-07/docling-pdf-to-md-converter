"""Repository for the documents aggregate (documents, document_blocks).

CRUD only — no validation, no extraction logic, no business rules. Those
belong to whichever module actually drives document upload/extraction.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from slidevision.persistence.enums import DocumentStatus, Provenance
from slidevision.persistence.models import Document, DocumentBlock


class DocumentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        title: str,
        source_filename: str,
        mime: str,
        content_hash: str,
        storage_uri: str,
        id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        status: DocumentStatus = DocumentStatus.UPLOADED,
    ) -> Document:
        document = Document(
            title=title,
            source_filename=source_filename,
            mime=mime,
            content_hash=content_hash,
            storage_uri=storage_uri,
            user_id=user_id,
            status=status,
        )
        if id is not None:
            document.id = id
        self.session.add(document)
        self.session.flush()
        return document

    def get(self, document_id: uuid.UUID) -> Document | None:
        return self.session.get(Document, document_id)

    def get_by_content_hash(self, content_hash: str) -> Document | None:
        stmt = select(Document).where(Document.content_hash == content_hash)
        return self.session.scalars(stmt).first()

    def list(self) -> list[Document]:
        return list(self.session.scalars(select(Document).order_by(Document.created_at)))

    def add_block(
        self,
        *,
        block_id: str,
        document_id: uuid.UUID,
        slide_no: int,
        order_index: int,
        text: str,
        provenance: Provenance,
        ocr_confidence: float | None = None,
        producer: str | None = None,
        bbox: list[float] | None = None,
    ) -> DocumentBlock:
        block = DocumentBlock(
            id=block_id,
            document_id=document_id,
            slide_no=slide_no,
            order_index=order_index,
            text=text,
            provenance=provenance,
            ocr_confidence=ocr_confidence,
            producer=producer,
            bbox=bbox,
        )
        self.session.add(block)
        self.session.flush()
        return block

    def get_blocks(self, document_id: uuid.UUID, slide_no: int | None = None) -> list[DocumentBlock]:
        stmt = select(DocumentBlock).where(DocumentBlock.document_id == document_id)
        if slide_no is not None:
            stmt = stmt.where(DocumentBlock.slide_no == slide_no)
        stmt = stmt.order_by(DocumentBlock.slide_no, DocumentBlock.order_index)
        return list(self.session.scalars(stmt))

    def delete_blocks(self, document_id: uuid.UUID) -> int:
        """Clears any blocks from a prior attempt before a (re-)extraction run."""
        deleted = (
            self.session.query(DocumentBlock).filter(DocumentBlock.document_id == document_id).delete()
        )
        self.session.flush()
        return deleted
