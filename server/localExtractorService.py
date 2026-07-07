import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
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
SLIDEVISION_CACHE_PATH = Path(os.getenv("SLIDEVISION_CACHE_PATH", "data/slidevision-cache.sqlite"))
SLIDEVISION_CACHE_NAMESPACE = os.getenv("SLIDEVISION_CACHE_NAMESPACE", "default")
OPENCODE_API_URL = os.getenv("OPENCODE_API_URL", "https://opencode.ai/zen/go/v1/chat/completions")
OPENCODE_VISION_MODEL = os.getenv("OPENCODE_VISION_MODEL", "mimo-v2.5")
OPENCODE_VISION_TIMEOUT_MS = int(os.getenv("OPENCODE_VISION_TIMEOUT_MS", "90000"))
OPENCODE_VISION_MAX_TOKENS = int(os.getenv("OPENCODE_VISION_MAX_TOKENS", "1200"))
OPENCODE_VISION_TEMPERATURE = float(os.getenv("OPENCODE_VISION_TEMPERATURE", "0.2"))
OPENCODE_VISION_CONCURRENCY = int(os.getenv("OPENCODE_VISION_CONCURRENCY", "1"))
OPENCODE_VISION_PAGE_TEXT_CHARS = int(os.getenv("OPENCODE_VISION_PAGE_TEXT_CHARS", "1800"))
OPENCODE_VISION_MAX_IMAGE_BYTES = int(os.getenv("OPENCODE_VISION_MAX_IMAGE_BYTES", str(4 * 1024 * 1024)))
OPENCODE_VISION_PROMPT_VERSION = os.getenv("OPENCODE_VISION_PROMPT_VERSION", "v1")
OPENCODE_VISION_NODE_HELPER = Path(
    os.getenv("OPENCODE_VISION_NODE_HELPER", "server/opencodeVisionClient.mjs")
)

LIBREOFFICE_PROCESS: subprocess.Popen | None = None
RAPID_OCR_ENGINE: Any | None = None
OCR_FONT = pymupdf.Font("cjk")
OCR_FONTNAME = "slidevision_ocr_font"
REPLACEMENT_UNICODE = chr(0xFFFD)
VISUAL_DESCRIPTION_PROMPT_TEMPLATE = """
You are preparing lecture-slide content for a teaching tutor.

Return only valid JSON in English with these keys:
- visualType: one of "diagram", "chart", "table", "equation", "photo", "mixed", "layout", "none"
- visualDescription: 2-4 precise sentences describing only meaningful visual content, relationships, arrows, axes, equations, charts, diagrams, or images
- teachingExplanation: 2-4 sentences explaining how a teacher should explain the visual to students
- importantVisualElements: array of 3-8 short strings naming the key visual elements
- visibleTextNotInOcr: array of short strings for visible text, symbols, labels, or formulas missing from OCR, or []
- confidence: one of "low", "medium", "high"

Rules:
- Keep the JSON compact, under 350 words total.
- Do not repeat all OCR text.
- Do not invent details that are not visible.
- If the slide is mostly text with no meaningful visual, set visualType to "none" and keep the description short.
- Prefer clear teaching language over generic image captions.
""".strip()


def clamp_render_scale(value: float) -> float:
    if not math.isfinite(value) or value <= 0:
        return DEFAULT_IMAGES_SCALE
    return min(value, MAX_RENDER_SCALE)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def estimate_data_uri_bytes(source: str) -> int:
    if not source:
        return 0

    encoded = source.split(",", 1)[1] if "," in source else source
    return round((len(encoded.strip()) * 3) / 4)


def compact_page_text(page_text: str) -> str:
    return re.sub(r"\s+", " ", str(page_text or "")).strip()[:OPENCODE_VISION_PAGE_TEXT_CHARS]


