import base64
import hashlib
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import pymupdf
import pymupdf4llm
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI(title="SlideVision Local Extractor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


DEFAULT_IMAGES_SCALE = float(os.getenv("LOCAL_EXTRACTOR_IMAGES_SCALE", "2"))
MAX_RENDER_SCALE = float(os.getenv("LOCAL_EXTRACTOR_MAX_IMAGES_SCALE", "3"))
DEFAULT_OCR_LANGUAGE = os.getenv("LOCAL_EXTRACTOR_OCR_LANGUAGE", "eng")
SOFFICE_TIMEOUT_SECONDS = int(os.getenv("LOCAL_EXTRACTOR_SOFFICE_TIMEOUT_SECONDS", "180"))
FORCE_OCR_RETRY = os.getenv("LOCAL_EXTRACTOR_FORCE_OCR_RETRY", "true").lower() != "false"
LIBREOFFICE_LISTENER_PORT = int(os.getenv("LOCAL_EXTRACTOR_LIBREOFFICE_PORT", "2002"))
LIBREOFFICE_PROFILE_DIR = Path(
    os.getenv("LOCAL_EXTRACTOR_LIBREOFFICE_PROFILE", tempfile.gettempdir())
) / "slidevision-libreoffice-profile"

LIBREOFFICE_PROCESS: subprocess.Popen | None = None
RAPID_OCR_ENGINE: Any | None = None
OCR_FONT = pymupdf.Font("cjk")
OCR_FONTNAME = "slidevision_ocr_font"
REPLACEMENT_UNICODE = chr(0xFFFD)


def clamp_render_scale(value: float) -> float:
    if not math.isfinite(value) or value <= 0:
        return DEFAULT_IMAGES_SCALE
    return min(value, MAX_RENDER_SCALE)


def get_no_window_flag() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def find_libreoffice() -> str:
    configured_path = os.getenv("LIBREOFFICE_PATH") or os.getenv("SOFFICE_PATH")
    candidates = [
        configured_path,
        shutil.which("soffice.com"),
        shutil.which("soffice"),
        shutil.which("libreoffice"),
        r"C:\Program Files\LibreOffice\program\soffice.com",
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.com",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]

    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(Path(candidate))

    return ""


def libreoffice_profile_arg() -> str:
    LIBREOFFICE_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return f"-env:UserInstallation={LIBREOFFICE_PROFILE_DIR.as_uri()}"


def start_libreoffice_listener() -> tuple[bool, str]:
    global LIBREOFFICE_PROCESS

    soffice_path = find_libreoffice()
    if not soffice_path:
        return False, "LibreOffice CLI was not found."

    if LIBREOFFICE_PROCESS and LIBREOFFICE_PROCESS.poll() is None:
        return True, "LibreOffice listener is already running."

    accept_arg = (
        f"--accept=socket,host=127.0.0.1,port={LIBREOFFICE_LISTENER_PORT};"
        "urp;StarOffice.ComponentContext"
    )
    args = [
        soffice_path,
        "--headless",
        "--invisible",
        "--nologo",
        "--nodefault",
        "--nofirststartwizard",
        "--nolockcheck",
        libreoffice_profile_arg(),
        accept_arg,
    ]

    try:
        LIBREOFFICE_PROCESS = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=get_no_window_flag(),
        )
        return True, f"LibreOffice listener started on port {LIBREOFFICE_LISTENER_PORT}."
    except Exception as exc:
        LIBREOFFICE_PROCESS = None
        return False, f"LibreOffice listener could not start: {exc}"


def stop_libreoffice_listener() -> None:
    global LIBREOFFICE_PROCESS

    if not LIBREOFFICE_PROCESS or LIBREOFFICE_PROCESS.poll() is not None:
        LIBREOFFICE_PROCESS = None
        return

    LIBREOFFICE_PROCESS.terminate()
    try:
        LIBREOFFICE_PROCESS.wait(timeout=5)
    except subprocess.TimeoutExpired:
        LIBREOFFICE_PROCESS.kill()
    finally:
        LIBREOFFICE_PROCESS = None


def convert_office_to_pdf(input_path: Path, output_dir: Path) -> tuple[Path, list[str]]:
    warnings: list[str] = []
    soffice_path = find_libreoffice()

    if not soffice_path:
        raise RuntimeError(
            "LibreOffice CLI was not found. Install LibreOffice and make sure soffice is on PATH, "
            "or set LIBREOFFICE_PATH to soffice.com/soffice.exe."
        )

    listener_ok, listener_message = start_libreoffice_listener()
    warnings.append(listener_message)
    if not listener_ok:
        warnings.append("Continuing with one-shot LibreOffice conversion.")

    args = [
        soffice_path,
        "--headless",
        "--invisible",
        "--nologo",
        "--nodefault",
        "--nofirststartwizard",
        "--nolockcheck",
        libreoffice_profile_arg(),
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir),
        str(input_path),
    ]

    completed = subprocess.run(
        args,
        cwd=str(output_dir),
        capture_output=True,
        text=True,
        timeout=SOFFICE_TIMEOUT_SECONDS,
        creationflags=get_no_window_flag(),
        check=False,
    )

    expected_pdf = output_dir / f"{input_path.stem}.pdf"
    if not expected_pdf.exists():
        pdf_candidates = sorted(output_dir.glob("*.pdf"), key=lambda path: path.stat().st_mtime, reverse=True)
        expected_pdf = pdf_candidates[0] if pdf_candidates else expected_pdf

    if completed.returncode != 0 or not expected_pdf.exists():
        details = (completed.stderr or completed.stdout or "No LibreOffice output.").strip()
        raise RuntimeError(f"LibreOffice conversion failed: {details}")

    return expected_pdf, warnings


