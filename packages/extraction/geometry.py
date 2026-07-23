import base64
import hashlib
from typing import Any

import pymupdf

from .utils import clamp_render_scale


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


def render_page_images(pdf_path, images_scale: float) -> list[dict[str, Any]]:
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