def normalize_json_content(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def normalize_description_payload(payload: dict[str, Any], fallback_page_number: Any) -> dict[str, Any]:
    return {
        "pageNumber": payload.get("pageNumber") or fallback_page_number,
        "visualType": str(payload.get("visualType") or "mixed").strip(),
        "visualDescription": str(payload.get("visualDescription") or "").strip(),
        "teachingExplanation": str(payload.get("teachingExplanation") or "").strip(),
        "importantVisualElements": [
            str(item).strip() for item in payload.get("importantVisualElements", []) if str(item).strip()
        ]
        if isinstance(payload.get("importantVisualElements"), list)
        else [],
        "visibleTextNotInOcr": [
            str(item).strip() for item in payload.get("visibleTextNotInOcr", []) if str(item).strip()
        ]
        if isinstance(payload.get("visibleTextNotInOcr"), list)
        else [],
        "confidence": str(payload.get("confidence") or "medium").strip(),
    }


def format_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items if item)


def format_visual_markdown(description: dict[str, Any]) -> str:
    sections = ["### Visual Explanation"]

    if description.get("visualDescription"):
        sections.append(description["visualDescription"])

    if description.get("teachingExplanation"):
        sections.append(f"Teaching note:\n{description['teachingExplanation']}")

    if description.get("importantVisualElements"):
        sections.append(f"Important visual elements:\n{format_list(description['importantVisualElements'])}")

    if description.get("visibleTextNotInOcr"):
        sections.append(
            f"Visible text or symbols not captured by OCR:\n{format_list(description['visibleTextNotInOcr'])}"
        )

    return "\n\n".join(sections)


def prompt_hash(actual_prompt: str) -> str:
    """Hash the fully-constructed prompt (template + per-slide content) so any
    change in OCR text, metrics, or config produces a different cache key."""
    return sha256_text(f"{OPENCODE_VISION_PROMPT_VERSION}\n{actual_prompt}")


def create_visual_prompt(page_number: Any, page_text: str, metrics: dict[str, Any] | None) -> str:
    page_label = f"Page {page_number}" if page_number else "Unknown page"
    context_text = compact_page_text(page_text)
    metrics_text = ""

    if metrics:
        metrics_text = (
            "\nVisual detector metrics:"
            f"\n- pictureBoxCount: {metrics.get('pictureBoxCount')}"
            f"\n- pictureAreaRatio: {metrics.get('pictureAreaRatio')}"
            f"\n- residualRatio: {metrics.get('residualRatio')}"
            f"\n- edgeRatio: {metrics.get('edgeRatio')}"
        )

    return (
        f"{VISUAL_DESCRIPTION_PROMPT_TEMPLATE}\n\n"
        f"Slide: {page_label}\n"
        f"Existing OCR text from this slide:\n{context_text or '[No OCR text available]'}"
        f"{metrics_text}"
    )


def get_cache_connection() -> sqlite3.Connection:
    SLIDEVISION_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(SLIDEVISION_CACHE_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")

    # --- visual description cache (per slide image + prompt) ---
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS visual_descriptions (
            namespace_id TEXT NOT NULL,
            slide_hash TEXT NOT NULL,
            model_id TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            prompt_hash TEXT NOT NULL,
            text_hash TEXT NOT NULL,
            page_number TEXT,
            description_json TEXT NOT NULL,
            markdown_block TEXT NOT NULL,
            latency_ms INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (namespace_id, slide_hash, model_id, prompt_version, prompt_hash)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_visual_descriptions_slide_hash ON visual_descriptions(slide_hash)"
    )

    # --- document extraction cache (per file hash + settings) ---
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS document_extractions (
            file_hash TEXT NOT NULL,
            images_scale REAL NOT NULL,
            ocr_language TEXT NOT NULL,
            force_ocr INTEGER NOT NULL,
            file_name TEXT NOT NULL,
            page_count INTEGER NOT NULL,
            file_size_bytes INTEGER NOT NULL DEFAULT 0,
            markdown TEXT NOT NULL,
            chunks_json TEXT NOT NULL,
            warnings_json TEXT NOT NULL,
            table_count INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL,
            extraction_ms INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (file_hash, images_scale, ocr_language, force_ocr)
        )
        """
    )

    # --- document registry (deck_id concept for multi-user) ---
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            document_id TEXT PRIMARY KEY,
            file_name TEXT NOT NULL,
            file_size_bytes INTEGER NOT NULL DEFAULT 0,
            page_count INTEGER NOT NULL,
            slide_hashes_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_accessed_at TEXT NOT NULL
        )
        """
    )

    connection.commit()
    return connection