def span_has_ocr_text(span: dict[str, Any]) -> bool:
    return not (span["char_flags"] & 32) and not (span["char_flags"] & 16)


def get_modern_rapidocr_engine():
    global RAPID_OCR_ENGINE

    if RAPID_OCR_ENGINE is None:
        from rapidocr import RapidOCR

        RAPID_OCR_ENGINE = RapidOCR()
    return RAPID_OCR_ENGINE


def exec_modern_rapidocr(page, dpi=300, pixmap=None, language="eng", keep_ocr_text=False):
    def adjust_width(text: str, fontsize: float, rect: pymupdf.Rect) -> pymupdf.Matrix:
        text_length = OCR_FONT.text_length(text, fontsize)
        if text_length > 0:
            return pymupdf.Matrix(rect.width / text_length, 1)
        return pymupdf.Matrix(1, 1)

    import numpy as np

    text_blocks = page.get_text("dict", flags=pymupdf.TEXT_ACCURATE_BBOXES)["blocks"]
    spans = []
    replacement_spans = []

    for block in text_blocks:
        for line in block["lines"]:
            for span in line["spans"]:
                if span_has_ocr_text(span):
                    if keep_ocr_text:
                        spans.append(span["bbox"])
                    else:
                        replacement_spans.append(span["bbox"])
                    continue

                if REPLACEMENT_UNICODE in span["text"]:
                    replacement_spans.append(span["bbox"])
                else:
                    spans.append(span["bbox"])

    if spans:
        temp_pdf = pymupdf.open()
        temp_pdf.insert_pdf(page.parent, from_page=page.number, to_page=page.number)
        temp_page = temp_pdf[0]
        for span_bbox in spans:
            temp_page.add_redact_annot(span_bbox)
        temp_page.apply_redactions(
            images=pymupdf.PDF_REDACT_IMAGE_NONE,
            graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
            text=pymupdf.PDF_REDACT_TEXT_REMOVE,
        )
        pixmap = temp_page.get_pixmap(dpi=dpi)

    if pixmap is None:
        pixmap = page.get_pixmap(dpi=dpi)

    if replacement_spans:
        for span_bbox in replacement_spans:
            page.add_redact_annot(span_bbox)
        page.apply_redactions(
            images=pymupdf.PDF_REDACT_IMAGE_NONE,
            graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
            text=pymupdf.PDF_REDACT_TEXT_REMOVE,
        )

    image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, pixmap.n)
    matrix = pymupdf.Rect(pixmap.irect).torect(page.rect)
    result = get_modern_rapidocr_engine()(image)

    if result.boxes is None or result.txts is None:
        return

    page.insert_font(fontname=OCR_FONTNAME, fontbuffer=OCR_FONT.buffer)

    for box, text in zip(result.boxes, result.txts):
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

        fontsize = rect.height
        page.insert_text(
            rect.bl + (0, -0.2 * fontsize),
            text,
            fontsize=fontsize,
            fontname=OCR_FONTNAME,
            render_mode=0,
            morph=(rect.bl, adjust_width(text, fontsize, rect)),
        )


def rapidocr_function(warnings: list[str]):
    try:
        from pymupdf4llm.ocr.rapidocr_api import exec_ocr

        return exec_ocr
    except Exception:
        pass

    try:
        get_modern_rapidocr_engine()
        return exec_modern_rapidocr
    except Exception as exc:
        warnings.append(
            "RapidOCR is not available, so OCR was disabled. Install rapidocr and onnxruntime "
            f"for OCR support. Detail: {exc}"
        )
        return None


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


def extract_page_areas(page: pymupdf.Page) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
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
                        "sourcePath": f"local.page[{page.number + 1}].blocks[{block_index}]",
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
                    "sourcePath": f"local.page[{page.number + 1}].blocks[{block_index}]",
                }
            )

    drawing_bboxes = []
    for drawing in page.get_drawings():
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
                "sourcePath": f"local.page[{page.number + 1}].drawingCluster[{cluster_index}]",
            }
        )

    return text_areas, picture_areas


def render_page_data_uri(page: pymupdf.Page, images_scale: float) -> tuple[str, str, int]:
    matrix = pymupdf.Matrix(images_scale, images_scale)
    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
    image_bytes = pixmap.tobytes("png")
    encoded = base64.b64encode(image_bytes).decode("ascii")
    fingerprint = hashlib.sha256(image_bytes).hexdigest()[:16]
    return f"data:image/png;base64,{encoded}", fingerprint, len(image_bytes)


