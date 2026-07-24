"""Unit tests for packages/tutor_core/consistency.py -- Module 5's
deterministic repairs (docs/ARCHITECTURE_REVIEW_AND_ROADMAP.md §1.9).

Pure functions, no DB/LLM/fixtures beyond plain models -- every rule is
tested for both the case where it fires and the case where it does not
(the "both directions" the module prompt asks for), plus the ordering
guarantee that later rules see earlier rules' output.
"""

from __future__ import annotations

from slidevision.tutor_core.consistency import (
    apply_consistency_rules,
    repair_assessment,
    repair_evidence_quote,
    repair_idea_references,
    repair_misconception_reference,
)
from slidevision.tutor_core.models import EvidenceCard, EvidenceIdea, EvidenceMisconception, ObjectiveAssessment


def _assessment(**overrides) -> ObjectiveAssessment:
    defaults = dict(verdict="correct", objective_met=True, reasoning_depth="adequate")
    defaults.update(overrides)
    return ObjectiveAssessment(**defaults)


# --- repair_idea_references -------------------------------------------------


def test_invented_matched_idea_id_is_dropped():
    a = _assessment(matched_idea_ids=["idea_1", "idea_99"])
    repaired, repairs = repair_idea_references(a, {"idea_1", "idea_2"})

    assert repaired.matched_idea_ids == ["idea_1"]
    assert len(repairs) == 1
    assert repairs[0].rule == "invented_idea_id"
    assert repairs[0].field == "matched_idea_ids"
    assert repairs[0].before == ["idea_1", "idea_99"]
    assert repairs[0].after == ["idea_1"]


def test_invented_missing_idea_id_is_dropped():
    a = _assessment(missing_idea_ids=["idea_2", "ghost_idea"])
    repaired, repairs = repair_idea_references(a, {"idea_1", "idea_2"})

    assert repaired.missing_idea_ids == ["idea_2"]
    assert len(repairs) == 1
    assert repairs[0].field == "missing_idea_ids"


def test_all_real_idea_ids_are_left_untouched():
    a = _assessment(matched_idea_ids=["idea_1"], missing_idea_ids=["idea_2"])
    repaired, repairs = repair_idea_references(a, {"idea_1", "idea_2"})

    assert repaired.matched_idea_ids == ["idea_1"]
    assert repaired.missing_idea_ids == ["idea_2"]
    assert repairs == []
    assert repaired is a  # no-op returns the original instance, not a copy


# --- repair_evidence_quote ---------------------------------------------------


def test_quote_not_a_substring_of_the_answer_is_cleared():
    a = _assessment(evidence_quote="the mapper emits keys")
    repaired, repairs = repair_evidence_quote(a, "I think it just sorts stuff")

    assert repaired.evidence_quote is None
    assert len(repairs) == 1
    assert repairs[0].rule == "evidence_quote_not_substring"
    assert repairs[0].before == "the mapper emits keys"
    assert repairs[0].after is None


def test_quote_that_is_a_real_substring_is_kept():
    a = _assessment(evidence_quote="the mapper emits keys")
    repaired, repairs = repair_evidence_quote(a, "I think the mapper emits keys for each record")

    assert repaired.evidence_quote == "the mapper emits keys"
    assert repairs == []


def test_no_quote_is_a_no_op():
    a = _assessment(evidence_quote=None)
    repaired, repairs = repair_evidence_quote(a, "some answer")

    assert repaired.evidence_quote is None
    assert repairs == []


# --- repair_misconception_reference -----------------------------------------


def test_unknown_misconception_id_moves_to_novel_text():
    a = _assessment(misconception_id="shuffle_is_reduce")
    repaired, repairs = repair_misconception_reference(a, {"other_code"})

    assert repaired.misconception_id is None
    assert repaired.misconception_novel_text == "shuffle_is_reduce"
    assert len(repairs) == 1
    assert repairs[0].rule == "misconception_not_in_card"
    assert repairs[0].before == "shuffle_is_reduce"
    assert repairs[0].after is None


def test_known_misconception_id_is_left_untouched():
    a = _assessment(misconception_id="shuffle_is_reduce")
    repaired, repairs = repair_misconception_reference(a, {"shuffle_is_reduce"})

    assert repaired.misconception_id == "shuffle_is_reduce"
    assert repaired.misconception_novel_text is None
    assert repairs == []


def test_no_misconception_id_is_a_no_op():
    a = _assessment(misconception_id=None)
    repaired, repairs = repair_misconception_reference(a, {"shuffle_is_reduce"})

    assert repaired.misconception_id is None
    assert repairs == []


# --- apply_consistency_rules: rule 1 (correct + missing ideas -> partial) --


def test_rule1_correct_with_missing_ideas_downgrades_to_partial():
    a = _assessment(verdict="correct", missing_idea_ids=["idea_2"])
    repaired, repairs = apply_consistency_rules(a, "a reasonably long answer here", set())

    assert repaired.verdict == "partial"
    assert any(r.rule == "correct_with_missing_ideas" for r in repairs)


def test_rule1_correct_with_no_missing_ideas_is_untouched():
    a = _assessment(verdict="correct", missing_idea_ids=[])
    repaired, repairs = apply_consistency_rules(a, "a reasonably long answer here", set())

    assert repaired.verdict == "correct"
    assert not any(r.rule == "correct_with_missing_ideas" for r in repairs)


# --- apply_consistency_rules: rule 2 (objective_met + bad verdict) ---------


