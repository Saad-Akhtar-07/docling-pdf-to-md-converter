"""End-to-end acceptance demo for packages/planbuilder (Module 2 slice):

    upload -> extraction -> plan build (units, objectives, anchored
    evidence cards) -> print units/objectives/evidence + build report + cost

Runs the real extraction and plan-build jobs directly (bypassing HTTP, same
functions apps/api's routers call) against a real Postgres, so this
exercises the actual persisted pipeline, not a mock. Defaults to the
40-slide synthetic "Computer Networks" deck (tests/fixtures/planbuilder_decks/
networking_101/deck.pdf, tests/fixtures/generate_planbuilder_deck.py);
pass a different PDF path as argv[1] to run it against another deck.

    .venv\\Scripts\\python.exe scripts\\build_plan_demo.py
    .venv\\Scripts\\python.exe scripts\\build_plan_demo.py "C:\\path\\to\\your\\deck.pdf"
"""

from __future__ import annotations

import hashlib
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, text

from apps.api.jobs.extraction import run_extraction_job
from apps.api.jobs.plan_build import is_incomplete, run_plan_build_job
from slidevision.persistence.db import SessionLocal
from slidevision.persistence.enums import DocumentStatus
from slidevision.persistence.models import LlmCall
from slidevision.persistence.repositories import DocumentRepository, PlanRepository

DEFAULT_DECK = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "planbuilder_decks" / "networking_101" / "deck.pdf"
)


