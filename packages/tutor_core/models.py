"""Pure state models -- docs/ARCHITECTURE_REVIEW_AND_ROADMAP.md §2.9.

No LLM, HTTP, or DB imports anywhere in this module or package (CLAUDE.md
invariant #2), enforced by the tutor-core-isolation contract in
.importlinter. packages/persistence/enums.py keeps its own independent copy
of the overlapping enum values for the same reason, in the other direction
-- see that module's docstring for why the dependency edge stays
one-directional instead of persistence importing these.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Intent(str, Enum):
    ANSWER = "answer"
    QUESTION = "question"
    META = "meta"
    OFF_TASK = "off_task"


class TurnIntent(BaseModel):
    intent: Intent
    meta_command: Literal["repeat", "skip", "slower", "harder", "end"] | None = None


class ObjectiveAssessment(BaseModel):
    verdict: Literal["correct", "partial", "incorrect", "confused", "dont_know"]
    objective_met: bool
    reasoning_depth: Literal["shallow", "adequate", "deep"]
    matched_idea_ids: list[str] = Field(default_factory=list)
    missing_idea_ids: list[str] = Field(default_factory=list)
    misconception_id: str | None = None
    misconception_novel_text: str | None = None
    prerequisite_gap_objective_id: str | None = None
    evidence_quote: str | None = Field(default=None, max_length=200)  # from student answer


class ObjectiveStatus(str, Enum):
    UNSEEN = "unseen"
    PROBING = "probing"
    PARTIAL = "partial"
    MISCONCEPTION = "misconception"
    CONFUSED = "confused"
    RESOLVED = "resolved"
    DEFERRED = "deferred"
    SKIPPED = "skipped"


class PedagogicalAction(str, Enum):
    PROBE = "probe"
    HINT = "hint"
    REPHRASE = "rephrase"
    BRIDGE = "bridge"
    RETEACH = "reteach"
    CHECK_AGAIN = "check_again"
    DEEPEN = "deepen"
    REVISIT_PREREQ = "revisit_prereq"
    ADVANCE = "advance"
    DEFER = "defer"
    ANSWER_QUESTION = "answer_question"
    REDIRECT = "redirect"


class ObjectiveState(BaseModel):
    objective_id: str
    status: ObjectiveStatus = ObjectiveStatus.UNSEEN
    attempts: int = 0
    hint_level: int = 0
    deepen_count: int = 0
    prereq_revisits: int = 0
    met_count: int = 0
    active_misconception_id: str | None = None
    last_action: PedagogicalAction | None = None
    event_ids: list[str] = Field(default_factory=list)


class EvidenceIdea(BaseModel):
    """One expected idea, as presented to the assessment LLM call.

    `id` is a short, stable-within-this-turn local reference ("idea_1",
    "idea_2", ...) assigned in card order by the caller building the card --
    not `objective_expected_ideas.id` (a UUID). Same rationale as
    planbuilder/evidence.py's `prerequisite_indices`: asking a model to
    reliably reproduce a UUID is asking for trouble; asking it to pick from
    a short list is not.
    """

    id: str
    idea: str


class EvidenceMisconception(BaseModel):
    code: str
    text: str


class EvidenceCard(BaseModel):
    """Read-only projection of one objective's evidence card, pure data --
    everything consistency.py needs to validate an ObjectiveAssessment
    against, with no DB/LLM dependency of its own."""

    objective_id: str
    expected_ideas: list[EvidenceIdea] = Field(default_factory=list)
    known_misconceptions: list[EvidenceMisconception] = Field(default_factory=list)

    def known_idea_ids(self) -> set[str]:
        return {idea.id for idea in self.expected_ideas}

    def known_misconception_codes(self) -> set[str]:
        return {m.code for m in self.known_misconceptions}


class ConsistencyRepair(BaseModel):
    """One deterministic correction applied to a raw ObjectiveAssessment --
    docs/ARCHITECTURE_REVIEW_AND_ROADMAP.md §1.9. Written to a
    CONSISTENCY_REPAIR turn_event with `before`/`after` so every repair is
    auditable after the fact."""

    rule: str
    field: str
    before: str | list[str] | bool | None
    after: str | list[str] | bool | None
