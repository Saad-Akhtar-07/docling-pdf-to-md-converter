# Adaptive ITS — Architecture Review & Implementation Roadmap

**Project:** An Adaptive AI-Powered Intelligent Tutoring System for Personalized Active Learning
**Document version:** 1.0
**Date:** 23 July 2026
**Status:** Pre-Module-1 architecture freeze

---

# Part 0 — Reading the current repository

Before critiquing the design on paper, some observations from the actual repo state, because several of them are load-bearing.

| Observation | Why it matters |
|---|---|
| Project is named `dockling test` | It is a spike, not a product skeleton. Rename and restructure **once, now**. Renaming after Module 5 means touching imports, env vars, Docker, and CI. |
| `.env.example` uses `VITE_VISUAL_MIN_PICTURE_AREA_PERCENT`, `VITE_VISUAL_ENABLE_RESIDUAL_FALLBACK`, etc. | These are **server-side extraction heuristics with a client-side prefix**. Vite injects every `VITE_*` variable into the browser bundle at build time. Today it leaks tuning constants (harmless). The moment someone follows the established convention and writes `VITE_GEMINI_API_KEY`, the key ships to every visitor. Fix the convention before it becomes habit. |
| `server/` (Node) + Python extractor + `src/` (React/Vite) | **Three runtimes for a three-person team.** See §1.8. |
| `requirements-langchain-extractor.txt` and `requirements-local-extractor.txt`, one `.venv` | Two competing extractor implementations sharing one environment. This is a dependency-collision incident waiting to happen, and it contradicts the claim that Module 0 is settled. |
| `data/` and `dist/` at repo root | Extraction output is currently loose files on disk with no identity, no owner, no version. Fine for a spike; fatal for sessions that must cite "slide 7 of document X, plan version 2." |
| Open tab: `Week 15 IR Optimization.md` | Good — there is a real artifact to test against. This becomes the seed of the evaluation corpus (§2.15). |
| `.agents/`, `.gemini/` | Assistant-config sprawl. Harmless, but keep them out of the service tree. |

---

# Part 1 — Critical architecture review

The overall direction is correct and I am not going to pretend otherwise: grounded content → explicit learner state → structured assessment → inspectable policy → constrained generation is the right spine for this project, and refusing RL / DKT / agent swarms in the MVP is a mature call. Almost everything below is about the parts that spine does not cover, and about places where the design assumes something is solved when it is not.

## 1.1 "Module 0 is COMPLETE" is the single most dangerous claim in the document

Everything downstream — units, objectives, evidence cards, retrieval anchors, provenance in every tutor sentence — is derived from the Markdown. The Markdown is therefore the root of the trust chain. Declaring it complete because it "already works" means the root of the trust chain has **no quality metric, no regression suite, and no failure taxonomy**.

Worse, there is a category error inside the output format itself:

```
[Page 4]
Slide text...            ← verbatim source
Visual Explanation...    ← model inference about an image
Teaching Note...         ← model-generated pedagogy
```

Two of those three blocks are **already LLM output**. When Module 5 later claims "the tutor is grounded in the source material," that claim is false for any turn whose evidence traces back to a Teaching Note. This is not a code bug — it is a **research validity problem**. Your groundedness numbers in the FYP report would be measuring "the tutor agrees with an earlier LLM," which is not what a reader will assume you measured.

**Required fix, and it is cheap:** every emitted block carries a provenance tag.

```
<!-- block: b_0412 slide: 4 provenance: verbatim -->
<!-- block: b_0413 slide: 4 provenance: ocr confidence: 0.71 -->
<!-- block: b_0414 slide: 4 provenance: model_generated model: gemini-2.5-flash -->
```

Then downstream you can enforce a hard rule: **evidence cards may only anchor to `verbatim` and `ocr` blocks.** `model_generated` blocks are allowed to inform plan construction but may never be cited as source. That one rule is what separates this from a chatbot that sounds confident.

Module 0 is not complete. It is *unvalidated*. It needs a provenance contract and a 10-deck regression set before anything is built on it.

## 1.2 Learning objectives and evidence cards are LLM-generated but treated as an oracle

The design says the assessor becomes robust because it sees `expected_ideas` and `common_confusions`. But those fields were themselves invented by an LLM reading a slide. Consider the failure:

1. Plan builder hallucinates an expected idea that is not on the slide.
2. A student gives a correct, complete answer.
3. The assessor sees a missing idea, returns `partial`.
4. Policy returns `HINT`.
5. The tutor hints toward something the slides never taught.

This error is **silent, permanent, and repeats for every student on that document**. Prep-time error becomes runtime error with no detection path. This is the most likely source of embarrassing behaviour in a live demo.

Two mitigations, both required:

- **Span anchoring.** Every `expected_idea` must carry `(block_id, char_start, char_end)` into the slide Markdown. At plan-build time, reject any idea whose anchor cannot be produced. Unanchored ideas do not enter the card. This turns a soft prompt instruction into a hard validation gate.
- **Human review of the plan.** Not a cop-out — a *feature*. The student (or instructor) sees the extracted units and objectives before the session starts, and can edit or delete them. This gives you: a syllabus preview UI, a correction signal, and a gold-standard dataset for the report. Three wins from one screen.

## 1.3 The policy state machine has no exit — this will hang a real session

The proposed pseudo-logic:

```
if incorrect and attempt_count >= 2: return RETEACH
```

There is no branch that ever stops. RETEACH → CHECK_AGAIN → incorrect → RETEACH → forever. A struggling student — exactly the student this system exists for — gets trapped on objective 3 of 40 and the session never ends. This is the most common failure mode in tutoring loops and it is currently unhandled.

Other holes in the same block:

- `hint_level` exists in the state model but nothing in the policy increments it, and there is no "hints exhausted → reveal and move on" path.
- `REVISIT_PREREQ` can recurse. Prereq A needs prereq B needs prereq A. No depth limit.
- `confidence: float` is produced and never consumed. Self-reported LLM confidence is poorly calibrated; either route on it with a validated threshold or delete the field. Do not ship dead schema.
- Ordering bug: `objective_met` is checked before `prerequisite_gap`, so an answer that is correct *and* reveals a prereq gap will ADVANCE and bury the gap.
- **Ownership of truth is ambiguous.** A single LLM turn setting `objective_met = true` immediately marks the objective RESOLVED. A lucky guess resolves an objective. The LLM should report *observations*; the policy should own *state transitions*. Require two independent pieces of evidence, or one correct answer with `reasoning_depth == deep`.

