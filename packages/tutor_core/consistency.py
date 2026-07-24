"""Deterministic assessment repairs -- docs/ARCHITECTURE_REVIEW_AND_ROADMAP.md
§1.9: "An LLM refereeing an LLM is not validation." Replace a second LLM
call with pure, testable rules instead.

Two kinds of repair live here, both pure (no LLM/HTTP/DB -- CLAUDE.md
invariant #2):

- `repair_idea_references` / `repair_evidence_quote`: structural repairs for
  claims the model has no business making up -- an idea id that isn't on
  the card, or a quote that isn't actually in the student's answer. Applied
  right after parsing, before the assessment is trusted for anything else.
- `apply_consistency_rules`: exactly the four rules from §1.9 -- internal
  contradictions within an otherwise well-formed assessment (a "correct"
  verdict that also lists missing ideas, etc).

Every repair returns a `ConsistencyRepair` recording rule/field/before/after
so the caller can write it to a CONSISTENCY_REPAIR turn_event; nothing here
touches the event log itself.
"""

from __future__ import annotations

from slidevision.tutor_core.models import ConsistencyRepair, EvidenceCard, ObjectiveAssessment

_INCORRECT_VERDICTS = {"incorrect", "confused", "dont_know"}


def repair_idea_references(
    assessment: ObjectiveAssessment, known_idea_ids: set[str]
) -> tuple[ObjectiveAssessment, list[ConsistencyRepair]]:
    """Drops any matched_idea_ids/missing_idea_ids the model invented --
    ids that don't correspond to a real idea on this objective's card."""
    repairs: list[ConsistencyRepair] = []
    updates: dict[str, list[str]] = {}

    for field in ("matched_idea_ids", "missing_idea_ids"):
        original = getattr(assessment, field)
        kept = [idea_id for idea_id in original if idea_id in known_idea_ids]
        if kept != original:
            repairs.append(
                ConsistencyRepair(rule="invented_idea_id", field=field, before=original, after=kept)
            )
            updates[field] = kept

    if not updates:
        return assessment, repairs
    return assessment.model_copy(update=updates), repairs


def repair_evidence_quote(
    assessment: ObjectiveAssessment, student_answer: str
) -> tuple[ObjectiveAssessment, list[ConsistencyRepair]]:
    """Clears evidence_quote unless it is an exact substring of the
    student's own answer -- it must never be attributable to the model
    instead of the student."""
    quote = assessment.evidence_quote
    if quote is None or quote in student_answer:
        return assessment, []

    repair = ConsistencyRepair(rule="evidence_quote_not_substring", field="evidence_quote", before=quote, after=None)
    return assessment.model_copy(update={"evidence_quote": None}), [repair]


def repair_misconception_reference(
    assessment: ObjectiveAssessment, known_misconception_codes: set[str]
) -> tuple[ObjectiveAssessment, list[ConsistencyRepair]]:
    """misconception_id must be from the card's known list, OR
    misconception_novel_text is set instead -- never both, never an
    unrecognised id left standing. An unrecognised misconception is a
    research signal (the card is incomplete), not silently discarded: it
    moves into misconception_novel_text so it's visible in the event log."""
    misconception_id = assessment.misconception_id
    if misconception_id is None or misconception_id in known_misconception_codes:
        return assessment, []

    repair = ConsistencyRepair(
        rule="misconception_not_in_card",
        field="misconception_id",
        before=misconception_id,
        after=None,
    )
    return (
        assessment.model_copy(update={"misconception_id": None, "misconception_novel_text": misconception_id}),
        [repair],
    )


def apply_consistency_rules(
    assessment: ObjectiveAssessment,
    student_answer: str,
    known_misconception_codes: set[str],
) -> tuple[ObjectiveAssessment, list[ConsistencyRepair]]:
    """Exactly the four rules from §1.9, applied in order -- each rule sees
    the (possibly already-repaired) output of the rule before it."""
    repairs: list[ConsistencyRepair] = []
    a = assessment

    if a.verdict == "correct" and a.missing_idea_ids:
        repairs.append(ConsistencyRepair(rule="correct_with_missing_ideas", field="verdict", before="correct", after="partial"))
        a = a.model_copy(update={"verdict": "partial"})

    if a.objective_met and a.verdict in _INCORRECT_VERDICTS:
        repairs.append(
            ConsistencyRepair(rule="objective_met_verdict_mismatch", field="objective_met", before=True, after=False)
        )
        a = a.model_copy(update={"objective_met": False})

    if len(student_answer.split()) < 4 and a.reasoning_depth == "deep":
        repairs.append(
            ConsistencyRepair(rule="short_answer_deep_depth", field="reasoning_depth", before="deep", after="shallow")
        )
        a = a.model_copy(update={"reasoning_depth": "shallow"})

    a, misconception_repairs = repair_misconception_reference(a, known_misconception_codes)
    repairs.extend(misconception_repairs)

    return a, repairs


def repair_assessment(
    assessment: ObjectiveAssessment, *, card: EvidenceCard, student_answer: str
) -> tuple[ObjectiveAssessment, list[ConsistencyRepair]]:
    """The full repair pipeline, in order: structural id/quote repairs
    first (claims the model has no business making up), then the four
    §1.9 consistency rules (internal contradictions in an otherwise
    well-formed assessment). This is node 5 (`consistency_check`, §2.7) --
    pure, no LLM/DB, entirely deterministic given its inputs."""
    a, id_repairs = repair_idea_references(assessment, card.known_idea_ids())
    a, quote_repairs = repair_evidence_quote(a, student_answer)
    a, rule_repairs = apply_consistency_rules(a, student_answer, card.known_misconception_codes())
    return a, id_repairs + quote_repairs + rule_repairs
