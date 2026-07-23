import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pymupdf

from .models import Block
from .ocr import get_modern_rapidocr_engine

MIN_LEGIBLE_TEXT_CHARS = 10


def make_block_id(document_id: str, slide_no: int, order_index: int) -> str:
    """Deterministic block id: same (document content, slide, position) in ->
    same id out, on every re-run of extraction on the same file."""
    digest = hashlib.sha256(f"{document_id}:{slide_no}:{order_index}".encode("utf-8")).hexdigest()
    return f"b_{digest[:16]}"


def normalize_bbox(rect: pymupdf.Rect, page_width: float, page_height: float) -> list[float] | None:
    if page_width <= 0 or page_height <= 0 or rect.is_empty:
        return None
    return [
        round(rect.x0 / page_width, 6),
        round(rect.y0 / page_height, 6),
        round(rect.x1 / page_width, 6),
        round(rect.y1 / page_height, 6),
    ]


def page_has_legible_text(page: pymupdf.Page) -> bool:
    return len(page.get_text("text").strip()) >= MIN_LEGIBLE_TEXT_CHARS


def _extract_verbatim_blocks(
    page: pymupdf.Page,
    slide_no: int,
    document_id: str,
    order_start: int,
) -> tuple[list[Block], int]:
    """One Block per PyMuPDF text block (its own paragraph/line grouping),
    lines joined with '\\n'. Only non-empty blocks are kept."""
    page_width = float(page.rect.width)
    page_height = float(page.rect.height)
    text_dict = page.get_text("dict", flags=pymupdf.TEXT_ACCURATE_BBOXES)

    blocks: list[Block] = []
    order_index = order_start

    for raw_block in text_dict.get("blocks", []):
        if raw_block.get("type") != 0:
            continue

        line_texts = []
        for line in raw_block.get("lines", []):
            line_text = "".join(str(span.get("text", "")) for span in line.get("spans", []))
            if line_text:
                line_texts.append(line_text)

        text = "\n".join(line_texts)
        if not text.strip():
            continue

        bbox = normalize_bbox(pymupdf.Rect(raw_block["bbox"]), page_width, page_height)
        blocks.append(
            Block(
                block_id=make_block_id(document_id, slide_no, order_index),
                document_id=document_id,
                slide_no=slide_no,
                order_index=order_index,
                text=text,
                provenance="verbatim",
                ocr_confidence=None,
                producer=None,
                bbox=bbox,
            )
        )
        order_index += 1

    return blocks, order_index


def _extract_ocr_blocks(
    page: pymupdf.Page,
    slide_no: int,
    document_id: str,
    order_start: int,
    dpi: int = 300,
) -> tuple[list[Block], int]:
    """Runs RapidOCR directly on the full page pixmap and returns one Block
    per recognized text region, each carrying its own confidence score.

    Scope: this targets pages with no legible text layer at all (scanned
    slides). Mixed pages — some real text plus an illegible embedded image —
    still only produce verbatim blocks for the legible spans; OCR-ing just
    the illegible remainder of a mixed page is deferred (see BACKLOG.md).
    """
    pixmap = page.get_pixmap(dpi=dpi)
    image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, pixmap.n)
    matrix = pymupdf.Rect(pixmap.irect).torect(page.rect)
    result = get_modern_rapidocr_engine()(image)

    blocks: list[Block] = []
    order_index = order_start

    if result.boxes is None or result.txts is None:
        return blocks, order_index

    scores = result.scores if result.scores is not None else [None] * len(result.txts)
    page_width = float(page.rect.width)
    page_height = float(page.rect.height)

    for box, text, score in zip(result.boxes, result.txts, scores):
        text = str(text or "").strip()
        if not text:
            continue

        top_left, _top_right, bottom_right, _bottom_left = box
        rect = pymupdf.Rect(
            float(top_left[0]),
            float(top_left[1]),
            float(bottom_right[0]),
            float(bottom_right[1]),
        ) * matrix

        if rect.is_empty or rect.height <= 0:
            continue

        blocks.append(
            Block(
                block_id=make_block_id(document_id, slide_no, order_index),
                document_id=document_id,
                slide_no=slide_no,
                order_index=order_index,
                text=text,
                provenance="ocr",
                ocr_confidence=float(score) if score is not None else None,
                producer=None,
                bbox=normalize_bbox(rect, page_width, page_height),
            )
        )
        order_index += 1

    return blocks, order_index


def build_document_blocks(
    pdf_path: Path,
    document_id: str,
    force_ocr: bool,
    warnings: list[str],
) -> list[Block]:
    """Builds the provenance-tagged block list for every page of pdf_path.

    document_id must be a hash of the ORIGINAL uploaded file (not of a
    LibreOffice-converted intermediate PDF, which embeds a fresh timestamp on
    every conversion and so is not stable across re-runs).
    """
    all_blocks: list[Block] = []

    with pymupdf.open(pdf_path) as document:
        for page in document:
            slide_no = page.number + 1
            order_index = 0

            verbatim_blocks, order_index = _extract_verbatim_blocks(page, slide_no, document_id, order_index)
            all_blocks.extend(verbatim_blocks)

            if force_ocr or not page_has_legible_text(page):
                try:
                    ocr_blocks, order_index = _extract_ocr_blocks(page, slide_no, document_id, order_index)
                    all_blocks.extend(ocr_blocks)
                except Exception as exc:
                    warnings.append(f"OCR block extraction failed on slide {slide_no}: {exc}")

    return all_blocks


def block_from_visual_description(
    description: dict[str, Any],
    document_id: str,
    slide_no: int,
    order_index: int,
) -> Block | None:
    """Converts one vision-model description (see vision.py) into a
    model_generated Block. Returns None for error results or empty output —
    those carry no citable content."""
    if description.get("error"):
        return None

    text = str(description.get("markdownBlock") or "").strip()
    if not text:
        return None

    return Block(
        block_id=make_block_id(document_id, slide_no, order_index),
        document_id=document_id,
        slide_no=slide_no,
        order_index=order_index,
        text=text,
        provenance="model_generated",
        ocr_confidence=None,
        producer=str(description.get("model") or "unknown"),
        bbox=None,
    )