def read_cached_visual_description(
    namespace_id: str,
    slide_hash: str,
    model_id: str,
    active_prompt_version: str,
    active_prompt_hash: str,
) -> dict[str, Any] | None:
    with get_cache_connection() as connection:
        row = connection.execute(
            """
            SELECT * FROM visual_descriptions
            WHERE namespace_id = ?
              AND slide_hash = ?
              AND model_id = ?
              AND prompt_version = ?
              AND prompt_hash = ?
            """,
            (namespace_id, slide_hash, model_id, active_prompt_version, active_prompt_hash),
        ).fetchone()

    if not row:
        return None

    description = json.loads(row["description_json"])
    return {
        **description,
        "slideHash": row["slide_hash"],
        "textHash": row["text_hash"],
        "model": row["model_id"],
        "promptVersion": row["prompt_version"],
        "markdownBlock": row["markdown_block"],
        "latencyMs": row["latency_ms"],
        "cacheStatus": "hit",
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def write_cached_visual_description(
    namespace_id: str,
    slide_hash: str,
    text_hash: str,
    page_number: Any,
    model_id: str,
    active_prompt_version: str,
    active_prompt_hash: str,
    description: dict[str, Any],
    markdown_block: str,
    latency_ms: int,
) -> None:
    now = utc_now_iso()
    with get_cache_connection() as connection:
        connection.execute(
            """
            INSERT INTO visual_descriptions (
                namespace_id,
                slide_hash,
                model_id,
                prompt_version,
                prompt_hash,
                text_hash,
                page_number,
                description_json,
                markdown_block,
                latency_ms,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(namespace_id, slide_hash, model_id, prompt_version, prompt_hash)
            DO UPDATE SET
                text_hash = excluded.text_hash,
                page_number = excluded.page_number,
                description_json = excluded.description_json,
                markdown_block = excluded.markdown_block,
                latency_ms = excluded.latency_ms,
                updated_at = excluded.updated_at
            """,
            (
                namespace_id,
                slide_hash,
                model_id,
                active_prompt_version,
                active_prompt_hash,
                text_hash,
                str(page_number or ""),
                json.dumps(description, ensure_ascii=False),
                markdown_block,
                latency_ms,
                now,
                now,
            ),
        )
        connection.commit()


def call_opencode_vision(
    image_source: str,
    prompt: str,
    model_id: str,
) -> tuple[dict[str, Any], int]:
    api_key = os.getenv("OPENCODE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENCODE_API_KEY is not set. Add it to .env.local and restart the app.")

    started_at = time.perf_counter()
    payload = {
        "model": model_id,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_source}},
                ],
            }
        ],
        "max_tokens": OPENCODE_VISION_MAX_TOKENS,
        "temperature": OPENCODE_VISION_TEMPERATURE,
        "response_format": {"type": "json_object"},
    }
    try:
        completed = subprocess.run(
            ["node", str(OPENCODE_VISION_NODE_HELPER)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=OPENCODE_VISION_TIMEOUT_MS / 1000,
            creationflags=get_no_window_flag(),
            check=False,
            env={
                **os.environ,
                "OPENCODE_API_KEY": api_key,
                "OPENCODE_API_URL": OPENCODE_API_URL,
            },
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("OpenCode request timed out.") from exc

    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout or "No helper output.").strip()
        raise RuntimeError(f"OpenCode helper failed: {details}")

    try:
        helper_result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"OpenCode helper returned non-JSON output: {completed.stdout[:500]}") from exc

    raw_body = str(helper_result.get("body") or "")
    status_code = int(helper_result.get("status") or 0)

    if status_code < 200 or status_code >= 300:
        try:
            error_payload = json.loads(raw_body)
            message = (
                error_payload.get("error", {}).get("message")
                if isinstance(error_payload.get("error"), dict)
                else error_payload.get("error")
            )
        except Exception:
            message = raw_body
        raise RuntimeError(f"OpenCode returned HTTP {status_code}: {message or 'No error body.'}")

    try:
        response_payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"OpenCode returned non-JSON body: {raw_body[:200]}") from exc

    content = response_payload.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not content:
        raise RuntimeError(f"OpenCode response did not include message content: {response_payload}")

    try:
        parsed = normalize_json_content(content)
    except Exception as exc:
        raise RuntimeError(f"OpenCode response was not valid JSON: {content[:500]}") from exc

    latency_ms = round((time.perf_counter() - started_at) * 1000)
    return parsed, latency_ms


