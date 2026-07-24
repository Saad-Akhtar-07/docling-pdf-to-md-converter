"""Offline unit tests for packages/planbuilder/objectives.py's code-level
post-check on pure-recall objectives — it must not just trust the model's
own self-reported `is_recall_only` flag (CLAUDE.md: "encode this as an
explicit prompt constraint AND a post-check")."""

from __future__ import annotations

from slidevision.planbuilder.objectives import ObjectiveDraft, filter_recall_only, looks_like_pure_recall


def test_looks_like_pure_recall_flags_definition_recall():
    assert looks_like_pure_recall("Student can define what a subnet mask is") is True
    assert looks_like_pure_recall("Student can list the seven OSI layers in order") is True


def test_looks_like_pure_recall_allows_reasoning_verbs():
    assert looks_like_pure_recall("Student can explain why TCP uses a three-way handshake") is False
    assert looks_like_pure_recall("Student can compare distance-vector and link-state routing") is False


def test_looks_like_pure_recall_catches_a_definition_verb_the_model_mislabeled():
    # the model claims this is reasoning-level (is_recall_only=False), but the
    # statement itself is pure recall with no reasoning cue -- the heuristic
    # must catch what the model's own flag missed.
    assert looks_like_pure_recall("Student can name the four TCP/IP layers") is True


def test_filter_recall_only_drops_recall_objectives_when_alternatives_exist():
    objectives = [
        ObjectiveDraft(statement="Student can define a VLAN", is_recall_only=True),
        ObjectiveDraft(statement="Student can explain why VLANs improve security", is_recall_only=False),
        ObjectiveDraft(statement="Student can compare VLAN trunking to routing", is_recall_only=False),
    ]
    result = filter_recall_only(objectives)
    assert len(result) == 2
    assert all(not looks_like_pure_recall(o.statement) for o in result)


def test_filter_recall_only_keeps_everything_when_no_reasoning_alternative_exists():
    # every objective is recall-only -- nothing better to fall back to, so
    # CLAUDE.md's "when the unit supports a reasoning-level objective" caveat
    # means we must NOT drop down to zero objectives.
    objectives = [
        ObjectiveDraft(statement="Student can define a MAC address", is_recall_only=True),
        ObjectiveDraft(statement="Student can name the OSI layers", is_recall_only=True),
    ]
    result = filter_recall_only(objectives)
    assert result == objectives


def test_filter_recall_only_caps_at_four():
    objectives = [
        ObjectiveDraft(statement=f"Student can explain reasoning point {i}", is_recall_only=False) for i in range(6)
    ]
    result = filter_recall_only(objectives)
    assert len(result) == 4
