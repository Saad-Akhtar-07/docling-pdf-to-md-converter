"""(Re)generates the golden `expected_blocks.json` for every deck under
tests/fixtures/decks/. Run this after `generate_decks.py`, and again any time
a deliberate change to block-building logic changes the expected output.

    .venv\\Scripts\\python.exe tests\\fixtures\\generate_expected_blocks.py
"""

import json
from pathlib import Path

from slidevision.extraction.blocks import build_document_blocks
from slidevision.extraction.utils import hash_file

DECKS_DIR = Path(__file__).parent / "decks"


def main() -> None:
    for deck_dir in sorted(DECKS_DIR.iterdir()):
        deck_path = deck_dir / "deck.pdf"
        if not deck_path.exists():
            continue

        document_id = hash_file(deck_path)
        warnings: list[str] = []
        blocks = build_document_blocks(deck_path, document_id=document_id, force_ocr=False, warnings=warnings)

        golden = {
            "documentId": document_id,
            "warnings": warnings,
            "blocks": [block.model_dump() for block in blocks],
        }
        golden_path = deck_dir / "expected_blocks.json"
        golden_path.write_text(json.dumps(golden, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {golden_path} ({len(blocks)} blocks)")


if __name__ == "__main__":
    main()
