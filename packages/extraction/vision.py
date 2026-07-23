import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from . import config
from .cache import read_cached_visual_description, write_cached_visual_description
from .utils import compact_page_text, estimate_data_uri_bytes, format_list, get_no_window_flag, normalize_json_content, sha256_text

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
    return sha256_text(f"{config.OPENCODE_VISION_PROMPT_VERSION}\n{actual_prompt}")


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
        "max_tokens": config.OPENCODE_VISION_MAX_TOKENS,
        "temperature": config.OPENCODE_VISION_TEMPERATURE,
        "response_format": {"type": "json_object"},
    }
    try:
        completed = subprocess.run(
            ["node", str(config.OPENCODE_VISION_NODE_HELPER)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=config.OPENCODE_VISION_TIMEOUT_MS / 1000,
            creationflags=get_no_window_flag(),
            check=False,
            env={
                **os.environ,
                "OPENCODE_API_KEY": api_key,
                "OPENCODE_API_URL": config.OPENCODE_API_URL,
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

    # Detect if the model was stopped early by a token limit
    finish_reason = (
        str(response_payload.get("choices", [{}])[0].get("finish_reason") or "").lower()
    )
    is_truncated = finish_reason == "length"

    try:
        parsed = normalize_json_content(content, is_truncated=is_truncated)
    except Exception as exc:
        truncation_note = " (output was truncated by token limit — raise OPENCODE_VISION_MAX_TOKENS)" if is_truncated else ""
        raise RuntimeError(
            f"OpenCode response was not valid JSON{truncation_note}: {content[:500]}"
        ) from exc

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

    if normalized_image["byteEstimate"] > config.OPENCODE_VISION_MAX_IMAGE_BYTES:
        return {
            "id": normalized_image["id"],
            "pageNumber": page_number,
            "slideHash": slide_hash,
            "error": (
                f"Slide image is {normalized_image['byteEstimate']} bytes, above "
                f"OPENCODE_VISION_MAX_IMAGE_BYTES={config.OPENCODE_VISION_MAX_IMAGE_BYTES}."
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

    concurrency = max(1, min(config.OPENCODE_VISION_CONCURRENCY, len(images) or 1))
    if concurrency == 1 or len(images) <= 1:
        return [run_one(image) for image in images]

    results: list[dict[str, Any] | None] = [None] * len(images)
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_to_index = {executor.submit(run_one, image): index for index, image in enumerate(images)}
        for future in as_completed(future_to_index):
            results[future_to_index[future]] = future.result()

    return [result for result in results if result is not None]
