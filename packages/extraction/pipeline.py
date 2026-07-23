import time
from pathlib import Path
from typing import Any

from .blocks import build_document_blocks
from .geometry import build_figures_from_images, render_page_images
from .markdown_build import run_pymupdf4llm
from .utils import clamp_render_scale


def extract_document(
    input_path: Path,
    document_name: str,
    images_scale: float,
    ocr_language: str,
    force_ocr: bool,
    document_id: str,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    warnings: list[str] = []

    markdown, chunks, table_count, page_chunks = run_pymupdf4llm(
        input_path,
        document_name=document_name,
        ocr_language=ocr_language,
        force_ocr=force_ocr,
        warnings=warnings,
    )
    images = render_page_images(input_path, images_scale)
    blocks = build_document_blocks(
        input_path,
        document_id=document_id,
        force_ocr=force_ocr,
        warnings=warnings,
    )

    return {
        "provider": "local-pymupdf4llm-rapidocr",
        "sourcePath": "local_pymupdf4llm",
        "documentId": document_id,
        "markdown": markdown,
        "chunks": chunks,
        "blocks": [block.model_dump() for block in blocks],
        "figures": build_figures_from_images(images),
        "embeddedImages": images,
        "tableCount": table_count,
        "warnings": warnings,
        "metadata": {
            "pageCount": len(page_chunks),
            "imagesScale": clamp_render_scale(images_scale),
            "ocrEngine": "rapidocr",
            "ocrEnabled": not any("OCR was disabled" in warning for warning in warnings),
            "forceOcr": force_ocr,
            "elapsedMs": round((time.perf_counter() - started_at) * 1000),
        },
    }
