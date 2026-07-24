from slidevision.planbuilder.anchor import Anchor, AnchoringToModelGeneratedBlockError, resolve_anchor
from slidevision.planbuilder.errors import PartitionError
from slidevision.planbuilder.evidence import EvidenceCardDraft, ExpectedIdeaDraft, MisconceptionDraft, build_evidence_card
from slidevision.planbuilder.objectives import ObjectiveDraft, build_objectives, looks_like_pure_recall
from slidevision.planbuilder.segment import UnitDraft, build_units, validate_partition
from slidevision.planbuilder.slides import SlideSummary, SourceBlock, build_slide_summaries, format_slide_entries
from slidevision.planbuilder.validate import (
    AnchoredIdea,
    DroppedIdea,
    EvidenceBuildReport,
    ObjectiveEvidenceResult,
    PriorObjectiveRef,
    build_and_validate_evidence,
    citable_blocks_for_slides,
)

__all__ = [
    "PartitionError",
    "SourceBlock",
    "SlideSummary",
    "build_slide_summaries",
    "format_slide_entries",
    "UnitDraft",
    "build_units",
    "validate_partition",
    "ObjectiveDraft",
    "build_objectives",
    "looks_like_pure_recall",
    "Anchor",
    "AnchoringToModelGeneratedBlockError",
    "resolve_anchor",
    "EvidenceCardDraft",
    "ExpectedIdeaDraft",
    "MisconceptionDraft",
    "build_evidence_card",
    "PriorObjectiveRef",
    "AnchoredIdea",
    "DroppedIdea",
    "ObjectiveEvidenceResult",
    "EvidenceBuildReport",
    "build_and_validate_evidence",
    "citable_blocks_for_slides",
]
