import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import pymupdf
import pymupdf4llm
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from . import config
from . import office as office_module
from .cache import (
    get_cache_connection,
    hash_file,
    read_cached_extraction,
    read_cached_visual_description_by_hash,
    upsert_document,
    write_cached_extraction,
)
from .geometry import build_figures_from_images, render_page_images
from .office import convert_office_to_pdf, find_libreoffice, start_libreoffice_listener, stop_libreoffice_listener
from .pipeline import extract_document
from .vision import run_visual_description_jobs

app = FastAPI(title="SlideVision Local Extractor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


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

    listener_running = bool(office_module.LIBREOFFICE_PROCESS and office_module.LIBREOFFICE_PROCESS.poll() is None)

    return {
        "status": "ok",
        "provider": "local-pymupdf4llm-rapidocr",
        "pymupdfVersion": pymupdf.__version__,
        "pymupdf4llmVersion": pymupdf4llm.__version__,
        "rapidOcrAvailable": rapidocr_available,
        "rapidOcrPackage": rapidocr_package,
        "libreOfficePath": find_libreoffice(),
        "libreOfficeListenerRunning": listener_running,
        "libreOfficePort": config.LIBREOFFICE_LISTENER_PORT,
        "openCodeVision": {
            "configured": bool(os.getenv("OPENCODE_API_KEY", "").strip()),
            "model": config.OPENCODE_VISION_MODEL,
            "promptVersion": config.OPENCODE_VISION_PROMPT_VERSION,
            "cachePath": str(config.SLIDEVISION_CACHE_PATH),
            "cacheNamespace": config.SLIDEVISION_CACHE_NAMESPACE,
        },
    }


@app.post("/v1/visual-descriptions")
async def describe_visuals(payload: dict[str, Any]) -> dict[str, Any]:
    images = payload.get("images") if isinstance(payload.get("images"), list) else []
    page_text_by_number = payload.get("pageTextByNumber") or {}
    namespace_id = str(payload.get("namespaceId") or config.SLIDEVISION_CACHE_NAMESPACE or "default")
    model_id = str(payload.get("model") or config.OPENCODE_VISION_MODEL)
    active_prompt_version = str(payload.get("promptVersion") or config.OPENCODE_VISION_PROMPT_VERSION)
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
            "path": str(config.SLIDEVISION_CACHE_PATH),
        },
        "elapsedMs": round((time.perf_counter() - started_at) * 1000),
    }


@app.post("/v1/convert/file")
async def convert_file(
    file: UploadFile = File(...),
    images_scale: float = Form(config.DEFAULT_IMAGES_SCALE),
    ocr_language: str = Form(config.DEFAULT_OCR_LANGUAGE),
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
    model_id = str(payload.get("model") or config.OPENCODE_VISION_MODEL)
    namespace_id = str(payload.get("namespaceId") or config.SLIDEVISION_CACHE_NAMESPACE)

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
        "cachePath": str(config.SLIDEVISION_CACHE_PATH),
    }
