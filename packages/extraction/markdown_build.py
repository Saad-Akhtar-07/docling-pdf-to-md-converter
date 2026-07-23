import math
import re
from pathlib import Path
from typing import Any

import pymupdf4llm

from . import config
from .ocr import rapidocr_function


def count_markdown_tables(markdown: str) -> int:
    table_blocks = re.findall(r"(?m)(?:^\|.*\|\s*$\n?){2,}", markdown)
    return len(table_blocks)


def normalize_page_chunks(page_chunks: Any) -> list[dict[str, Any]]:
    if isinstance(page_chunks, list):
        return page_chunks
    if isinstance(page_chunks, str):
        return [
            {
                "metadata": {
                    "page_number": 1,
                    "page_count": 1,
                },
                "text": page_chunks,
                "page_boxes": [],
            }
        ]
    return []


def build_markdown_and_chunks(page_chunks: list[dict[str, Any]], document_name: str) -> tuple[str, list[dict[str, Any]], int]:
    chunks = []
    sections = []
    table_count = 0

    for index, page_chunk in enumerate(page_chunks):
        metadata = page_chunk.get("metadata") or {}
        page_number = int(metadata.get("page_number") or index + 1)
        content = str(page_chunk.get("text") or "").strip()
        table_count += count_markdown_tables(content)

        sections.append(f"[Page {page_number}]\n\n{content}" if content else f"[Page {page_number}]")
        chunks.append(
            {
                "documentName": document_name,
                "pageNo": page_number,
                "type": "text",
                "content": content,
                "metadata": {
                    "label": "page",
                    "sourcePath": f"local_pymupdf4llm.page[{page_number}]",
                    "parserMetadata": metadata,
                    "pageBoxes": page_chunk.get("page_boxes") or [],
                    "missingPageNo": False,
                },
            }
        )

    return "\n\n---\n\n".join(sections), chunks, table_count


def needs_force_ocr_retry(chunks: list[dict[str, Any]]) -> bool:
    if not config.FORCE_OCR_RETRY or not chunks:
        return False

    blank_pages = sum(1 for chunk in chunks if len(str(chunk.get("text") or "").strip()) < 10)
    return blank_pages > 0 and blank_pages >= math.ceil(len(chunks) * 0.35)


def run_pymupdf4llm(
    pdf_path: Path,
    document_name: str,
    ocr_language: str,
    force_ocr: bool,
    warnings: list[str],
) -> tuple[str, list[dict[str, Any]], int, list[dict[str, Any]]]:
    ocr_function = rapidocr_function(warnings)
    use_ocr = callable(ocr_function)

    page_chunks = normalize_page_chunks(
        pymupdf4llm.to_markdown(
            str(pdf_path),
            page_chunks=True,
            embed_images=False,
            write_images=False,
            header=False,
            footer=False,
            use_ocr=use_ocr,
            force_ocr=force_ocr and use_ocr,
            ocr_language=ocr_language,
            ocr_function=ocr_function,
        )
    )

    if use_ocr and not force_ocr and needs_force_ocr_retry(page_chunks):
        warnings.append("Several pages had little text, so extraction was retried with RapidOCR forced.")
        page_chunks = normalize_page_chunks(
            pymupdf4llm.to_markdown(
                str(pdf_path),
                page_chunks=True,
                embed_images=False,
                write_images=False,
                header=False,
                footer=False,
                use_ocr=True,
                force_ocr=True,
                ocr_language=ocr_language,
                ocr_function=ocr_function,
            )
        )

    markdown, chunks, table_count = build_markdown_and_chunks(page_chunks, document_name)
    return markdown, chunks, table_count, page_chunks