## 1.4 The graph assumes every student message is an answer to the tutor's question

It is not. Real students send:

- "wait, what does idempotent mean?" → a genuine question, not an answer
- "can you say that again" → meta
- "skip this, I know it" → meta
- "actually can you help with my assignment" → off-task
- "ok" / "yes" / "hmm" → non-answer

Feed any of these into `assess_response` and you get `verdict: confused`, and the tutor begins remediating a misconception the student does not have. **This is the bug that breaks the supervisor demo.** It is not an edge case; it is 20–30% of turns.

**Missing module:** an intent router in front of assessment.

```
STUDENT_MESSAGE → classify_intent → ANSWER   → assess_response → ...
                                  → QUESTION → answer_in_context (no state change)
                                  → META     → handle_command (repeat/skip/slower/end)
                                  → OFF_TASK → redirect
```

Only `ANSWER` mutates learner state. Everything else is a side-channel. This also gives you a fast path (§1.12): META and short acknowledgements skip the expensive assessment call entirely.

## 1.5 LangGraph interrupts are more machinery than this problem needs

The proposal leans on `interrupt()` to pause the graph while waiting for the student. Interrupts are genuinely designed for that. But look at what a web session actually throws at it: page refresh mid-turn, two browser tabs, a double-clicked send button, a server restart during deploy, a student who returns three days later. Each of those becomes a question about *which checkpoint is live*, and debugging distributed checkpoint state is not how you want to spend week 6.

The alternative is stateless and, I would argue, strictly better here:

```python
def run_turn(session_id: str, message: str) -> TutorTurn:
    state = load_session_state(session_id)       # from Postgres
    result = graph.invoke({"state": state, "message": message})
    persist(session_id, result)                  # to Postgres
    return result.tutor_turn
```

One turn = one graph invocation, start to finish, no pause. State is loaded from Postgres at the first node and written back at the last. The graph never waits, so there is nothing to resume.

What you gain: the turn becomes a **pure function of (state, message)**, which means table-driven tests, deterministic replay from the event log, trivial horizontal scaling, and no divergence between checkpoint and database. What you lose: nothing you currently need. Interrupts earn their keep for long-running background work, parallel branches, and streaming across many nodes. You have one short linear turn.

**Recommendation:** keep LangGraph (it is a legitimate structuring tool and your report benefits from naming it), but define the graph so it is fully resumable from Postgres alone, and treat the checkpointer as a disposable cache. Then write a test that deletes all checkpoints mid-session and asserts the session continues correctly. If that test passes, you have no hidden state.

## 1.6 Two stores, no conflict rule

The prior design correctly says "separate LangGraph state from your domain database" but never says who wins when they disagree. That is the whole problem. State that lives in two places and is authoritative in neither will diverge, and the divergence will surface as a tutor that repeats a question it already asked.

**Invariant to write down and test:** Postgres is the sole source of truth. The checkpointer may be dropped at any moment with zero data loss. Nothing may exist only in a checkpoint.

## 1.7 pgvector is not needed in the MVP

Trace the retrieval design honestly. Layer 1 is objective-first — the evidence card already carries `source_refs`, so it is a primary-key lookup. Layer 2 is prerequisite/neighbour — also a lookup, by unit ordering. Layer 3, semantic search, only fires when the student asks something outside the current unit.

So the vector index serves roughly 10% of turns, and for those turns a keyword/BM25 search over a single 40-slide document is close to as good. Meanwhile pgvector costs you: an embedding model dependency, a chunking-strategy decision, an index build step in the ingestion path, and a similarity-threshold you will have to tune. (You have already lost time to cosine-ranking behaviour in a different project — that experience applies directly here.)

**Cut it from the MVP.** Keep the table and the column so it is a drop-in later. Ship Layer 3 as Postgres full-text search. Add embeddings in v1.1 with a measurement showing they beat FTS on your own eval set — which is a better story for the report than "we used pgvector because everyone does."

## 1.8 Three runtimes, three people, one semester

Right now: React/Vite frontend, Node backend in `server/`, Python extraction service. Adding a Python FastAPI tutor service makes four processes and two languages, with domain models duplicated across TypeScript and Python. Every schema change becomes two changes plus a serialization bug.

The extractor is Python. LangGraph, LangChain, Pydantic, and the ML ecosystem are Python-first. The decision follows:

**Delete the Node backend.** One FastAPI service owns ingestion, planning, sessions, and the tutoring graph. React talks to it directly. Generate the TypeScript client types from the FastAPI OpenAPI schema so there is exactly one definition of every model.

This also resolves the stack drift: the earlier plan in this project was Next.js + Supabase; the repo is Vite + Node + Python. Pick now and stop paying for the ambiguity. My recommendation is Vite + FastAPI + Postgres, because it matches what is already on disk and removes a runtime rather than adding one.

## 1.9 An LLM refereeing an LLM is not validation

`validate_assessment` as a second LLM call adds latency, cost, and a new failure mode (the two models disagree — now what?). Replace it with **deterministic consistency checks**, which are faster, free, and actually testable:

```python
if a.verdict == "correct" and a.missing_ideas:      a.verdict = "partial"
if a.objective_met and a.verdict in {"incorrect", "confused", "dont_know"}:
                                                    a.objective_met = False
if len(answer.split()) < 4 and a.reasoning_depth == "deep":
                                                    a.reasoning_depth = "shallow"
if a.misconception and a.misconception not in card.known_misconceptions:
                                                    a.misconception_novel = True
```

That last rule matters: an unrecognised misconception is a *research signal* (the card is incomplete), and you want it logged, not silently accepted.

Keep an LLM judge, but offline, over sampled traces — §2.15.

## 1.10 No versioning means no reproducible results

Two gaps that are cheap now and expensive later:

- **Plan versioning.** Regenerating a document's learning plan while sessions reference its objectives orphans those sessions. Sessions must pin `learning_plan_id`, and plans must be immutable once approved.
- **Prompt versioning.** Every LLM call must log `prompt_id` and `prompt_version` alongside model name and parameters. Without this, your evaluation table in the report describes a system that no longer exists, and you cannot answer "which prompt produced this result?" during the viva.

## 1.11 The stated research contribution is not yet a contribution

"A generalized tutoring architecture for arbitrary uploaded documents" is engineering. An examiner will ask what is novel, and "we combined ideas from six papers and applied them to slides" is a weak answer, because every component is borrowed and the combination is not obviously non-trivial.

