"""Builds the synthetic fixture deck corpus used by
tests/unit/test_extraction_regression.py.

Real lecture decks are not checked into the repo (they contain the user's
course material), so these PDFs are generated programmatically instead:
deterministic, tiny, and covering the four content shapes the extraction
regression suite needs to exercise --

    text_heavy    -- plain slide text only               -> verbatim blocks
    tables        -- grid tables of text                 -> verbatim blocks
    image_heavy   -- drawn figures + caption text         -> verbatim blocks
                     (pictures alongside legible text; must NOT trigger OCR)
    scanned_ocr   -- pages rasterised with NO text layer  -> ocr blocks
    mixed         -- one deck spanning all of the above, to exercise
                     slide_no/order_index continuity across per-page
                     provenance changes within a single document

Run directly to (re)generate the PDFs:
    .venv\\Scripts\\python.exe tests\\fixtures\\generate_decks.py
"""

from pathlib import Path

import pymupdf

DECKS_DIR = Path(__file__).parent / "decks"

PAGE_WIDTH = 720
PAGE_HEIGHT = 540


def _add_text_slide(doc: pymupdf.Document, title: str, paragraphs: list[str]) -> None:
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    page.insert_text((72, 72), title, fontsize=22, fontname="helv")
    y = 130
    for paragraph in paragraphs:
        page.insert_text((72, y), paragraph, fontsize=13, fontname="helv")
        y += 28


def build_text_heavy(path: Path) -> None:
    doc = pymupdf.open()
    _add_text_slide(
        doc,
        "Introduction to Sorting Algorithms",
        [
            "Sorting rearranges the elements of a list into a defined order.",
            "Comparison-based sorts are bounded below by O(n log n) worst case.",
            "Stability means equal elements keep their original relative order.",
        ],
    )
    _add_text_slide(
        doc,
        "Merge Sort",
        [
            "Merge sort splits the input in half recursively.",
            "Each half is sorted independently, then merged in linear time.",
            "Merge sort is stable and runs in O(n log n) time in all cases.",
        ],
    )
    _add_text_slide(
        doc,
        "Quick Sort",
        [
            "Quick sort partitions the array around a chosen pivot element.",
            "Average case running time is O(n log n); worst case is O(n^2).",
            "In place partitioning avoids the extra memory merge sort needs.",
        ],
    )
    _add_text_slide(
        doc,
        "Summary",
        [
            "Choose merge sort when stability or worst-case guarantees matter.",
            "Choose quick sort when average-case speed and low memory matter.",
        ],
    )
    doc.save(path)
    doc.close()


def _add_table_slide(doc: pymupdf.Document, title: str, rows: list[list[str]]) -> None:
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    page.insert_text((72, 72), title, fontsize=22, fontname="helv")

    col_width = 140
    row_height = 32
    top = 130
    left = 72

    for row_index, row in enumerate(rows):
        for col_index, cell in enumerate(row):
            x0 = left + col_index * col_width
            y0 = top + row_index * row_height
            rect = pymupdf.Rect(x0, y0, x0 + col_width, y0 + row_height)
            page.draw_rect(rect, color=(0, 0, 0), width=0.75)
            page.insert_text((x0 + 6, y0 + 20), cell, fontsize=11, fontname="helv")


def build_tables(path: Path) -> None:
    doc = pymupdf.open()
    _add_table_slide(
        doc,
        "Algorithm Complexity Comparison",
        [
            ["Algorithm", "Best", "Worst"],
            ["Merge Sort", "O(n log n)", "O(n log n)"],
            ["Quick Sort", "O(n log n)", "O(n^2)"],
            ["Bubble Sort", "O(n)", "O(n^2)"],
        ],
    )
    _add_table_slide(
        doc,
        "Data Structure Operations",
        [
            ["Structure", "Insert", "Lookup"],
            ["Array", "O(n)", "O(1)"],
            ["Linked List", "O(1)", "O(n)"],
            ["Hash Table", "O(1)", "O(1)"],
        ],
    )
    _add_table_slide(
        doc,
        "Storage Cost Estimates",
        [
            ["Item", "Rows", "Bytes/Row"],
            ["Users", "12,000", "128"],
            ["Orders", "480,000", "256"],
            ["Events", "9,300,000", "64"],
        ],
    )
    doc.save(path)
    doc.close()