def render_page_images(pdf_path: Path, images_scale: float) -> list[dict[str, Any]]:
    images = []
    scale = clamp_render_scale(images_scale)

    with pymupdf.open(pdf_path) as document:
        for page in document:
            text_areas, picture_areas = extract_page_areas(page)
            source, fingerprint, byte_estimate = render_page_data_uri(page, scale)
            page_number = page.number + 1
            images.append(
                {
                    "id": f"local-page-{page_number}",
                    "pageNumber": page_number,
                    "caption": f"Rendered slide {page_number}",
                    "source": source,
                    "sourcePath": f"local.page[{page_number}].render",
                    "fingerprint": fingerprint,
                    "reference": f"local-page-{page_number}",
                    "pageSize": {
                        "width": float(page.rect.width),
                        "height": float(page.rect.height),
                    },
                    "textAreas": text_areas,
                    "pictureAreas": picture_areas,
                    "byteEstimate": byte_estimate,
                }
            )

    return images


def build_figures_from_images(images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    figures = []

    for image in images:
        if not image["pictureAreas"]:
            continue

        figures.append(
            {
                "id": f"local-page-{image['pageNumber']}-visual",
                "pageNumber": image["pageNumber"],
                "caption": "Large visual region candidate",
                "reference": image["sourcePath"],
                "type": "page-visual",
                "raw": {
                    "pictureAreaCount": len(image["pictureAreas"]),
                    "sourcePath": image["sourcePath"],
                },
            }
        )

    return figures


def needs_force_ocr_retry(chunks: list[dict[str, Any]]) -> bool:
    if not FORCE_OCR_RETRY or not chunks:
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


def extract_document(
    input_path: Path,
    document_name: str,
    images_scale: float,
    ocr_language: str,
    force_ocr: bool,
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

    return {
        "provider": "local-pymupdf4llm-rapidocr",
        "sourcePath": "local_pymupdf4llm",
        "markdown": markdown,
        "chunks": chunks,
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


@app.on_event("startup")
def startup() -> None:
    start_libreoffice_listener()


@app.on_event("shutdown")
def shutdown() -> None:
    stop_libreoffice_listener()


@app.get("/health")
def health() -> dict[str, Any]:
    rapidocr_package = ""
    try:
        import rapidocr_onnxruntime  # noqa: F401

        rapidocr_available = True
    except Exception:
        try:
            import rapidocr  # noqa: F401

            rapidocr_available = True
            rapidocr_package = "rapidocr"
        except Exception:
            rapidocr_available = False
    else:
        rapidocr_package = "rapidocr_onnxruntime"

    listener_running = bool(LIBREOFFICE_PROCESS and LIBREOFFICE_PROCESS.poll() is None)

    return {
        "status": "ok",
        "provider": "local-pymupdf4llm-rapidocr",
        "pymupdfVersion": pymupdf.__version__,
        "pymupdf4llmVersion": pymupdf4llm.__version__,
        "rapidOcrAvailable": rapidocr_available,
        "rapidOcrPackage": rapidocr_package,
        "libreOfficePath": find_libreoffice(),
        "libreOfficeListenerRunning": listener_running,
        "libreOfficePort": LIBREOFFICE_LISTENER_PORT,
    }


@app.post("/v1/convert/file")
async def convert_file(
    file: UploadFile = File(...),
    images_scale: float = Form(DEFAULT_IMAGES_SCALE),
    ocr_language: str = Form(DEFAULT_OCR_LANGUAGE),
    force_ocr: bool = Form(False),
) -> dict[str, Any]:
    filename = Path(file.filename or "document.pdf").name
    lower_name = filename.lower()
    is_pdf = lower_name.endswith(".pdf")
    is_powerpoint = lower_name.endswith((".ppt", ".pptx", ".odp"))

    if not is_pdf and not is_powerpoint:
        raise HTTPException(status_code=400, detail="Only PDF, PPT, PPTX, or ODP input is supported.")

    with tempfile.TemporaryDirectory(prefix="slidevision-local-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        input_path = temp_dir / filename

        try:
            with input_path.open("wb") as temp_file:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    temp_file.write(chunk)

            conversion_warnings: list[str] = []
            pdf_path = input_path
            if is_powerpoint:
                pdf_path, conversion_warnings = convert_office_to_pdf(input_path, temp_dir)

            response = extract_document(
                pdf_path,
                document_name=filename,
                images_scale=images_scale,
                ocr_language=ocr_language,
                force_ocr=force_ocr,
            )
            response["warnings"] = conversion_warnings + response["warnings"]
            if is_powerpoint:
                response["metadata"]["convertedFrom"] = filename
                response["metadata"]["convertedPdfName"] = pdf_path.name
            return response
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(status_code=504, detail=f"Local conversion timed out: {exc}") from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