You do not need a new method. You need a **claim you can measure**. Three candidates, in order of cost-effectiveness:

**(a) The policy ablation — strongest, cheapest, and it defends your central design decision.**
Run identical sessions under four configurations:

| Arm | Retrieval | Action selection | Evidence cards |
|---|---|---|---|
| A0 | full doc in context | none (plain LLM tutor) | no |
| A1 | objective-first | LLM chooses action | yes |
| A2 | objective-first | **deterministic policy (ours)** | yes |
| A3 | objective-first | deterministic policy | **no** |

Measure: objective resolution rate, turns-to-resolution, groundedness, answer-leakage rate, action appropriateness (human rubric, N≈100 turns), p95 latency, cost per session. A2 vs A1 tests "is an inspectable rule policy competitive with an LLM policy?" A2 vs A3 tests "do evidence cards matter?" A2 vs A0 is your headline. **That is a results chapter, and it costs you an evaluation harness you need anyway.**

**(b) Provenance-constrained tutoring.** Every tutor claim traceable to a `verbatim`/`ocr` span, with groundedness and leakage measured. Novel-ish, and it is the natural payoff of §1.1.

**(c) Objective-first vs query-first retrieval.** Falls out of the same harness for almost no extra cost.

Design the harness into the system now (Module 10 is scoped for it). Retrofitting instrumentation after the fact is where FYPs lose their results section.

## 1.12 No latency or cost budget

Per turn as designed: intent → assess → validate → generate = 3–4 LLM calls, serial. Even on a fast model that is 4–8 seconds. A tutor that takes eight seconds to react to "yes" feels broken, and perceived responsiveness is a large part of whether the demo lands.

Budget to hold: **p50 < 2.5s, p95 < 5s.** Achieved by: dropping `validate_assessment` (§1.9), routing META/short-acknowledgement turns past assessment (§1.4), streaming the generation call token-by-token so time-to-first-token is under a second, and running intent classification on the cheapest model available.

## 1.13 The UI is the pedagogy, and it is currently unspecified

If the demo looks like a chat box, it will be called a chatbot regardless of what the architecture does. The thing that makes this *slide-aware* has to be visible: a split view with the conversation on one side and the cited slide on the other, the current objective named above the chat, and the exact source span highlighted when the tutor grounds a claim. An objective-progress rail down the side makes the learner state legible.

This is not polish. It is the visual proof that the architecture exists.

## 1.14 Smaller items

- **Idempotency.** Double-clicked send = two turns, two assessments, corrupted state. Every `POST /turns` needs a client-supplied idempotency key.
- **`unit_edges` with `edge_type` ∈ {PREREQUISITE, RELATED, NEXT}** is a graph table for what is, in the MVP, a line. Use `order_index` for sequence and a `prerequisite_unit_ids` array for the rare real dependency. Add the edge table when you have a use for it.
- **Session termination is undefined.** Needs an explicit rule (§2.8).
- **No abuse/off-task policy.** One paragraph in the spec is enough, but an examiner will ask.
- **Multi-document sessions** — state explicitly that this is out of MVP scope, or someone will assume it works.

## 1.15 Summary — keep / cut / add

| Keep | Cut from MVP | Add |
|---|---|---|
| Grounded evidence cards | pgvector / embeddings | Provenance tags on every Markdown block |
| Explicit per-objective state (not `mastery=0.72`) | `validate_assessment` LLM call | Span anchoring + prep-time validation |
| Deterministic inspectable policy | `unit_edges` table | Intent router before assessment |
| Structured Pydantic assessment | LangGraph interrupts | Termination & deferral rules |
| Objective-first retrieval | Node backend | Plan + prompt versioning |
| Postgres as single source of truth | `confidence` field (unless routed on) | Idempotency keys |
| Event log | Runtime evaluator LLM | Evaluation harness + ablations |
| Session consolidation report | Multi-document sessions | Split-view evidence UI |

---

# Part 2 — Revised architecture

## 2.1 Statement

> A single Python service that converts uploaded teaching material into a **provenance-tagged, span-anchored learning plan**, then runs tutoring sessions as a sequence of **pure turns**: each turn loads explicit state from Postgres, classifies the student's intent, produces a structured assessment, applies a deterministic policy to select one pedagogical action, and generates language constrained to that action and to cited source spans — writing every intermediate decision to an append-only event log.

The architecture's defining property is that **no decision is hidden inside a prompt**. Perception, control, and generation are three separately inspectable, separately testable stages.

## 2.2 System diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│  React + Vite + TS  (apps/web)                                       │
│  Upload · Plan Review · Tutor Split-View · Session Report            │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ REST + SSE (typed client from OpenAPI)
┌───────────────────────────────▼──────────────────────────────────────┐
│  FastAPI  (apps/api)  — the only backend process                     │
│                                                                       │
│  ┌────────────────┐  ┌────────────────┐  ┌─────────────────────────┐ │
│  │ INGESTION      │  │ PLAN BUILDER   │  │ TUTOR RUNTIME           │ │
│  │ (no LLM)       │  │ (offline, LLM) │  │ (per-turn, LLM)         │ │
│  │                │  │                │  │                         │ │
│  │ upload         │  │ segment units  │  │ ┌─ LangGraph turn ────┐ │ │
│  │ → extraction   │→ │ → objectives   │→ │ │ load → intent →     │ │ │
│  │ → blocks +     │  │ → evidence     │  │ │ assess → check →    │ │ │
│  │   provenance   │  │   cards        │  │ │ update → policy →   │ │ │
│  │ → persist      │  │ → anchor spans │  │ │ retrieve → generate │ │ │
│  │                │  │ → validate     │  │ │ → persist           │ │ │
│  │                │  │ → HUMAN REVIEW │  │ └─────────────────────┘ │ │
│  └────────────────┘  └────────────────┘  └─────────────────────────┘ │
│                                                                       │
│  packages/tutor_core  ← state models + policy. NO LLM IMPORTS.       │
│  packages/llm         ← provider adapters + versioned prompt registry │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│  PostgreSQL  — SINGLE SOURCE OF TRUTH                                 │
│  documents · blocks · plans(versioned) · units · objectives ·         │
│  evidence · sessions · objective_states · turns · events · llm_calls  │
│  (LangGraph checkpointer optional & disposable)                       │
└──────────────────────────────────────────────────────────────────────┘

Offline, out of request path:
  packages/evals — trace scoring · simulated students · ablation runner
