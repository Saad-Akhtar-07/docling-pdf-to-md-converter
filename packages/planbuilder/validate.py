"""The evidence-card gate: docs/ARCHITECTURE_REVIEW_AND_ROADMAP.md §2.6
Stage 5. "Drop unanchored ideas. Flag objectives with fewer than two ideas
as low_confidence... Never anchor to a model_generated block."

Orchestrates evidence.py (LLM call) -> anchor.py (quote -> real span, or
None) per objective, and rolls the results into a build report so a human
can tell whether a low anchor rate is a prompt problem (the model isn't
quoting verbatim) or a source-material problem (the slides genuinely don't
contain much quotable, atomic content) rather than just lowering the
fuzzy-match threshold until the numbers look better.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from slidevision.planbuilder.anchor import MIN_QUOTE_CHARS, resolve_anchor
from slidevision.planbuilder.evidence import MisconceptionDraft, build_evidence_card
from slidevision.planbuilder.slides import CITABLE_PROVENANCE, SlideSummary, SourceBlock

logger = logging.getLogger(__name__)


@dataclass
class PriorObjectiveRef:
    index: int
    objective_id: uuid.UUID
    statement: str


@dataclass
class AnchoredIdea:
    idea: str
    block_id: str
    char_start: int
    char_end: int


@dataclass
class DroppedIdea:
    idea: str
    quote: str
    reason: str  # "quote_too_short" | "no_match_above_threshold"


@dataclass
class ObjectiveEvidenceResult:
    objective_id: uuid.UUID
    objective_statement: str
    anchored_ideas: list[AnchoredIdea] = field(default_factory=list)
    dropped_ideas: list[DroppedIdea] = field(default_factory=list)
    misconceptions: list[MisconceptionDraft] = field(default_factory=list)
    prerequisite_objective_ids: list[uuid.UUID] = field(default_factory=list)

    @property
    def low_confidence(self) -> bool:
        return len(self.anchored_ideas) < 2

    @property
    def zero_ideas(self) -> bool:
        return len(self.anchored_ideas) == 0


def citable_blocks_for_slides(blocks: list[SourceBlock], slide_ids: set[int]) -> list[SourceBlock]:
    return [block for block in blocks if block.slide_no in slide_ids and block.provenance in CITABLE_PROVENANCE]


def build_and_validate_evidence(
    objective_id: uuid.UUID,
    objective_statement: str,
    unit_slides: list[SlideSummary],
    citable_blocks: list[SourceBlock],
    prior_objectives: list[PriorObjectiveRef],
) -> ObjectiveEvidenceResult:
    """One objective's full evidence pipeline: LLM draft -> per-idea anchor
    resolution -> drop what doesn't anchor. Never raises for a bad
    idea/quote (that's the drop path); only propagates real failures
    (LLM/transport errors) to the caller."""
    prompt_context = [(ref.index, ref.statement) for ref in prior_objectives]
    draft = build_evidence_card(objective_statement, unit_slides, prompt_context)

    result = ObjectiveEvidenceResult(objective_id=objective_id, objective_statement=objective_statement)

    for idea_draft in draft.expected_ideas:
        quote = idea_draft.quote.strip()
        if len(quote) < MIN_QUOTE_CHARS:
            result.dropped_ideas.append(DroppedIdea(idea=idea_draft.idea, quote=idea_draft.quote, reason="quote_too_short"))
            logger.info("dropped idea (quote too short) for objective %s: idea=%r quote=%r", objective_id, idea_draft.idea, idea_draft.quote)
            continue

        anchor = resolve_anchor(quote, citable_blocks)
        if anchor is None:
            result.dropped_ideas.append(
                DroppedIdea(idea=idea_draft.idea, quote=idea_draft.quote, reason="no_match_above_threshold")
            )
            logger.info(
                "dropped unanchored idea for objective %s: idea=%r quote=%r", objective_id, idea_draft.idea, idea_draft.quote
            )
            continue

        result.anchored_ideas.append(
            AnchoredIdea(idea=idea_draft.idea, block_id=anchor.block_id, char_start=anchor.char_start, char_end=anchor.char_end)
        )

    result.misconceptions = draft.known_misconceptions

    index_to_objective_id = {ref.index: ref.objective_id for ref in prior_objectives}
    result.prerequisite_objective_ids = [
        index_to_objective_id[index] for index in draft.prerequisite_indices if index in index_to_objective_id
    ]

    return result


@dataclass
class EvidenceBuildReport:
    results: list[ObjectiveEvidenceResult] = field(default_factory=list)

    @property
    def total_objectives(self) -> int:
        return len(self.results)

    @property
    def total_ideas_generated(self) -> int:
        return sum(len(r.anchored_ideas) + len(r.dropped_ideas) for r in self.results)

    @property
    def total_anchored(self) -> int:
        return sum(len(r.anchored_ideas) for r in self.results)

    @property
    def total_dropped(self) -> int:
        return sum(len(r.dropped_ideas) for r in self.results)

    @property
    def objectives_with_ge2_anchored(self) -> int:
        return sum(1 for r in self.results if len(r.anchored_ideas) >= 2)

    @property
    def objectives_with_zero_ideas(self) -> int:
        return sum(1 for r in self.results if r.zero_ideas)

    @property
    def ge2_ratio(self) -> float:
        return self.objectives_with_ge2_anchored / self.total_objectives if self.results else 0.0

    @property
    def anchor_rate(self) -> float:
        total = self.total_ideas_generated
        return self.total_anchored / total if total else 0.0

    def dropped_examples(self, limit: int = 10) -> list[tuple[str, DroppedIdea]]:
        examples = []
        for r in self.results:
            for dropped in r.dropped_ideas:
                examples.append((r.objective_statement, dropped))
        return examples[:limit]

    def summary_lines(self) -> list[str]:
        return [
            f"objectives: {self.total_objectives}",
            f"ideas generated: {self.total_ideas_generated}, anchored: {self.total_anchored}, "
            f"dropped: {self.total_dropped} (anchor rate {self.anchor_rate:.0%})",
            f"objectives with >=2 anchored ideas: {self.objectives_with_ge2_anchored}/{self.total_objectives} "
            f"({self.ge2_ratio:.0%})",
            f"objectives with zero anchored ideas (flagged for review): {self.objectives_with_zero_ideas}",
        ]
