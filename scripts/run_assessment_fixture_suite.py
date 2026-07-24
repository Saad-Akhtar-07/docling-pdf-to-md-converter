"""Module 5 acceptance check: runs tests/fixtures/assessments.jsonl (40
hand-labelled objective/question/answer/expected_verdict rows, see
tests/fixtures/generate_assessments.py) against the real assess_response
pipeline (a real OpenCode Zen call per row, through the full repair chain),
and prints a confusion matrix, per-verdict accuracy, overall agreement, and
the worst failures ranked by how far off the predicted verdict was.

Requires OPENCODE_API_KEY (real LLM calls) and a reachable DATABASE_URL
(packages/llm/logging.py logs every call to llm_calls). Not part of the
pytest suite -- LLM output isn't deterministic enough for a pass/fail CI
gate the way tests/contract's mocked tests are; this is an evaluation
report to read, matching docs/…§2.15's "Pedagogical (offline)" testing
layer.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from slidevision.graph.assessment import assess_and_repair
from slidevision.llm import config
from slidevision.tutor_core import EvidenceCard

_FIXTURES_PATH = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "assessments.jsonl"

_VERDICTS = ["dont_know", "confused", "incorrect", "partial", "correct"]
_SEVERITY = {v: i for i, v in enumerate(_VERDICTS)}


def _load_rows() -> list[dict]:
    rows = []
    with _FIXTURES_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _run_one(row: dict) -> dict:
    card = EvidenceCard.model_validate(row["card"])
    assessment, repairs, used_safe_default = assess_and_repair(
        objective_statement=row["objective_statement"],
        card=card,
        source_text=row["source_text"],
        question=row["question"],
        answer=row["answer"],
    )
    predicted = assessment.verdict
    expected = row["expected_verdict"]
    return {
        "id": row["id"],
        "expected": expected,
        "predicted": predicted,
        "match": predicted == expected,
        "used_safe_default": used_safe_default,
        "repairs": [r.rule for r in repairs],
        "note": row["note"],
        "answer": row["answer"],
        "objective_statement": row["objective_statement"],
    }


def main() -> None:
    rows = _load_rows()
    print(f"Running {len(rows)} fixture cases against the real assess_response pipeline...\n")

    with ThreadPoolExecutor(max_workers=config.MAX_CONCURRENCY) as pool:
        results = list(pool.map(_run_one, rows))
    results.sort(key=lambda r: r["id"])

    # --- confusion matrix ---------------------------------------------------
    matrix: dict[str, Counter] = {v: Counter() for v in _VERDICTS}
    for r in results:
        matrix[r["expected"]][r["predicted"]] += 1

    col_width = 11
    header = "expected \\ predicted".ljust(22) + "".join(v.rjust(col_width) for v in _VERDICTS)
    print(header)
    for expected in _VERDICTS:
        row_str = expected.ljust(22) + "".join(str(matrix[expected][p]).rjust(col_width) for p in _VERDICTS)
        print(row_str)
    print()

    # --- per-verdict accuracy -----------------------------------------------
    by_verdict: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_verdict[r["expected"]].append(r)

    print(f"{'verdict':<12}{'n':>5}{'correct':>9}{'accuracy':>11}")
    total_n, total_correct = 0, 0
    for v in _VERDICTS:
        rows_v = by_verdict.get(v, [])
        n = len(rows_v)
        correct = sum(1 for r in rows_v if r["match"])
        total_n += n
        total_correct += correct
        acc = f"{correct / n:.0%}" if n else "n/a"
        print(f"{v:<12}{n:>5}{correct:>9}{acc:>11}")
    overall = total_correct / total_n if total_n else 0.0
    print(f"\nOverall verdict agreement: {total_correct}/{total_n} = {overall:.1%}")
    print(f"Acceptance threshold: >=80% -> {'PASS' if overall >= 0.8 else 'FAIL'}")

    safe_default_count = sum(1 for r in results if r["used_safe_default"])
    print(f"Rows that fell back to the safe default (StructuredOutputError): {safe_default_count}/{len(results)}")

    # --- worst failures -------------------------------------------------
    mismatches = [r for r in results if not r["match"]]
    mismatches.sort(key=lambda r: abs(_SEVERITY[r["expected"]] - _SEVERITY[r["predicted"]]), reverse=True)
    print(f"\nTop {min(5, len(mismatches))} worst failures (by verdict-distance):")
    for r in mismatches[:5]:
        print(f"  [{r['id']}] expected={r['expected']!r} predicted={r['predicted']!r}")
        print(f"    objective: {r['objective_statement']}")
        print(f"    answer: {r['answer']!r}")
        print(f"    note: {r['note']}")
        if r["repairs"]:
            print(f"    repairs applied: {r['repairs']}")
        print()


if __name__ == "__main__":
    main()
