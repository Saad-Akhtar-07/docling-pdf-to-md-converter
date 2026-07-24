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
