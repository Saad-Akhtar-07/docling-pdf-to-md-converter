"""Acceptance demo for packages/llm (Step 2 VERIFY):

    complete(purpose="plan", schema=SomeModel) -> validated object, with a
    row in llm_calls.

Runs one real structured call against the OpenCode Zen gateway (purpose
"plan" -> LLM_PURPOSE_PLAN -> LLM_MODEL_REASONING -> deepseek-v4-pro) using
the packages/llm/prompts/example/v1.md prompt and a 3-field Pydantic
schema, then reads the row it wrote back from Postgres and prints it.
"""

from __future__ import annotations

from pydantic import BaseModel

from slidevision.llm import complete
from slidevision.llm.prompts import load_prompt
from slidevision.persistence.db import get_session
from slidevision.persistence.repositories.llm_calls import LlmCallRepository


class Fact(BaseModel):
    subject: str
    predicate: str
    object: str


def main() -> None:
    prompt_id, prompt_version = "example", "v1"
    system_prompt = load_prompt(prompt_id, prompt_version)

    result = complete(
        purpose="plan",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Subject: the Eiffel Tower."},
        ],
        schema=Fact,
        prompt_id=prompt_id,
        prompt_version=prompt_version,
    )

    print("=== complete() result ===")
    print(f"model:   {result.model}")
    print(f"parsed:  {result.parsed!r}")
    print(f"usage:   {result.usage}")
    print(f"call id: {result.llm_call_id}")

    db_session = get_session()
    try:
        row = LlmCallRepository(db_session).get(result.llm_call_id)
        print("\n=== llm_calls row ===")
        for column in [
            "id",
            "session_id",
            "turn_id",
            "purpose",
            "provider",
            "model",
            "prompt_id",
            "prompt_version",
            "input_tokens",
            "output_tokens",
            "latency_ms",
            "cost_usd",
            "ok",
            "error",
            "created_at",
        ]:
            print(f"{column:>14}: {getattr(row, column)}")
    finally:
        db_session.close()


if __name__ == "__main__":
    main()