```

## 2.3 Service boundaries

| Boundary | Rule |
|---|---|
| `extraction` | Pure: bytes → provenance-tagged Markdown blocks. No DB, no HTTP. Importable as a library and runnable as a CLI. |
| `planbuilder` | Runs once per document version, offline, async job. Never touched during a session. |
| `tutor_core` | **Must not import any LLM library, HTTP client, or DB driver.** Contains state models, the policy function, consistency checks, termination rules. This is the invariant that keeps the system inspectable and the policy unit-testable. |
| `llm` | The only module that talks to model providers. Every call goes through it and is logged with prompt id + version. |
| `graph` | Wires nodes together. Contains orchestration only — no pedagogy. |
| `api` | HTTP, auth, validation, job dispatch. No business logic. |

If a rule in this table is ever violated, the corresponding property (testability, inspectability, reproducibility) is lost. Enforce `tutor_core`'s isolation with an import-linter test in CI.

## 2.4 Data flow

```
Upload
  → extraction → Block[]  (text, slide_no, provenance, bbox?)
  → persist documents + document_blocks
  → [job] plan build
       → segment into LearningUnit[]        (LLM, structured)
       → per unit: LearningObjective[]      (LLM, structured)
       → per objective: EvidenceCard        (LLM, structured)
       → anchor every expected_idea to (block_id, start, end)   ← hard gate
       → drop unanchorable ideas; flag objectives with <2 ideas
       → persist learning_plan(status=draft)
  → human review → learning_plan(status=approved, immutable)

Session start
  → sessions row, objective_states seeded UNSEEN, plan pinned
  → turn(0): policy = PROBE on first objective → generate → return

Each student message
  → turn(n): load state → classify intent
       ANSWER   → assess → consistency checks → update state → policy
       QUESTION → answer from evidence, no state mutation
       META     → command handler, no LLM assessment
       OFF_TASK → redirect
  → retrieve grounding for chosen action
  → generate under the action's contract
  → append turn + events → return (streamed)

Session end (any termination rule)
  → consolidate → session_report (resolved / deferred / misconceptions /
                   interventions that worked / suggested next session)
```

## 2.5 The turn contract — the core invariant

```
run_turn(session_id, message, idempotency_key) -> TutorTurn

  1. State in  == state loaded from Postgres. Nothing from memory.
  2. State out == state written to Postgres before the response returns.
  3. Given the same (state, message, seed, prompt_version), the intent,
     assessment, policy action, and retrieved evidence are reproducible.
  4. Only intent == ANSWER may mutate objective_states.
  5. The policy step is a pure function with no I/O.
  6. Every LLM call and every decision is appended to the event log.
```

Rules 1, 2 and 5 are what make this system debuggable at 2am in week 7.

## 2.6 Document pipeline

**Stage 1 — Extraction (Module 0.5).** Existing service, plus a provenance contract:

```json
{
  "block_id": "b_0412",
  "document_id": "doc_01",
  "slide_no": 7,
  "order": 3,
  "text": "The shuffle phase groups intermediate values by key.",
  "provenance": "verbatim",          // verbatim | ocr | model_generated
  "ocr_confidence": null,
  "producer": null,
  "bbox": [0.12, 0.34, 0.88, 0.41]
}
```

**Stage 2 — Unit segmentation.** Slides → 6–15 units per deck. Prompt receives slide titles + text, returns unit boundaries with `source_slide_ids`. Constraint: units must partition the slides with no gaps and no overlap — validate this, do not trust it.

**Stage 3 — Objectives.** 2–4 per unit, phrased as *"Student can …"*. Reject objectives that are pure recall of a definition when a reasoning-level objective is available for the same unit — recall-only objectives make the tutor feel like a flashcard app.

**Stage 4 — Evidence cards, with anchoring.**

```json
{
  "objective_id": "obj_0031",
  "statement": "Student can explain why intermediate values must be grouped by key",
  "expected_ideas": [
    {"idea": "mapper outputs carry intermediate keys",
     "anchor": {"block_id": "b_0412", "start": 4, "end": 51}},
    {"idea": "values sharing a key are collected before reduction",
     "anchor": {"block_id": "b_0413", "start": 0, "end": 62}}
  ],
  "known_misconceptions": [
    {"id": "shuffle_is_reduce", "text": "shuffle performs the reduction itself"}
  ],
  "prerequisite_objective_ids": ["obj_0027"],
  "source_block_ids": ["b_0412", "b_0413"]
}
```

**Stage 5 — Validation gate.** Drop unanchored ideas. Flag objectives with fewer than two ideas as `low_confidence` and surface them first in review. Never anchor to a `model_generated` block.

**Stage 6 — Review.** Approve → immutable plan version.

## 2.7 Tutoring pipeline — LangGraph nodes

| # | Node | LLM? | Responsibility |
|---|---|---|---|
| 1 | `load_state` | no | Session, current objective, objective states, last N turns |
| 2 | `classify_intent` | yes (cheap) | ANSWER / QUESTION / META / OFF_TASK |
| 3 | `handle_side_channel` | yes | QUESTION / META / OFF_TASK → response, **no state change**, exit early |
| 4 | `assess_response` | yes | Structured `ObjectiveAssessment` |
| 5 | `consistency_check` | no | Deterministic repairs (§1.9) |
| 6 | `update_objective_state` | no | Apply transitions; policy owns truth, not the LLM |
| 7 | `select_action` | no | **Pure policy function** |
| 8 | `retrieve_grounding` | no | Action-specific evidence assembly |
| 9 | `generate_turn` | yes (streamed) | Language only, under the action contract |
| 10 | `persist_turn` | no | Turn row + events, atomically |
| 11 | `check_termination` | no | Session-level exit rules |

Nine nodes, four LLM calls maximum, two on the common META path. Note there is no `wait_for_student` node — the graph completes and returns; the wait lives in HTTP.

## 2.8 Session management & termination

**Objective-level termination** (prevents §1.3's infinite loop):

| Condition | Result |
|---|---|
| `objective_met` on two separate turns, or once with `reasoning_depth == deep` | `RESOLVED` |
| `attempts >= 4` | `DEFERRED` |
| `hint_level > 3` | reveal + explain, then `DEFERRED` |
| `prereq_revisits >= 1` for this objective in this session | no further REVISIT_PREREQ; fall through to RETEACH |
| Student issues `skip` | `SKIPPED` |

`DEFERRED` is not failure — it is a first-class outcome that appears in the report and seeds the next session. Say this explicitly in the write-up; it is a pedagogically defensible design choice, not a bail-out.

**Session-level termination:** all objectives terminal, **or** 40 turns, **or** 45 minutes wall clock, **or** student ends, **or** 3 consecutive OFF_TASK turns → offer to end.

**Revised policy table:**

| Condition (checked in order) | Action |
|---|---|
| `state.status == UNSEEN` | `PROBE` |
| `prerequisite_gap` and `prereq_revisits == 0` | `REVISIT_PREREQ` |
| `objective_met` and `depth == shallow` and `deepen_count == 0` | `DEEPEN` |
| `objective_met` (evidence threshold met) | `ADVANCE` |
| `attempts >= 4` | `DEFER` |
| `verdict == partial` and `hint_level < 3` | `HINT(level+1)` |
| `verdict == partial` and `hint_level >= 3` | `RETEACH` |
| `verdict == incorrect` and `misconception` | `RETEACH` (address it by name) |
| `verdict == incorrect` and `attempts == 1` | `REPHRASE` |
| `verdict == incorrect` and `attempts >= 2` | `RETEACH` |
| `verdict in {confused, dont_know}` | `BRIDGE` |
| previous action was `RETEACH` | `CHECK_AGAIN` |

Order matters and the ordering is itself a design claim — put this table in the thesis and defend it.

## 2.9 State models

```python
class Provenance(str, Enum):
    VERBATIM = "verbatim"; OCR = "ocr"; MODEL_GENERATED = "model_generated"

