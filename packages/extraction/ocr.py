from typing import Any

import pymupdf

OCR_FONT = pymupdf.Font("cjk")
OCR_FONTNAME = "slidevision_ocr_font"
REPLACEMENT_UNICODE = chr(0xFFFD)

RAPID_OCR_ENGINE: Any | None = None


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