def _draw_figure(page: pymupdf.Page, origin_y: float) -> None:
    page.draw_rect(
        pymupdf.Rect(120, origin_y, 600, origin_y + 220),
        color=(0.1, 0.1, 0.1),
        fill=(0.85, 0.9, 0.97),
        width=1.5,
    )
    page.draw_circle((260, origin_y + 110), 60, color=(0.1, 0.3, 0.6), fill=(0.6, 0.75, 0.95), width=1.5)
    page.draw_line((320, origin_y + 110), (500, origin_y + 60), color=(0.1, 0.3, 0.6), width=2)
    page.draw_line((320, origin_y + 110), (500, origin_y + 160), color=(0.1, 0.3, 0.6), width=2)


def _add_image_slide(doc: pymupdf.Document, title: str, caption: str) -> None:
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    page.insert_text((72, 72), title, fontsize=22, fontname="helv")
    page.insert_text((72, 105), caption, fontsize=13, fontname="helv")
    _draw_figure(page, origin_y=140)


def build_image_heavy(path: Path) -> None:
    doc = pymupdf.open()
    _add_image_slide(
        doc,
        "Client-Server Architecture",
        "Figure: a client sends a request; the server returns a response.",
    )
    _add_image_slide(
        doc,
        "Load Balancing",
        "Figure: a load balancer distributes requests across replicas.",
    )
    _add_image_slide(
        doc,
        "Cache Layer",
        "Figure: a cache sits between the application and the database.",
    )
    doc.save(path)
    doc.close()


def _render_text_only_page_as_image(title: str, lines: list[str]) -> bytes:
    """Builds a throwaway text page, rasterises it, and returns PNG bytes --
    used to build a page with NO text layer at all (a stand-in for a scanned
    slide), so the extractor must fall back to OCR to recover its text."""
    source_doc = pymupdf.open()
    page = source_doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    page.insert_text((72, 90), title, fontsize=26, fontname="helv")
    y = 160
    for line in lines:
        page.insert_text((72, y), line, fontsize=16, fontname="helv")
        y += 34
    pixmap = page.get_pixmap(dpi=200)
    png_bytes = pixmap.tobytes("png")
    source_doc.close()
    return png_bytes


def _add_scanned_slide(doc: pymupdf.Document, title: str, lines: list[str]) -> None:
    png_bytes = _render_text_only_page_as_image(title, lines)
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    page.insert_image(pymupdf.Rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT), stream=png_bytes)


def build_scanned_ocr(path: Path) -> None:
    doc = pymupdf.open()
    _add_scanned_slide(
        doc,
        "Scanned Lecture Note",
        [
            "Photosynthesis converts light energy into chemical energy.",
            "It takes place mainly in the chloroplasts of plant cells.",
            "The products are glucose and oxygen gas.",
        ],
    )
    _add_scanned_slide(
        doc,
        "Cellular Respiration",
        [
            "Respiration releases energy stored in glucose molecules.",
            "It occurs in the mitochondria of the cell.",
            "Carbon dioxide and water are released as byproducts.",
        ],
    )
    doc.save(path)
    doc.close()


def build_mixed(path: Path) -> None:
    doc = pymupdf.open()
    _add_text_slide(
        doc,
        "Networking Fundamentals",
        [
            "A network connects devices so they can exchange data.",
            "Packets carry data plus addressing and control information.",
        ],
    )
    _add_image_slide(
        doc,
        "The OSI Model",
        "Figure: seven layers from physical transmission to application.",
    )
    _add_scanned_slide(
        doc,
        "Handwritten Note",
        [
            "TCP guarantees ordered, reliable delivery of a byte stream.",
            "UDP is connectionless and does not guarantee delivery.",
        ],
    )
    doc.save(path)
    doc.close()


DECKS = {
    "text_heavy": build_text_heavy,
    "tables": build_tables,
    "image_heavy": build_image_heavy,
    "scanned_ocr": build_scanned_ocr,
    "mixed": build_mixed,
}


def main() -> None:
    for deck_name, builder in DECKS.items():
        deck_dir = DECKS_DIR / deck_name
        deck_dir.mkdir(parents=True, exist_ok=True)
        builder(deck_dir / "deck.pdf")
        print(f"wrote {deck_dir / 'deck.pdf'}")


if __name__ == "__main__":
    main()