class Intent(str, Enum):
    ANSWER = "answer"; QUESTION = "question"
    META = "meta"; OFF_TASK = "off_task"

class TurnIntent(BaseModel):
    intent: Intent
    meta_command: Literal["repeat","skip","slower","harder","end"] | None = None

class ObjectiveAssessment(BaseModel):
    verdict: Literal["correct","partial","incorrect","confused","dont_know"]
    objective_met: bool
    reasoning_depth: Literal["shallow","adequate","deep"]
    matched_idea_ids: list[str]
    missing_idea_ids: list[str]
    misconception_id: str | None = None
    misconception_novel_text: str | None = None
    prerequisite_gap_objective_id: str | None = None
    evidence_quote: str | None = Field(None, max_length=200)  # from student answer

class ObjectiveStatus(str, Enum):
    UNSEEN="unseen"; PROBING="probing"; PARTIAL="partial"
    MISCONCEPTION="misconception"; CONFUSED="confused"
    RESOLVED="resolved"; DEFERRED="deferred"; SKIPPED="skipped"

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
    event_ids: list[str] = []

class PedagogicalAction(str, Enum):
    PROBE="probe"; HINT="hint"; REPHRASE="rephrase"; BRIDGE="bridge"
    RETEACH="reteach"; CHECK_AGAIN="check_again"; DEEPEN="deepen"
    REVISIT_PREREQ="revisit_prereq"; ADVANCE="advance"; DEFER="defer"
    ANSWER_QUESTION="answer_question"; REDIRECT="redirect"
```

Note what is absent: no `mastery: float`, no `confidence: float`. Every field is either consumed by the policy or written to the report.

## 2.10 Database schema

```sql
documents(id, user_id, title, source_filename, mime, status, created_at)

document_blocks(id, document_id, slide_no, order_index, text,
                provenance, ocr_confidence, producer, bbox jsonb)
  INDEX (document_id, slide_no, order_index)

learning_plans(id, document_id, version, status,        -- draft|approved|archived
               builder_prompt_version, model, created_at,
               UNIQUE(document_id, version))

learning_units(id, plan_id, title, order_index, summary, slide_ids int[])

learning_objectives(id, unit_id, statement, order_index, low_confidence bool,
                    prerequisite_objective_ids uuid[])

objective_expected_ideas(id, objective_id, idea, block_id,
                         char_start, char_end)          -- anchoring is enforced here

objective_misconceptions(id, objective_id, code, text)

sessions(id, user_id, document_id, plan_id, status,     -- active|completed|abandoned
         current_objective_id, turn_count, started_at, ended_at)

session_objective_states(session_id, objective_id, status, attempts, hint_level,
                         deepen_count, prereq_revisits, met_count,
                         active_misconception_id, last_action, updated_at,
                         PRIMARY KEY(session_id, objective_id))

turns(id, session_id, index, idempotency_key UNIQUE, student_message,
      intent, action, tutor_message, objective_id, latency_ms, created_at)

turn_events(id, session_id, turn_id, event_type, payload jsonb, created_at)
  -- TUTOR_QUESTION, STUDENT_ANSWER, INTENT, ASSESSMENT, CONSISTENCY_REPAIR,
  -- STATE_UPDATE, POLICY_DECISION, RETRIEVAL, TUTOR_RESPONSE,
  -- OBJECTIVE_RESOLVED, OBJECTIVE_DEFERRED

llm_calls(id, session_id, turn_id, purpose, provider, model, prompt_id,
          prompt_version, input_tokens, output_tokens, latency_ms,
          cost_usd, ok, error)

session_reports(id, session_id, summary, resolved uuid[], deferred uuid[],
                misconceptions jsonb, effective_actions jsonb, created_at)
```

`turn_events` and `llm_calls` are your research dataset. Every number in the FYP report should be derivable from these two tables with SQL. Design them as if they were the deliverable, because in a sense they are.

## 2.11 APIs

```
POST   /documents                       multipart → {document_id, status}
GET    /documents/{id}
GET    /documents/{id}/blocks?slide=

POST   /documents/{id}/plans            → 202 {job_id}   (async build)
GET    /plans/{id}                      → units + objectives + cards
PATCH  /objectives/{id}                 → edit statement / ideas (draft only)
DELETE /objectives/{id}
POST   /plans/{id}/approve              → immutable

POST   /sessions            {document_id, plan_id}      → session + first turn
GET    /sessions/{id}                                   → state + progress rail
POST   /sessions/{id}/turns {message, idempotency_key}  → SSE stream
GET    /sessions/{id}/turns?after=
POST   /sessions/{id}/end
GET    /sessions/{id}/report

GET    /health   GET /metrics
```

Turn response payload carries the citation so the UI can highlight it:

```json
{ "turn_index": 7, "action": "hint",
  "message": "You said shuffle produces the final answer...",
  "objective": {"id": "obj_0031", "statement": "..."},
  "citations": [{"block_id":"b_0412","slide_no":7,"start":4,"end":51}],
  "progress": {"resolved": 3, "deferred": 0, "total": 14} }
