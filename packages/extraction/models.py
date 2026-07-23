from typing import Literal

from pydantic import BaseModel

Provenance = Literal["verbatim", "ocr", "model_generated"]


class Block(BaseModel):
    """One provenance-tagged unit of extracted content.

    `text` is stored exactly as it will be persisted: (block_id, char_start,
    char_end) anchors downstream must slice this exact string, so nothing
    upstream or downstream may re-normalise whitespace in it.
    """

    block_id: str
    document_id: str
    slide_no: int
    order_index: int
    text: str
    provenance: Provenance
    ocr_confidence: float | None = None
    producer: str | None = None
    bbox: list[float] | None = None