def test_rule2_objective_met_true_with_incorrect_verdict_is_forced_false():
    a = _assessment(verdict="incorrect", objective_met=True)
    repaired, repairs = apply_consistency_rules(a, "a reasonably long answer here", set())

    assert repaired.objective_met is False
    assert any(r.rule == "objective_met_verdict_mismatch" for r in repairs)


def test_rule2_objective_met_true_with_correct_verdict_is_untouched():
    a = _assessment(verdict="correct", objective_met=True, missing_idea_ids=[])
    repaired, repairs = apply_consistency_rules(a, "a reasonably long answer here", set())

    assert repaired.objective_met is True
    assert not any(r.rule == "objective_met_verdict_mismatch" for r in repairs)


# --- apply_consistency_rules: rule 3 (short answer can't be deep) ---------


def test_rule3_short_answer_with_deep_depth_is_downgraded_to_shallow():
    a = _assessment(verdict="partial", objective_met=False, reasoning_depth="deep")
    repaired, repairs = apply_consistency_rules(a, "yes ok", set())

    assert repaired.reasoning_depth == "shallow"
    assert any(r.rule == "short_answer_deep_depth" for r in repairs)


def test_rule3_long_answer_with_deep_depth_is_untouched():
    a = _assessment(verdict="partial", objective_met=False, reasoning_depth="deep")
    repaired, repairs = apply_consistency_rules(a, "this is a reasonably long and detailed answer", set())

    assert repaired.reasoning_depth == "deep"
    assert not any(r.rule == "short_answer_deep_depth" for r in repairs)


# --- apply_consistency_rules: rule 4 (misconception not in card) ----------


def test_rule4_unknown_misconception_is_flagged_novel():
    a = _assessment(verdict="incorrect", objective_met=False, misconception_id="made_up_code")
    repaired, repairs = apply_consistency_rules(a, "a reasonably long answer here", {"real_code"})

    assert repaired.misconception_id is None
    assert repaired.misconception_novel_text == "made_up_code"
    assert any(r.rule == "misconception_not_in_card" for r in repairs)


def test_rule4_known_misconception_is_untouched():
    a = _assessment(verdict="incorrect", objective_met=False, misconception_id="real_code")
    repaired, repairs = apply_consistency_rules(a, "a reasonably long answer here", {"real_code"})

    assert repaired.misconception_id == "real_code"
    assert not any(r.rule == "misconception_not_in_card" for r in repairs)


def test_a_fully_consistent_assessment_produces_no_repairs():
    a = _assessment(
        verdict="partial",
        objective_met=False,
        reasoning_depth="adequate",
        missing_idea_ids=["idea_2"],
        misconception_id="real_code",
    )
    repaired, repairs = apply_consistency_rules(a, "a reasonably long and adequate answer", {"real_code"})

    assert repaired == a
    assert repairs == []


def test_rules_apply_in_order_each_seeing_the_previous_repair():
    """verdict starts 'correct' with missing ideas (rule 1 fires ->
    'partial'), and objective_met=True -- rule 2 checks against the
    ALREADY-downgraded verdict. 'partial' isn't in the rule-2 trigger set,
    so objective_met should survive untouched here, proving rule 2 reads
    rule 1's output rather than the original input."""
    a = _assessment(verdict="correct", objective_met=True, missing_idea_ids=["idea_2"])
    repaired, repairs = apply_consistency_rules(a, "a reasonably long answer here", set())

    assert repaired.verdict == "partial"
    assert repaired.objective_met is True  # rule 2 did not fire against 'partial'
    rule_names = [r.rule for r in repairs]
    assert rule_names == ["correct_with_missing_ideas"]


# --- repair_assessment: full pipeline ---------------------------------------


def _card() -> EvidenceCard:
    return EvidenceCard(
        objective_id="obj_1",
        expected_ideas=[EvidenceIdea(id="idea_1", idea="mapper emits keys"), EvidenceIdea(id="idea_2", idea="shuffle groups by key")],
        known_misconceptions=[EvidenceMisconception(code="shuffle_is_reduce", text="shuffle performs the reduction itself")],
    )


def test_repair_assessment_runs_structural_repairs_before_consistency_rules():
    """An invented idea id makes missing_idea_ids non-empty only after
    structural repair -- if repair_assessment ran the rules before the
    structural pass, rule 1 (correct + missing -> partial) wouldn't see it
    correctly reflect the card. This asserts the pipeline order end to end."""
    a = _assessment(
        verdict="correct",
        matched_idea_ids=["idea_1"],
        missing_idea_ids=["idea_2", "not_a_real_id"],
        evidence_quote="something the student never said",
        misconception_id="unknown_code",
    )
    final, repairs = repair_assessment(a, card=_card(), student_answer="mapper emits keys I think")

    assert final.missing_idea_ids == ["idea_2"]  # invented id dropped
    assert final.evidence_quote is None  # not a substring of the answer
    assert final.verdict == "partial"  # rule 1: correct + missing -> partial
    assert final.misconception_id is None
    assert final.misconception_novel_text == "unknown_code"

    rule_names = {r.rule for r in repairs}
    assert "invented_idea_id" in rule_names
    assert "evidence_quote_not_substring" in rule_names
    assert "correct_with_missing_ideas" in rule_names
    assert "misconception_not_in_card" in rule_names


def test_repair_assessment_is_a_no_op_for_a_clean_assessment():
    a = _assessment(
        verdict="correct",
        matched_idea_ids=["idea_1", "idea_2"],
        missing_idea_ids=[],
        evidence_quote="mapper emits keys",
        reasoning_depth="adequate",
    )
    final, repairs = repair_assessment(a, card=_card(), student_answer="the mapper emits keys for each record")

    assert final == a
    assert repairs == []