```

## 2.12 Persistence strategy

Postgres is authoritative for everything. LangGraph checkpointer: **omit in MVP**; if added later for streaming resumption, it is a cache with a CI test proving the session survives its deletion. Uploaded files on local disk in dev, object storage in deploy, referenced by URI — never stored in the database.

## 2.13 Error handling

| Failure | Strategy |
|---|---|
| LLM timeout / 5xx | 2 retries, exponential backoff, then fall back to secondary provider |
| Structured-output parse failure | 1 repair retry with the validation error appended; then a safe default: `verdict=confused`, action `REPHRASE`. **The session never breaks because a model returned bad JSON.** |
| Both providers down | Return a graceful tutor message ("give me a moment"), mark the turn `failed`, no state mutation, client can retry with the same idempotency key |
| Extraction failure | Document → `failed` with a per-stage error; partial blocks retained |
| Plan build failure | Plan stays `draft`, partial units retained, resumable |
| Duplicate idempotency key | Return the stored turn, do not re-execute |
| Anchoring failure at build time | Drop idea; if the objective drops below 2 ideas, mark `low_confidence` |

The governing principle: **degrade the turn, never the session.**

## 2.14 Observability

Structured JSON logs with `session_id` / `turn_id` / `prompt_version` on every line. Counters: turns, actions taken (by type), objectives resolved vs deferred, parse-failure rate, provider fallback rate. Histograms: node latency, end-to-end turn latency, tokens and cost per turn. A `/sessions/{id}/trace` debug view rendering the event log as a timeline — build this in Module 6; it will pay for itself many times over.

## 2.15 Testing strategy

| Layer | What |
|---|---|
| Unit | **Policy: exhaustive table-driven tests.** Every row of §2.8, plus every termination path. This is a pure function — there is no excuse for less than full branch coverage. |
| Unit | Consistency checks, state transitions, termination rules |
| Contract | Golden JSON schemas for every structured LLM output; recorded-response fixtures so the suite runs offline and free |
| Integration | Seeded document → plan build → 20-turn scripted session, asserting state trajectory |
| Property | No objective exceeds max attempts; no session exceeds turn budget; `RESOLVED` is never entered from a single shallow-correct turn |
| Architecture | Import-linter: `tutor_core` imports nothing from `llm`, `graph`, or the DB layer |
| Extraction regression | 10 decks with hand-checked expected blocks and provenance tags |
| Pedagogical (offline) | LLM judge over sampled traces: groundedness, answer leakage, action appropriateness, misconception fit |
| Simulated students | Personas replaying full sessions: `novice`, `misconception_holder` (seeded from the card's own `known_misconceptions` — self-consistent and free), `guesser`, `expert`, `off_topic_asker` |

## 2.16 Deployment

`docker compose` with three services: `api`, `postgres`, `web`. Alembic migrations run on start. Deploy target: any container host (Fly / Railway / a university VM). Frontend static build behind the same origin to avoid CORS. Secrets via environment; **no `VITE_` prefix on anything the browser must not see** — audit `.env.example` before Module 1.

## 2.17 Folder structure

```
tutor/                                # rename from "dockling test"
├── apps/
│   ├── api/            main.py, routers/, deps.py, jobs/
│   └── web/            src/{pages,components,api,hooks}/   # Vite + TS
├── packages/
│   ├── extraction/     converters/, ocr/, vision/, blocks.py, cli.py
│   ├── planbuilder/    segment.py, objectives.py, evidence.py, anchor.py, validate.py
│   ├── tutor_core/     ⚠ NO LLM / DB / HTTP IMPORTS
│   │                   models.py, policy.py, consistency.py,
│   │                   transitions.py, termination.py
│   ├── llm/            client.py, providers/, prompts/{id}/v{n}.md, registry.py
│   ├── graph/          nodes/, build.py, run_turn.py
│   ├── persistence/    models.py, repositories/
│   └── evals/          judges/, personas/, ablations/, report.py
├── db/migrations/
├── data/               # gitignored
├── tests/              unit/ contract/ integration/ architecture/
├── docs/               ARCHITECTURE.md, ROADMAP.md, DECISIONS.md
├── docker-compose.yml
└── pyproject.toml
```

Delete `server/`. Merge the two `requirements-*.txt` into `pyproject.toml` extras (`[extraction]`, `[api]`).

## 2.18 Extension points

| Version | Extension | Hook already in place |
|---|---|---|
| 1.1 | Semantic fallback retrieval | `document_blocks.embedding` column, retrieval layer 3 interface |
| 1.1 | Cross-session memory | `session_reports` + `turn_events` are the evidence substrate |
| 1.1 | Selective runtime evaluator | Trigger on `RETEACH` + novel misconception only |
| 1.1 | Learned policy weights | Policy is a pure function — swap the implementation, keep the interface |
| Research | Knowledge tracing / DKT | `turn_events` is exactly a KT interaction log |
| Research | RLHF on pedagogical reward | `llm_calls` + judge scores form the preference dataset |
| Research | Multi-document curricula | `sessions.document_id` → join table |

---

# Part 3 — Module roadmap

Rules: each module is independently buildable, independently testable, and leaves the system in a demonstrable state. Order is chosen to minimise rework — schema and contracts first, adaptivity last.

---

## Module 0 — Document Markdown Extraction Service
**Status: EXISTS — but not complete**

Works today. Missing: provenance tags, block-level IDs, stable character offsets, a regression corpus. Do not build on it as-is (§1.1).

---

## Module 0.5 — Extraction Contract Hardening
**Complexity: S (2–3 days) · Depends on: M0 · Blocks: everything**

- **Purpose:** Make extraction output trustworthy and citable.
- **Inputs:** PDF/PPTX/ODP.
- **Outputs:** `Block[]` with `block_id`, `slide_no`, `order_index`, `text`, `provenance`, `ocr_confidence`, `producer`, `bbox`.
- **Components:** provenance tagger; block ID generator (stable across re-runs); offset preservation; `extract` CLI; 10-deck regression corpus.
- **DB:** none yet.
- **APIs:** CLI only.
- **Frontend:** none.
- **Tests:** golden-output regression on 10 decks; assert every block has a provenance value; assert offsets index correctly into stored text.
- **Acceptance:** re-running extraction on the same deck yields identical block IDs; zero blocks with null provenance; `Week 15 IR Optimization` deck extracts cleanly end to end.
- **Future:** figure/table extraction as typed blocks; equation handling.

---

## Module 1 — Repo Restructure, Database & Document Registry
**Complexity: M (4–5 days) · Depends on: M0.5**

- **Purpose:** Give documents an identity, an owner, and a home. Establish the single-service skeleton.
- **Inputs:** uploaded file.
- **Outputs:** persisted `documents` + `document_blocks`; document detail API.
- **Components:** repo restructure to §2.17; delete `server/`; merge requirements; `VITE_` env audit; FastAPI skeleton; Alembic; SQLAlchemy models; extraction job runner; docker-compose.
- **DB:** `documents`, `document_blocks`.
- **APIs:** `POST /documents`, `GET /documents/{id}`, `GET /documents/{id}/blocks`, `GET /health`.
- **LangGraph:** none.
- **Frontend:** upload page + processing status + block viewer.
- **Tests:** upload→persist integration; idempotent re-upload; failed-extraction path leaves `status=failed` with partial blocks; import-linter test scaffolded.
- **Acceptance:** upload a PPTX in the browser, see slide-by-slide blocks with provenance badges rendered, all from Postgres.
- **Future:** multi-user auth; object storage; document versioning.

---

## Module 2 — Learning Plan Builder
**Complexity: L (6–8 days) · Depends on: M1 · The intellectual core of the document side**

- **Purpose:** Blocks → validated, anchored learning plan.
- **Inputs:** `document_id`.
- **Outputs:** `learning_plans(status=draft)` with units, objectives, anchored ideas, misconceptions.
- **Components:** `llm` package (provider adapters, versioned prompt registry, structured output + repair retry); unit segmenter; objective generator; evidence-card generator; **span anchor resolver**; validation gate; async job runner.
- **DB:** `learning_plans`, `learning_units`, `learning_objectives`, `objective_expected_ideas`, `objective_misconceptions`, `llm_calls`.
- **APIs:** `POST /documents/{id}/plans`, `GET /plans/{id}`.
- **LangGraph:** optional — a linear job, plain async code is fine and simpler.
- **Frontend:** build-progress indicator.
- **Tests:** unit partition completeness (no gaps/overlaps); every persisted idea has a resolvable anchor; anchors never point at `model_generated` blocks; parse-repair path; recorded-fixture contract tests.
- **Acceptance:** on a 40-slide deck, produce 8–14 units and ≥2 anchored ideas for ≥80% of objectives, in under 3 minutes, at a logged cost.
- **Future:** cross-document dedup; difficulty estimation; instructor-authored objectives.

---

## Module 3 — Plan Review Interface
**Complexity: S–M (3–4 days) · Depends on: M2**

- **Purpose:** Human-in-the-loop correction; approval freezes the plan. Also produces gold-standard data (§1.2).
- **Inputs:** draft plan.
- **Outputs:** approved immutable plan + edit audit trail.
- **Components:** editable objective list; source-span preview panel; low-confidence flags surfaced first; approve transaction.
- **DB:** plan status transitions; `plan_edits` audit table.
- **APIs:** `PATCH /objectives/{id}`, `DELETE /objectives/{id}`, `POST /plans/{id}/approve`.
- **Frontend:** plan review page — unit list, objectives, expected ideas with highlighted source spans.
- **Tests:** approved plans reject edits; edit audit recorded; deleting an objective cascades correctly.
- **Acceptance:** review and approve a plan in under 5 minutes; every edit recoverable from the audit table.
- **Future:** instructor accounts; plan templates; edit statistics as a quality metric for M2.

---

## Module 4 — Session Runtime Skeleton (no adaptivity)
**Complexity: M (4–5 days) · Depends on: M3**

- **Purpose:** Prove the entire turn plumbing before any intelligence exists. Highest rework-avoidance value in the roadmap.
- **Inputs:** `document_id` + approved `plan_id` + student messages.
- **Outputs:** a running session that walks objectives linearly, asking a `PROBE` question for each and accepting any answer.
- **Components:** session creation; `run_turn` skeleton; LangGraph with `load_state → select_action(stub) → retrieve → generate → persist`; SSE streaming; idempotency keys; `tutor_core` package created with import-linter enforced.
- **DB:** `sessions`, `session_objective_states`, `turns`, `turn_events`.
- **APIs:** `POST /sessions`, `POST /sessions/{id}/turns`, `GET /sessions/{id}`, `GET /sessions/{id}/turns`.
- **LangGraph:** nodes 1, 7(stub), 8, 9, 10.
- **Frontend:** split view — chat left, cited slide right, objective progress rail.
- **Tests:** turn contract properties (state in/out from DB only); duplicate idempotency key returns stored turn; page refresh mid-session resumes correctly; two tabs do not corrupt state.
- **Acceptance:** complete a 10-turn session; kill and restart the API mid-session and continue without loss.
- **Future:** voice input; mobile layout.

---

## Module 5 — Assessment
**Complexity: M (4–5 days) · Depends on: M4**

- **Purpose:** Turn free-text answers into structured, grounded observations.
- **Inputs:** objective + evidence card + source blocks + question asked + student answer + recent context.
- **Outputs:** `ObjectiveAssessment`, plus `consistency_repair` events.
- **Components:** `assess_response` node; assessment prompt (versioned); deterministic consistency checks (§1.9); novel-misconception flagging.
- **DB:** `turn_events(ASSESSMENT, CONSISTENCY_REPAIR)`.
- **APIs:** unchanged.
- **LangGraph:** nodes 4, 5.
- **Frontend:** dev-only assessment panel behind a debug flag.
- **Tests:** 40 hand-labelled (answer, expected verdict) pairs as a fixture suite; every consistency rule unit-tested; parse-repair path.
- **Acceptance:** ≥80% verdict agreement with hand labels on the fixture set; zero unhandled parse failures across 100 turns.
- **Future:** partial-credit scoring; multilingual answers; code-answer assessment.

---

## Module 6 — Policy Engine, State Machine & Trace Viewer
**Complexity: M (4–5 days) · Depends on: M5 · This is your research artefact**

- **Purpose:** Deterministic, inspectable, fully tested action selection.
- **Inputs:** `ObjectiveAssessment` + `ObjectiveState`.
- **Outputs:** `PedagogicalAction` + updated state + termination decisions.
- **Components:** `policy.py` (pure); `transitions.py`; `termination.py`; deferral; hint ladder; prereq revisit limits; **trace viewer** rendering `turn_events` as a timeline.
- **DB:** `session_objective_states` updates; `POLICY_DECISION`, `OBJECTIVE_RESOLVED`, `OBJECTIVE_DEFERRED` events.
- **APIs:** `GET /sessions/{id}/trace`.
- **LangGraph:** nodes 6, 7, 11.
- **Frontend:** trace viewer page.
- **Tests:** **exhaustive table-driven coverage of every policy row and every termination path**; property tests (attempts never exceed cap; sessions always terminate; RESOLVED never entered from a single shallow-correct turn).
- **Acceptance:** 100% branch coverage on `tutor_core`; import-linter passes; a 40-turn adversarial scripted session always terminates.
- **Future:** configurable policy profiles (gentle / challenging); learned policy weights.

---

## Module 7 — Grounded Action-Constrained Generation
**Complexity: M (4–5 days) · Depends on: M6**

- **Purpose:** Produce tutor language that obeys the selected action and cites real spans.
- **Inputs:** action + objective + state + retrieved evidence + recent turns.
- **Outputs:** tutor message + citations, streamed.
- **Components:** one prompt contract per action (PROBE / HINT×3 / REPHRASE / BRIDGE / RETEACH / CHECK_AGAIN / DEEPEN / REVISIT_PREREQ / DEFER); layered retrieval (objective-first → prereq → FTS fallback); **leakage guard** — HINT output must not contain a target idea's anchored span near-verbatim; citation extraction.
- **DB:** `turns.tutor_message`, citations in `turn_events`.
- **APIs:** turn response carries `citations[]`.
- **LangGraph:** nodes 8, 9.
- **Frontend:** citation click → highlight span on the slide pane.
- **Tests:** per-action contract assertions (HINT never states the answer; DEEPEN never re-explains; RETEACH names the misconception); leakage guard unit tests; streaming integration.
- **Acceptance:** leakage rate < 5% on 100 sampled HINT turns; every factual sentence carries a resolvable citation.
- **Future:** worked examples; analogy generation; diagram references.

---

## Module 8 — Intent Router & Side Channels
**Complexity: S–M (3 days) · Depends on: M7 · Do not skip this**

- **Purpose:** Stop treating every message as an answer (§1.4).
- **Inputs:** student message + session context.
- **Outputs:** `TurnIntent`; side-channel responses that never mutate learner state.
- **Components:** `classify_intent` (cheapest model); question answerer restricted to plan evidence; meta commands (repeat / skip / slower / harder / end); off-task redirect with a 3-strike rule; fast path skipping assessment.
- **DB:** `turns.intent`; `INTENT` events.
- **LangGraph:** nodes 2, 3.
- **Frontend:** visible affordances for skip / repeat / end.
- **Tests:** 60 labelled messages across four intents; assert non-ANSWER intents produce zero state mutations.
- **Acceptance:** ≥90% intent accuracy on the labelled set; META turns complete in under 1.5s.
- **Future:** clarification requests; student-initiated topic jumps.

---

## Module 9 — Session Consolidation & Report
**Complexity: S (2–3 days) · Depends on: M8**

- **Purpose:** Close the loop and produce the artefact students actually keep.
- **Inputs:** full session event log.
- **Outputs:** `session_reports` row + report UI.
- **Components:** aggregation from events (deterministic, not LLM-derived); narrative summary (LLM, from aggregated facts only); which interventions preceded resolution; suggested next-session focus.
- **DB:** `session_reports`.
- **APIs:** `POST /sessions/{id}/end`, `GET /sessions/{id}/report`.
- **Frontend:** report page; export to Markdown/PDF.
- **Tests:** aggregation correctness against a synthetic event log; summary contains no claims absent from the aggregate.
- **Acceptance:** every number in the report reproducible by SQL over `turn_events`.
- **Future:** cross-session progress; instructor dashboard; spaced-repetition scheduling.

---

## Module 10 — Evaluation Harness, Simulated Students & Ablations
**Complexity: L (6–8 days) · Depends on: M9 · This is your results chapter**

- **Purpose:** Produce defensible numbers (§1.11).
- **Inputs:** eval corpus (10 decks), personas, arm configurations.
- **Outputs:** metric tables and plots for the thesis.
- **Components:** persona simulator (novice / misconception_holder / guesser / expert / off_topic_asker); ablation runner (A0–A3); offline LLM judges for groundedness, leakage, action appropriateness; human rubric tooling for N≈100 turns with inter-rater agreement; metrics aggregation → CSV/LaTeX.
- **DB:** `eval_runs`, `eval_scores`.
- **APIs:** CLI, not HTTP.
- **Tests:** judge stability across repeated runs; persona determinism under fixed seed.
- **Acceptance:** a single command reproduces the full ablation table; every reported metric traceable to `turn_events`.
- **Future:** real user study; A/B in-product.

---

## Module 11 — Polish, Hardening & Deployment
**Complexity: M (4–5 days) · Depends on: M10**

- Provider fallback under fault injection; rate limiting; cost caps per session; empty/error states; loading skeletons; accessibility pass; onboarding for first-time users; docker-compose → deployed URL; README with reproduction steps; demo script for the viva.
- **Acceptance:** a stranger uploads a deck and completes a session on the deployed URL without assistance.

---

## v1.1 and research extensions (post-MVP, only if time permits)

`pgvector` semantic retrieval with a measurement showing it beats FTS · cross-session memory with evidence-backed observations · selective runtime evaluator on RETEACH turns only · configurable policy profiles · knowledge tracing over `turn_events`.

---

## Parallelisation for three people

The critical path is M1 → M2 → M4 → M5 → M6 → M7. Two branches can run alongside it:

| Owner | Track |
|---|---|
| **Saad** (critical path) | M0.5, M1, M2, M5, M6, M7 — extraction contract, plan builder, assessment, policy, generation |
| **Teammate A** | M3 plan review UI, M4 frontend split-view, M9 report UI, M11 polish — starts as soon as M1's API contracts exist |
| **Teammate B** | Eval corpus + hand labels for M5, intent label set for M8, judge prompts and persona definitions for M10 — **this work can start on day one and does not block on any code** |

Teammate B's track is deliberately front-loaded: the labelled datasets are the long pole for every acceptance criterion in the roadmap, and they are the one thing that cannot be produced quickly at the end.

## Rough week map (8 weeks)

| Week | Work |
|---|---|
| 1 | M0.5 + M1 |
| 2–3 | M2 (+ M3 in parallel) |
| 4 | M4 |
| 5 | M5 + M6 |
| 6 | M7 + M8 |
| 7 | M9 + M10 |
| 8 | M11 + write-up |

Weeks 5–7 are the tightest. If something must be cut, cut M11 polish and the v1.1 list — never M10, because without it the thesis has no results.
