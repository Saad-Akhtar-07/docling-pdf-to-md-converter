import argparse
import sys
import tempfile
from pathlib import Path

from . import config
from .office import convert_office_to_pdf
from .pipeline import extract_document


def convert_path_to_markdown(
    input_path: Path,
    images_scale: float = config.DEFAULT_IMAGES_SCALE,
    ocr_language: str = config.DEFAULT_OCR_LANGUAGE,
    force_ocr: bool = False,
) -> str:
    lower_name = input_path.name.lower()
    is_pdf = lower_name.endswith(".pdf")
    is_powerpoint = lower_name.endswith((".ppt", ".pptx", ".odp"))

    if not is_pdf and not is_powerpoint:
        raise ValueError("Only PDF, PPT, PPTX, or ODP input is supported.")

    if is_pdf:
        response = extract_document(
            input_path,
            document_name=input_path.name,
            images_scale=images_scale,
            ocr_language=ocr_language,
            force_ocr=force_ocr,
        )
        return response["markdown"]

    with tempfile.TemporaryDirectory(prefix="slidevision-cli-", ignore_cleanup_errors=True) as temp_dir_name:
        pdf_path, _warnings = convert_office_to_pdf(input_path, Path(temp_dir_name))
        response = extract_document(
            pdf_path,
            document_name=input_path.name,
            images_scale=images_scale,
            ocr_language=ocr_language,
            force_ocr=force_ocr,
        )
        return response["markdown"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert a PDF/PPT/PPTX/ODP file to page-aware Markdown using the SlideVision extractor.",
    )
    parser.add_argument("input", type=Path, help="Path to the PDF/PPT/PPTX/ODP file to convert.")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Write Markdown to this file instead of stdout.")
    parser.add_argument("--images-scale", type=float, default=config.DEFAULT_IMAGES_SCALE)
    parser.add_argument("--ocr-language", type=str, default=config.DEFAULT_OCR_LANGUAGE)
    parser.add_argument("--force-ocr", action="store_true")
    args = parser.parse_args(argv)

    markdown = convert_path_to_markdown(
        args.input,
        images_scale=args.images_scale,
        ocr_language=args.ocr_language,
        force_ocr=args.force_ocr,
    )

    if args.output:
        args.output.write_text(markdown, encoding="utf-8")
    else:
        sys.stdout.write(markdown)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
