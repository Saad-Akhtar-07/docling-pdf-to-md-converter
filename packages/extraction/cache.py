import json
import sqlite3
from pathlib import Path
from typing import Any

from . import config
from .utils import hash_file, utc_now_iso


def get_cache_connection() -> sqlite3.Connection:
    config.SLIDEVISION_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(config.SLIDEVISION_CACHE_PATH, timeout=30)
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