def normalize_image_job(image: dict[str, Any]) -> dict[str, Any]:
    source = str(image.get("source") or "").strip()
    slide_hash = str(image.get("slideHash") or image.get("fingerprint") or "").strip()

    if not slide_hash and source:
        slide_hash = sha256_text(source.split(",", 1)[1] if "," in source else source)

    return {
        "id": image.get("id") or slide_hash,
        "pageNumber": image.get("pageNumber"),
        "caption": image.get("caption") or "",
        "source": source,
        "slideHash": slide_hash,
        "fingerprint": image.get("fingerprint") or slide_hash[:16],
        "byteEstimate": int(image.get("byteEstimate") or estimate_data_uri_bytes(source)),
        "metrics": image.get("metrics") or {},
    }


def describe_visual_image(
    image: dict[str, Any],
    page_text: str,
    namespace_id: str,
    model_id: str,
    active_prompt_version: str,
) -> dict[str, Any]:
    normalized_image = normalize_image_job(image)
    slide_hash = normalized_image["slideHash"]
    page_number = normalized_image["pageNumber"]
    text_hash = sha256_text(page_text or "")

    if not slide_hash:
        return {
            "id": normalized_image["id"],
            "pageNumber": page_number,
            "error": "Slide hash is missing.",
            "cacheStatus": "error",
        }

    # Build the full prompt FIRST so its hash covers per-slide OCR text + metrics.
    # This ensures any change in text or config produces a different cache key.
    prompt = create_visual_prompt(page_number, page_text, normalized_image["metrics"])
    active_prompt_hash = prompt_hash(prompt)

    cached = read_cached_visual_description(
        namespace_id,
        slide_hash,
        model_id,
        active_prompt_version,
        active_prompt_hash,
    )
    if cached:
        return {
            "id": normalized_image["id"],
            "pageNumber": page_number,
            **cached,
        }

    if not normalized_image["source"]:
        return {
            "id": normalized_image["id"],
            "pageNumber": page_number,
            "slideHash": slide_hash,
            "error": "Slide image source is missing.",
            "cacheStatus": "error",
        }

    if normalized_image["byteEstimate"] > OPENCODE_VISION_MAX_IMAGE_BYTES:
        return {
            "id": normalized_image["id"],
            "pageNumber": page_number,
            "slideHash": slide_hash,
            "error": (
                f"Slide image is {normalized_image['byteEstimate']} bytes, above "
                f"OPENCODE_VISION_MAX_IMAGE_BYTES={OPENCODE_VISION_MAX_IMAGE_BYTES}."
            ),
            "cacheStatus": "error",
        }

    try:
        raw_description, latency_ms = call_opencode_vision(normalized_image["source"], prompt, model_id)
        description = normalize_description_payload(raw_description, page_number)
        markdown_block = format_visual_markdown(description)
        write_cached_visual_description(
            namespace_id=namespace_id,
            slide_hash=slide_hash,
            text_hash=text_hash,
            page_number=page_number,
            model_id=model_id,
            active_prompt_version=active_prompt_version,
            active_prompt_hash=active_prompt_hash,
            description=description,
            markdown_block=markdown_block,
            latency_ms=latency_ms,
        )
        return {
            "id": normalized_image["id"],
            "slideHash": slide_hash,
            "textHash": text_hash,
            "model": model_id,
            "promptVersion": active_prompt_version,
            "markdownBlock": markdown_block,
            "latencyMs": latency_ms,
            "cacheStatus": "miss",
            **description,
        }
    except Exception as exc:
        return {
            "id": normalized_image["id"],
            "pageNumber": page_number,
            "slideHash": slide_hash,
            "model": model_id,
            "promptVersion": active_prompt_version,
            "error": str(exc),
            "cacheStatus": "error",
        }


