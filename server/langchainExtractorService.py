import base64
import hashlib
import math
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

import fitz
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI(title="SlideVision LangChain/PyMuPDF Extractor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


MAX_RENDER_SCALE = float(os.getenv("LANGCHAIN_EXTRACTOR_MAX_IMAGES_SCALE", "3"))
DEFAULT_TABLE_STRATEGY = os.getenv("LANGCHAIN_EXTRACTOR_TABLE_STRATEGY", "lines")


def clamp_render_scale(value: float) -> float:
    if not math.isfinite(value) or value <= 0:
        return 2
    return min(value, MAX_RENDER_SCALE)


def bbox_from_rect(rect: Any) -> dict[str, Any] | None:
    if not rect:
        return None

    x0, y0, x1, y1 = [float(value) for value in rect]
    if x1 <= x0 or y1 <= y0:
        return None

    return {
        "l": x0,
        "r": x1,
        "t": y0,
        "b": y1,
        "coordOrigin": "TOPLEFT",
    }


def area_ratio(bbox: dict[str, Any], page_width: float, page_height: float) -> float:
    width = abs(float(bbox["r"]) - float(bbox["l"]))
    height = abs(float(bbox["b"]) - float(bbox["t"]))
    page_area = page_width * page_height
    if page_area <= 0:
        return 0
    return (width * height) / page_area


def is_page_sized_bbox(bbox: dict[str, Any], page_width: float, page_height: float) -> bool:
    ratio = area_ratio(bbox, page_width, page_height)
    left = min(float(bbox["l"]), float(bbox["r"]))
    right = max(float(bbox["l"]), float(bbox["r"]))
    top = min(float(bbox["t"]), float(bbox["b"]))
    bottom = max(float(bbox["t"]), float(bbox["b"]))
    edge_tolerance = max(page_width, page_height) * 0.04

    touches_page_edges = (
        left <= edge_tolerance
        and top <= edge_tolerance
        and right >= page_width - edge_tolerance
        and bottom >= page_height - edge_tolerance
    )

    return ratio >= 0.82 or (ratio >= 0.65 and touches_page_edges)


def union_bboxes(bboxes: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not bboxes:
        return None

    return {
        "l": min(float(box["l"]) for box in bboxes),
        "r": max(float(box["r"]) for box in bboxes),
        "t": min(float(box["t"]) for box in bboxes),
        "b": max(float(box["b"]) for box in bboxes),
        "coordOrigin": "TOPLEFT",
    }


def bboxes_are_near(left: dict[str, Any], right: dict[str, Any], gap: float) -> bool:
    left_l = min(float(left["l"]), float(left["r"])) - gap
    left_r = max(float(left["l"]), float(left["r"])) + gap
    left_t = min(float(left["t"]), float(left["b"])) - gap
    left_b = max(float(left["t"]), float(left["b"])) + gap
    right_l = min(float(right["l"]), float(right["r"]))
    right_r = max(float(right["l"]), float(right["r"]))
    right_t = min(float(right["t"]), float(right["b"]))
    right_b = max(float(right["t"]), float(right["b"]))

    return not (left_r < right_l or right_r < left_l or left_b < right_t or right_b < left_t)


def cluster_bboxes(bboxes: list[dict[str, Any]], gap: float) -> list[dict[str, Any]]:
    clusters: list[list[dict[str, Any]]] = []

    for bbox in bboxes:
        matching_indexes = [
            index
            for index, cluster in enumerate(clusters)
            if any(bboxes_are_near(bbox, existing_bbox, gap) for existing_bbox in cluster)
        ]

        if not matching_indexes:
            clusters.append([bbox])
            continue

        first_index = matching_indexes[0]
        clusters[first_index].append(bbox)

        for merge_index in reversed(matching_indexes[1:]):
            clusters[first_index].extend(clusters.pop(merge_index))

    return [cluster for cluster in (union_bboxes(cluster) for cluster in clusters) if cluster]


def get_block_text(block: dict[str, Any]) -> str:
    lines = []
    for line in block.get("lines", []):
        spans = line.get("spans", [])
        text = "".join(str(span.get("text", "")) for span in spans).strip()
        if text:
            lines.append(text)
    return "\n".join(lines).strip()


def extract_page_areas(page: fitz.Page) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    text_areas = []
    picture_areas = []
    page_width = float(page.rect.width)
    page_height = float(page.rect.height)

    page_dict = page.get_text("dict")
    for block_index, block in enumerate(page_dict.get("blocks", [])):
        bbox = bbox_from_rect(block.get("bbox"))
        if not bbox:
            continue

        block_type = block.get("type")
        if block_type == 0:
            text = get_block_text(block)
            if text:
                text_areas.append(
                    {
                        "bbox": bbox,
                        "text": text[:500],
                        "sourcePath": f"pymupdf.page[{page.number + 1}].blocks[{block_index}]",
                    }
                )
        elif (
            block_type == 1
            and area_ratio(bbox, page_width, page_height) >= 0.01
            and not is_page_sized_bbox(bbox, page_width, page_height)
        ):
            picture_areas.append(
                {
                    "bbox": bbox,
                    "label": "image",
                    "sourcePath": f"pymupdf.page[{page.number + 1}].blocks[{block_index}]",
                }
            )

    drawing_bboxes = []
    for drawing_index, drawing in enumerate(page.get_drawings()):
        bbox = bbox_from_rect(drawing.get("rect"))
        if not bbox:
            continue
        if (
            area_ratio(bbox, page_width, page_height) >= 0.0005
            and not is_page_sized_bbox(bbox, page_width, page_height)
        ):
            drawing_bboxes.append(bbox)

    for cluster_index, drawing_cluster in enumerate(cluster_bboxes(drawing_bboxes, gap=12)):
        if (
            area_ratio(drawing_cluster, page_width, page_height) < 0.03
            or is_page_sized_bbox(drawing_cluster, page_width, page_height)
        ):
            continue

        picture_areas.append(
            {
                "bbox": drawing_cluster,
                "label": "drawing",
                "sourcePath": f"pymupdf.page[{page.number + 1}].drawingCluster[{cluster_index}]",
            }
        )

    return text_areas, picture_areas


def render_page_data_uri(page: fitz.Page, images_scale: float) -> tuple[str, str, int]:
    matrix = fitz.Matrix(images_scale, images_scale)
    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
    image_bytes = pixmap.tobytes("png")
    encoded = base64.b64encode(image_bytes).decode("ascii")
    fingerprint = hashlib.sha256(image_bytes).hexdigest()[:16]
    return f"data:image/png;base64,{encoded}", fingerprint, len(image_bytes)


def load_pages_with_pymupdf4llm(pdf_path: str) -> tuple[list[dict[str, Any]], list[str]]:
    warnings = []

    try:
        from langchain_pymupdf4llm import PyMuPDF4LLMLoader
    except ImportError as exc:
        raise RuntimeError(
            "langchain-pymupdf4llm is not installed. Install requirements-langchain-extractor.txt."
        ) from exc

    try:
        loader = PyMuPDF4LLMLoader(
            pdf_path,
            mode="page",
            table_strategy=DEFAULT_TABLE_STRATEGY,
        )
    except TypeError:
        warnings.append("Installed PyMuPDF4LLMLoader does not accept table_strategy; using defaults.")
        loader = PyMuPDF4LLMLoader(pdf_path, mode="page")

    docs = loader.load()
    pages = []

    for index, doc in enumerate(docs):
        page_number = int(doc.metadata.get("page", index)) + 1
        content = str(doc.page_content or "").strip()
        pages.append(
            {
                "pageNo": page_number,
                "content": content,
                "metadata": dict(doc.metadata),
            }
        )

    return pages, warnings


def load_pages_with_native_pymupdf(document: fitz.Document) -> tuple[list[dict[str, Any]], list[str]]:
    pages = []

    for index, page in enumerate(document):
        text = page.get_text("text").strip()
        pages.append(
            {
                "pageNo": index + 1,
                "content": text,
                "metadata": {
                    "source": "pymupdf-native-fallback",
                    "page": index,
                    "total_pages": document.page_count,
                },
            }
        )

    return pages, ["PyMuPDF4LLM failed, so native PyMuPDF text extraction fallback was used."]


def count_markdown_tables(markdown: str) -> int:
    table_blocks = re.findall(r"(?m)(?:^\|.*\|\s*$\n?){2,}", markdown)
    return len(table_blocks)


def build_markdown_and_chunks(pages: list[dict[str, Any]], document_name: str) -> tuple[str, list[dict[str, Any]], int]:
    chunks = []
    sections = []
    table_count = 0

    for page in sorted(pages, key=lambda item: item["pageNo"]):
        page_no = page["pageNo"]
        content = str(page.get("content") or "").strip()
        table_count += count_markdown_tables(content)
        sections.append(f"[Page {page_no}]\n\n{content}" if content else f"[Page {page_no}]")
        chunks.append(
            {
                "documentName": document_name,
                "pageNo": page_no,
                "type": "text",
                "content": content,
                "metadata": {
                    "label": "page",
                    "sourcePath": f"langchain_pymupdf4llm.page[{page_no}]",
                    "parserMetadata": page.get("metadata", {}),
                    "missingPageNo": False,
                },
            }
        )

    return "\n\n---\n\n".join(sections), chunks, table_count


def build_figures_from_images(images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    figures = []

    for image in images:
        if not image["pictureAreas"]:
            continue

        figures.append(
            {
                "id": f"pymupdf-page-{image['pageNumber']}-visual",
                "pageNumber": image["pageNumber"],
                "caption": "PyMuPDF visual region candidate",
                "reference": image["sourcePath"],
                "type": "page-visual",
                "raw": {
                    "pictureAreaCount": len(image["pictureAreas"]),
                    "sourcePath": image["sourcePath"],
                },
            }
        )

    return figures


def extract_pdf(pdf_path: str, document_name: str, images_scale: float) -> dict[str, Any]:
    started_at = time.perf_counter()
    warnings = ["OCR is disabled for this experimental LangChain/PyMuPDF pipeline."]

    document = fitz.open(pdf_path)

    try:
        try:
            pages, loader_warnings = load_pages_with_pymupdf4llm(pdf_path)
            warnings.extend(loader_warnings)
            source_path = "langchain_pymupdf4llm"
        except Exception as exc:
            pages, loader_warnings = load_pages_with_native_pymupdf(document)
            warnings.extend(loader_warnings)
            warnings.append(str(exc))
            source_path = "pymupdf-native-fallback"

        markdown, chunks, table_count = build_markdown_and_chunks(pages, document_name)
        images = []
        scale = clamp_render_scale(images_scale)

        for page in document:
            text_areas, picture_areas = extract_page_areas(page)
            source, fingerprint, byte_estimate = render_page_data_uri(page, scale)
            page_number = page.number + 1
            images.append(
                {
                    "id": f"pymupdf-page-{page_number}",
                    "pageNumber": page_number,
                    "caption": f"Rendered page {page_number}",
                    "source": source,
                    "sourcePath": f"pymupdf.page[{page_number}].render",
                    "fingerprint": fingerprint,
                    "reference": f"pymupdf-page-{page_number}",
                    "pageSize": {
                        "width": float(page.rect.width),
                        "height": float(page.rect.height),
                    },
                    "textAreas": text_areas,
                    "pictureAreas": picture_areas,
                    "byteEstimate": byte_estimate,
                }
            )

        return {
            "provider": "langchain-pymupdf4llm",
            "sourcePath": source_path,
            "markdown": markdown,
            "chunks": chunks,
            "figures": build_figures_from_images(images),
            "embeddedImages": images,
            "tableCount": table_count,
            "warnings": warnings,
            "metadata": {
                "pageCount": document.page_count,
                "imagesScale": scale,
                "elapsedMs": round((time.perf_counter() - started_at) * 1000),
            },
        }
    finally:
        document.close()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/convert/file")
async def convert_file(
    file: UploadFile = File(...),
    images_scale: float = Form(2),
) -> dict[str, Any]:
    filename = file.filename or "document.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF input is supported. Convert PPT/PPTX first.")

    suffix = Path(filename).suffix or ".pdf"
    temp_path = ""

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_path = temp_file.name
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                temp_file.write(chunk)

        return extract_pdf(temp_path, filename, images_scale)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        try:
            os.remove(temp_path)
        except Exception:
            pass
