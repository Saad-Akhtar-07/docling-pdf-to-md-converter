"""Prompt registry: prompts/<id>/v<n>.md, loaded by (id, version).

Each call to complete() records which (prompt_id, prompt_version) produced
its messages (packages/llm/logging.py), so prompt changes are reproducible
and auditable per docs/ARCHITECTURE_REVIEW_AND_ROADMAP.md §2.5 rule 3.

Real tutoring prompts (assess_response, plan_segment, ...) belong to the
modules that own that pedagogy — packages/llm only owns the loading
mechanism. `example/v1.md` here is scaffolding to exercise the mechanism
and the structured-output pipeline end to end.
"""

from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent


class PromptNotFoundError(FileNotFoundError):
    pass


def load_prompt(prompt_id: str, version: str) -> str:
    path = _PROMPTS_DIR / prompt_id / f"{version}.md"
    if not path.is_file():
        raise PromptNotFoundError(f"No prompt at prompts/{prompt_id}/{version}.md")
    return path.read_text(encoding="utf-8").strip()