def run_visual_description_jobs(
    images: list[dict[str, Any]],
    page_text_by_number: dict[str, str],
    namespace_id: str,
    model_id: str,
    active_prompt_version: str,
) -> list[dict[str, Any]]:
    def run_one(image: dict[str, Any]) -> dict[str, Any]:
        page_number = image.get("pageNumber")
        page_text = page_text_by_number.get(str(page_number or "Unknown"), "")
        return describe_visual_image(image, page_text, namespace_id, model_id, active_prompt_version)

    concurrency = max(1, min(OPENCODE_VISION_CONCURRENCY, len(images) or 1))
    if concurrency == 1 or len(images) <= 1:
        return [run_one(image) for image in images]

    results: list[dict[str, Any] | None] = [None] * len(images)
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_to_index = {executor.submit(run_one, image): index for index, image in enumerate(images)}
        for future in as_completed(future_to_index):
            results[future_to_index[future]] = future.result()

    return [result for result in results if result is not None]


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


def render_page_data_uri(page: pymupdf.Page, images_scale: float) -> tuple[str, str, str, int]:
    matrix = pymupdf.Matrix(images_scale, images_scale)
    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
    image_bytes = pixmap.tobytes("png")
    encoded = base64.b64encode(image_bytes).decode("ascii")
    slide_hash = hashlib.sha256(image_bytes).hexdigest()
    fingerprint = slide_hash[:16]
    return f"data:image/png;base64,{encoded}", fingerprint, slide_hash, len(image_bytes)