def main() -> None:
    deck_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DECK
    if not deck_path.is_file():
        raise SystemExit(f"deck not found: {deck_path}")

    content_hash = hashlib.sha256(deck_path.read_bytes()).hexdigest()

    session = SessionLocal()
    doc_repo = DocumentRepository(session)
    plan_repo = PlanRepository(session)
    try:
        document = doc_repo.get_by_content_hash(content_hash)
        if document is None:
            document = doc_repo.create(
                title=deck_path.name,
                source_filename=deck_path.name,
                mime="application/pdf",
                content_hash=content_hash,
                storage_uri=str(deck_path),
            )
            session.commit()
        else:
            print(f"reusing existing document {document.id} (status={document.status.value})")

        if document.status != DocumentStatus.READY:
            print("running extraction...")
            run_extraction_job(document.id, deck_path)
            session.expire_all()
            document = doc_repo.get(document.id)
        if document.status != DocumentStatus.READY:
            raise SystemExit(f"extraction did not succeed: status={document.status.value} error={document.error}")

        blocks = doc_repo.get_blocks(document.id)
        expected_slide_ids = sorted({block.slide_no for block in blocks})
        print(f"document {document.id}: {len(blocks)} blocks across {len(expected_slide_ids)} slides")

        latest = plan_repo.latest_version(document.id)
        if latest is not None and is_incomplete(latest):
            # same resume rule as apps/api/routers/plans.py -- don't abandon
            # a mid-build draft (e.g. a previous killed/crashed run) by
            # starting a fresh version on top of it.
            plan = latest
            print(f"resuming incomplete plan {plan.id} (v{plan.version})")
        else:
            next_version = (latest.version + 1) if latest is not None else 1
            plan = plan_repo.create_plan(document_id=document.id, version=next_version)
            session.commit()
        plan_id = plan.id
        plan_version = plan.version
    finally:
        session.close()

    print(f"building plan {plan_id} (version {plan_version})...")
    job_started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    evidence_report = run_plan_build_job(plan_id)
    elapsed_s = time.perf_counter() - started

    session = SessionLocal()
    try:
        plan = PlanRepository(session).get_plan(plan_id)
        units = sorted(plan.units, key=lambda unit: unit.order_index)

        got_slide_ids = sorted({slide_id for unit in units for slide_id in unit.slide_ids})
        partition_ok = got_slide_ids == expected_slide_ids

        print("\n=== Partition check ===")
        print(f"expected slides: {expected_slide_ids}")
        print(f"covered slides:  {got_slide_ids}")
        print(f"complete, no gaps/overlaps: {partition_ok}")
        assert partition_ok, "slide partition is incomplete or overlapping"

        print(f"\n=== Plan {plan.id} (v{plan.version}, model={plan.model}, "
              f"prompt_version={plan.builder_prompt_version}) ===")
        print(f"{len(units)} units, built in {elapsed_s:.1f}s")
        for unit in units:
            objectives = sorted(unit.objectives, key=lambda o: o.order_index)
            print(f"\n[{unit.order_index + 1}] {unit.title}  (slides {unit.slide_ids})")
            if unit.summary:
                print(f"    {unit.summary}")
            for objective in objectives:
                flag = " [low_confidence]" if objective.low_confidence else ""
                print(f"    - {objective.statement}{flag} ({len(objective.expected_ideas)} anchored ideas)")

        stmt = (
            select(LlmCall)
            .where(LlmCall.created_at >= job_started_at, LlmCall.purpose == "plan")
            .order_by(LlmCall.created_at)
        )
        calls = list(session.scalars(stmt))
        total_input = sum(call.input_tokens or 0 for call in calls)
        total_output = sum(call.output_tokens or 0 for call in calls)
        priced_calls = [call for call in calls if call.cost_usd is not None]
        prompt_versions = sorted({f"{call.prompt_id}/{call.prompt_version}" for call in calls})
        ok_calls = sum(1 for call in calls if call.ok)

        print("\n=== llm_calls ===")
        print(f"{len(calls)} rows ({ok_calls} ok), prompt versions used: {prompt_versions}")
        print(f"total tokens: {total_input} in / {total_output} out")
        if priced_calls:
            print(f"total logged cost: ${sum(call.cost_usd for call in priced_calls):.4f}")
        else:
            print("total logged cost: NULL for every call (no LLM_COST_RATE_* configured — never guessed)")

        # --- Evidence-card build report (packages/planbuilder/validate.py) ---
        print("\n=== Evidence build report ===")
        if evidence_report is None:
            print("run_plan_build_job returned None (job failed before/after evidence stage — see logs)")
        else:
            for line in evidence_report.summary_lines():
                print(line)

            dropped = evidence_report.dropped_examples(limit=8)
            if dropped:
                print(f"\nsample dropped ideas ({len(dropped)} of {evidence_report.total_dropped} shown):")
                for objective_statement, idea in dropped:
                    print(f"  [{idea.reason}] objective={objective_statement!r}")
                    print(f"      idea={idea.idea!r}")
                    print(f"      quote={idea.quote!r}")

        # --- SQL invariant checks ---
        print("\n=== SQL invariant checks ===")
        null_block_count = session.execute(
            text("SELECT count(*) FROM objective_expected_ideas WHERE block_id IS NULL")
        ).scalar_one()
        print(f"objective_expected_ideas.block_id IS NULL: {null_block_count} -> {'OK' if null_block_count == 0 else 'FAIL'}")

        model_generated_anchor_count = session.execute(
            text(
                "SELECT count(*) FROM objective_expected_ideas i "
                "JOIN document_blocks b ON i.block_id = b.id "
                "WHERE b.provenance = 'model_generated'"
            )
        ).scalar_one()
        print(
            f"ideas anchored to a model_generated block: {model_generated_anchor_count} -> "
            f"{'OK' if model_generated_anchor_count == 0 else 'FAIL'}"
        )

        round_trip_mismatches = session.execute(
            text(
                "SELECT count(*) FROM objective_expected_ideas i "
                "JOIN document_blocks b ON i.block_id = b.id "
                "WHERE i.char_start < 0 OR i.char_end > length(b.text) OR i.char_start >= i.char_end"
            )
        ).scalar_one()
        print(
            f"ideas whose (char_start, char_end) don't fit inside their block's text: {round_trip_mismatches} -> "
            f"{'OK' if round_trip_mismatches == 0 else 'FAIL'}"
        )

        # --- Acceptance: >=80% of objectives have >=2 anchored ideas ---
        all_objectives = [objective for unit in units for objective in unit.objectives]
        ge2 = sum(1 for objective in all_objectives if len(objective.expected_ideas) >= 2)
        ratio = ge2 / len(all_objectives) if all_objectives else 0.0
        print("\n=== Acceptance ===")
        print(f"units in [6,15]: {len(units)} -> {'OK' if 6 <= len(units) <= 15 else 'CHECK'}")
        print(f"under 3 minutes: {elapsed_s:.1f}s -> {'OK' if elapsed_s < 180 else 'CHECK'}")
        print(
            f"objectives with >=2 anchored ideas: {ge2}/{len(all_objectives)} ({ratio:.0%}) -> "
            f"{'OK' if ratio >= 0.80 else 'BELOW 80% TARGET'}"
        )

        # --- 5 example evidence cards, with the actual quoted source text ---
        blocks_by_id = {block.id: block.text for block in blocks}
        print("\n=== 5 example evidence cards ===")
        shown = 0
        for unit in units:
            for objective in sorted(unit.objectives, key=lambda o: o.order_index):
                if not objective.expected_ideas or shown >= 5:
                    continue
                shown += 1
                print(f"\n--- Example {shown}: {objective.statement} ---")
                for idea in sorted(objective.expected_ideas, key=lambda i: i.idea):
                    block_text = blocks_by_id.get(idea.block_id, "")
                    quoted = block_text[idea.char_start : idea.char_end]
                    print(f"  idea: {idea.idea}")
                    print(f"    anchored quote (block {idea.block_id}, chars {idea.char_start}-{idea.char_end}):")
                    print(f"    {quoted!r}")
                if objective.misconceptions:
                    print("  misconceptions:")
                    for m in objective.misconceptions:
                        print(f"    - [{m.code}] {m.text}")
                if objective.prerequisite_objective_ids:
                    print(f"  prerequisites: {[str(pid) for pid in objective.prerequisite_objective_ids]}")
            if shown >= 5:
                break
    finally:
        session.close()


if __name__ == "__main__":
    main()
