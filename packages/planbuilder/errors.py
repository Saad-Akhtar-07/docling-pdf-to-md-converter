"""Typed errors for packages/planbuilder."""

from __future__ import annotations


class PartitionError(ValueError):
    """The model's proposed units don't partition the deck's slides:
    some slide_no is missing, duplicated across units, or doesn't exist.
    Raised after the retry in segment.py has also failed — callers (the
    plan-build job) catch this and leave the plan in its current, resumable
    draft state rather than persisting a partition they can't trust."""

    def __init__(self, *, missing: list[int], duplicated: list[int], unknown: list[int]) -> None:
        self.missing = missing
        self.duplicated = duplicated
        self.unknown = unknown
        parts = []
        if missing:
            parts.append(f"missing slides {missing}")
        if duplicated:
            parts.append(f"slides in more than one unit {duplicated}")
        if unknown:
            parts.append(f"slide numbers that don't exist in this deck {unknown}")
        super().__init__("invalid unit partition: " + "; ".join(parts))