def render_page_images(pdf_path: Path, images_scale: float) -> list[dict[str, Any]]:
    images = []
    scale = clamp_render_scale(images_scale)

    with pymupdf.open(pdf_path) as document:
        for page in document:
            text_areas, picture_areas = extract_page_areas(page)
            source, fingerprint, slide_hash, byte_estimate = render_page_data_uri(page, scale)
            page_number = page.number + 1
            images.append(
                {
                    "id": f"local-page-{page_number}",
                    "pageNumber": page_number,
                    "caption": f"Rendered slide {page_number}",
                    "source": source,
                    "sourcePath": f"local.page[{page_number}].render",
                    "fingerprint": fingerprint,
                    "slideHash": slide_hash,
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
        "openCodeVision": {
            "configured": bool(os.getenv("OPENCODE_API_KEY", "").strip()),
            "model": OPENCODE_VISION_MODEL,
            "promptVersion": OPENCODE_VISION_PROMPT_VERSION,
            "cachePath": str(SLIDEVISION_CACHE_PATH),
            "cacheNamespace": SLIDEVISION_CACHE_NAMESPACE,
        },
    }


@app.post("/v1/visual-descriptions")
async def describe_visuals(payload: dict[str, Any]) -> dict[str, Any]:
    images = payload.get("images") if isinstance(payload.get("images"), list) else []
    page_text_by_number = payload.get("pageTextByNumber") or {}
    namespace_id = str(payload.get("namespaceId") or SLIDEVISION_CACHE_NAMESPACE or "default")
    model_id = str(payload.get("model") or OPENCODE_VISION_MODEL)
    active_prompt_version = str(payload.get("promptVersion") or OPENCODE_VISION_PROMPT_VERSION)
    started_at = time.perf_counter()

    descriptions = run_visual_description_jobs(
        images=images,
        page_text_by_number=page_text_by_number,
        namespace_id=namespace_id,
        model_id=model_id,
        active_prompt_version=active_prompt_version,
    )
    cache_hits = sum(1 for description in descriptions if description.get("cacheStatus") == "hit")
    cache_misses = sum(1 for description in descriptions if description.get("cacheStatus") == "miss")
    failures = sum(1 for description in descriptions if description.get("cacheStatus") == "error")

    return {
        "provider": "opencode-go",
        "model": model_id,
        "promptVersion": active_prompt_version,
        "namespaceId": namespace_id,
        "descriptions": descriptions,
        "cache": {
            "hits": cache_hits,
            "misses": cache_misses,
            "failures": failures,
            "path": str(SLIDEVISION_CACHE_PATH),
        },
        "elapsedMs": round((time.perf_counter() - started_at) * 1000),
    }


# ---------------------------------------------------------------------------
# Extraction cache helpers
# ---------------------------------------------------------------------------

def hash_file(path: Path) -> str:
    """SHA-256 hash of raw file bytes — used as the extraction cache key."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def read_cached_extraction(
    file_hash: str,
    images_scale: float,
    ocr_language: str,
    force_ocr: bool,
) -> dict[str, Any] | None:
    with get_cache_connection() as connection:
        row = connection.execute(
            """
            SELECT * FROM document_extractions
            WHERE file_hash = ? AND images_scale = ? AND ocr_language = ? AND force_ocr = ?
            """,
            (file_hash, images_scale, ocr_language, int(force_ocr)),
        ).fetchone()

    if not row:
        return None

    return {
        "provider": "local-pymupdf4llm-rapidocr",
        "sourcePath": "local_pymupdf4llm",
        "markdown": row["markdown"],
        "chunks": json.loads(row["chunks_json"]),
        "figures": [],  # re-built from fresh images after cache hit
        "embeddedImages": [],  # re-rendered after cache hit
        "tableCount": row["table_count"],
        "warnings": json.loads(row["warnings_json"]),
        "metadata": {
            **json.loads(row["metadata_json"]),
            "cacheStatus": "hit",
            "originalExtractionMs": row["extraction_ms"],
            "cachedAt": row["created_at"],
        },
    }


def write_cached_extraction(
    file_hash: str,
    images_scale: float,
    ocr_language: str,
    force_ocr: bool,
    file_name: str,
    file_size_bytes: int,
    response: dict[str, Any],
) -> None:
    metadata = {k: v for k, v in response.get("metadata", {}).items() if k != "elapsedMs"}
    extraction_ms = response.get("metadata", {}).get("elapsedMs", 0)
    now = utc_now_iso()
    with get_cache_connection() as connection:
        connection.execute(
            """
            INSERT INTO document_extractions (
                file_hash, images_scale, ocr_language, force_ocr,
                file_name, page_count, file_size_bytes,
                markdown, chunks_json, warnings_json, table_count,
                metadata_json, extraction_ms, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_hash, images_scale, ocr_language, force_ocr)
            DO UPDATE SET
                file_name = excluded.file_name,
                page_count = excluded.page_count,
                markdown = excluded.markdown,
                chunks_json = excluded.chunks_json,
                warnings_json = excluded.warnings_json,
                table_count = excluded.table_count,
                metadata_json = excluded.metadata_json,
                extraction_ms = excluded.extraction_ms
            """,
            (
                file_hash,
                images_scale,
                ocr_language,
                int(force_ocr),
                file_name,
                response.get("metadata", {}).get("pageCount", 0),
                file_size_bytes,
                response.get("markdown", ""),
                json.dumps(response.get("chunks", []), ensure_ascii=False),
                json.dumps(response.get("warnings", []), ensure_ascii=False),
                response.get("tableCount", 0),
                json.dumps(metadata, ensure_ascii=False),
                extraction_ms,
                now,
            ),
        )
        connection.commit()


# ---------------------------------------------------------------------------
# Document registry helpers (deck_id / multi-user)
# ---------------------------------------------------------------------------

def upsert_document(
    document_id: str,
    file_name: str,
    file_size_bytes: int,
    page_count: int,
    slide_hashes: list[str],
) -> None:
    now = utc_now_iso()
    with get_cache_connection() as connection:
        connection.execute(
            """
            INSERT INTO documents (
                document_id, file_name, file_size_bytes, page_count,
                slide_hashes_json, created_at, last_accessed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(document_id) DO UPDATE SET
                file_name = excluded.file_name,
                page_count = excluded.page_count,
                slide_hashes_json = excluded.slide_hashes_json,
                last_accessed_at = excluded.last_accessed_at
            """,
            (
                document_id,
                file_name,
                file_size_bytes,
                page_count,
                json.dumps(slide_hashes, ensure_ascii=False),
                now,
                now,
            ),
        )
        connection.commit()


# ---------------------------------------------------------------------------
# Hash-only visual description lookup (no image data needed)
# ---------------------------------------------------------------------------

def read_cached_visual_description_by_hash(
    namespace_id: str,
    slide_hash: str,
    model_id: str,
) -> dict[str, Any] | None:
    """Relaxed lookup — returns the newest cached entry for a slide hash
    regardless of prompt version. Used by the hash-only lookup endpoint so
    callers can check the cache without uploading base64 image data."""
    with get_cache_connection() as connection:
        row = connection.execute(
            """
            SELECT * FROM visual_descriptions
            WHERE namespace_id = ? AND slide_hash = ? AND model_id = ?
            ORDER BY updated_at DESC LIMIT 1
            """,
            (namespace_id, slide_hash, model_id),
        ).fetchone()

    if not row:
        return None

    description = json.loads(row["description_json"])
    return {
        **description,
        "slideHash": row["slide_hash"],
        "textHash": row["text_hash"],
        "model": row["model_id"],
        "promptVersion": row["prompt_version"],
        "markdownBlock": row["markdown_block"],
        "latencyMs": row["latency_ms"],
        "cacheStatus": "hit",
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


# ---------------------------------------------------------------------------
# /v1/convert/file  — with extraction cache + document registry
# ---------------------------------------------------------------------------

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

    with tempfile.TemporaryDirectory(prefix="slidevision-local-", ignore_cleanup_errors=True) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        input_path = temp_dir / filename

        try:
            # ---- 1. Save upload ----------------------------------------
            file_size_bytes = 0
            with input_path.open("wb") as temp_file:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    temp_file.write(chunk)
                    file_size_bytes += len(chunk)

            # ---- 2. Hash the file (cache key) --------------------------
            started_at = time.perf_counter()
            file_hash = hash_file(input_path)

            # ---- 3. PowerPoint conversion (needed before cache check) --
            conversion_warnings: list[str] = []
            pdf_path = input_path
            if is_powerpoint:
                pdf_path, conversion_warnings = convert_office_to_pdf(input_path, temp_dir)
                # Re-hash the resulting PDF for the cache key
                file_hash = hash_file(pdf_path)

            # ---- 4. Check extraction cache -----------------------------
            cached = read_cached_extraction(file_hash, images_scale, ocr_language, force_ocr)
            if cached:
                # Re-render images (< 1 s); OCR is skipped entirely.
                images = render_page_images(pdf_path, images_scale)
                cached["embeddedImages"] = images
                cached["figures"] = build_figures_from_images(images)
                cached["warnings"] = conversion_warnings + cached["warnings"]
                if is_powerpoint:
                    cached["metadata"]["convertedFrom"] = filename
                    cached["metadata"]["convertedPdfName"] = pdf_path.name
                cached["metadata"]["elapsedMs"] = round((time.perf_counter() - started_at) * 1000)

                # Update last_accessed_at in document registry
                upsert_document(
                    document_id=file_hash,
                    file_name=filename,
                    file_size_bytes=file_size_bytes,
                    page_count=cached["metadata"].get("pageCount", len(images)),
                    slide_hashes=[img["slideHash"] for img in images],
                )
                return cached

            # ---- 5. Full extraction (slow path) ------------------------
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
            response["metadata"]["cacheStatus"] = "miss"

            # ---- 6. Write extraction cache -----------------------------
            write_cached_extraction(
                file_hash=file_hash,
                images_scale=images_scale,
                ocr_language=ocr_language,
                force_ocr=force_ocr,
                file_name=filename,
                file_size_bytes=file_size_bytes,
                response=response,
            )

            # ---- 7. Register document for deck-level queries -----------
            upsert_document(
                document_id=file_hash,
                file_name=filename,
                file_size_bytes=file_size_bytes,
                page_count=response["metadata"].get("pageCount", 0),
                slide_hashes=[img["slideHash"] for img in response.get("embeddedImages", [])],
            )

            return response

        except subprocess.TimeoutExpired as exc:
            raise HTTPException(status_code=504, detail=f"Local conversion timed out: {exc}") from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# /v1/visual-descriptions/lookup  — hash-only cache check
# ---------------------------------------------------------------------------

@app.post("/v1/visual-descriptions/lookup")
async def lookup_visual_descriptions(payload: dict[str, Any]) -> dict[str, Any]:
    """Check the visual description cache by slide hash only.

    Callers send a list of slide hashes (no base64 image data) and receive
    back which slides are already cached and which are missing. This lets
    the frontend skip uploading large images for slides already in cache.
    """
    slide_hashes: list[str] = [
        str(h) for h in payload.get("slideHashes", []) if h
    ]
    model_id = str(payload.get("model") or OPENCODE_VISION_MODEL)
    namespace_id = str(payload.get("namespaceId") or SLIDEVISION_CACHE_NAMESPACE)

    cached_results: list[dict[str, Any]] = []
    missing_hashes: list[str] = []

    for slide_hash in slide_hashes:
        result = read_cached_visual_description_by_hash(namespace_id, slide_hash, model_id)
        if result:
            result["slideHash"] = slide_hash  # ensure field is present
            cached_results.append(result)
        else:
            missing_hashes.append(slide_hash)

    return {
        "cached": cached_results,
        "missing": missing_hashes,
        "totalRequested": len(slide_hashes),
        "cacheHits": len(cached_results),
        "cacheMisses": len(missing_hashes),
    }


# ---------------------------------------------------------------------------
# /v1/documents  — list all processed documents
# ---------------------------------------------------------------------------

@app.get("/v1/documents")
def list_documents() -> dict[str, Any]:
    """Return all previously processed documents with their slide hashes and
    the number of cached visual descriptions available for each.
    """
    with get_cache_connection() as connection:
        docs = connection.execute(
            "SELECT * FROM documents ORDER BY last_accessed_at DESC"
        ).fetchall()

    results = []
    for doc in docs:
        slide_hashes: list[str] = json.loads(doc["slide_hashes_json"] or "[]")
        # Count how many slides for this document have a cached description
        with get_cache_connection() as connection:
            cached_count = connection.execute(
                f"""
                SELECT COUNT(DISTINCT slide_hash) FROM visual_descriptions
                WHERE slide_hash IN ({','.join('?' * len(slide_hashes))})
                """,
                slide_hashes,
            ).fetchone()[0] if slide_hashes else 0

        results.append({
            "documentId": doc["document_id"],
            "fileName": doc["file_name"],
            "fileSizeBytes": doc["file_size_bytes"],
            "pageCount": doc["page_count"],
            "slideCount": len(slide_hashes),
            "cachedDescriptionCount": cached_count,
            "createdAt": doc["created_at"],
            "lastAccessedAt": doc["last_accessed_at"],
        })

    return {
        "documents": results,
        "total": len(results),
        "cachePath": str(SLIDEVISION_CACHE_PATH),
    }
