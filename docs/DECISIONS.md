# Decisions

## 2026-07-23/24 — Repo restructure (Module 0.5 → target layout)

**Extractor's FastAPI app stays in `packages/extraction/service.py`, not `apps/api`.**
This module scoped `apps/api` to an empty health-check skeleton, but the React app
talks to the extractor over live HTTP (Vite spawns uvicorn, proxied through
`/local-extractor`). Merging the extraction routes into `apps/api` now would have been
scope creep ahead of Module 1 (no persistence layer or job runner exists yet to justify
`apps/api` owning them); leaving the live flow disconnected would have broken
`npm run dev`. Chose to keep a transitional FastAPI app inside `packages/extraction`
that Vite spawns directly (`slidevision.extraction.service:app`), preserving identical
behavior. Revisit when Module 1 gives `apps/api` real routes and a reason to absorb
extraction's HTTP layer.

**`server/langchainExtractorService.py` and `server/groqVisionService.js` were deleted,
not archived.** Both were confirmed dead code (unused by any script, by
`vite.config.js`, or by any `src/` import) before this restructure. Superseded by the
OpenCode-based pipeline in `localExtractorService.py` (now `packages/extraction/`).
Full history is preserved on the `pre-restructure` git tag if either is ever needed for
the FYP report's comparison section. Their frontend counterparts (`doclingApi.js`,
`pptApi.js`, `langchainExtractorApi.js`, `visionApi.js`) were deleted for the same
reason — confirmed unused, no import anywhere in `src/`.

**`VITE_VISUAL_*` and `VITE_OPENCODE_VISION_*` stay `VITE_`-prefixed — documented
exception to invariant #7.** The roadmap doc's Part 0 assumed these were "server-side
extraction heuristics with a client-side prefix" (a leak risk). Code inspection showed
otherwise: `ImageDebugPanel.jsx` does genuine canvas-based pixel analysis in the
browser (`calculateResidualScores`, `analyzeImage`) to decide which rendered slide
images are "visual enough" to send for description, and reads these vars via
`import.meta.env` with no server-side duplicate. None are secrets. Renaming them away
from `VITE_` would have required either hardcoding the values as JS constants (losing
env-configurability, a real behavior change) or a custom Vite `envPrefix` (reintroducing
the exact ambiguity the rule exists to prevent). Confirmed with the project owner:
keep them `VITE_`, document the exception in CLAUDE.md invariant #7 rather than
silently relaxing the rule. The only var actually renamed for the leak fix was
`VITE_LOCAL_EXTRACTOR_BASE_URL` → `VITE_API_BASE_URL` (a legitimate rename, not a
leak fix — the extractor was never in-process, it's still a separate FastAPI process
reached via the Vite proxy, same as before).

**`packages/extraction` is split into single-purpose modules** (`config.py`, `utils.py`,
`cache.py`, `office.py`, `ocr.py`, `geometry.py`, `markdown_build.py`, `pipeline.py`,
`service.py`, `cli.py`) rather than kept as one ~1,770-line file, matching the
"importable package" requirement. `opencodeVisionClient.mjs` moved to
`packages/extraction/opencode_helper/` since the Python code still shells out to it by
design (no LLM library dependency in the extraction layer); `OPENCODE_VISION_NODE_HELPER`'s
default path now resolves relative to the package file itself rather than process cwd,
since the package can now be imported/run from anywhere.

## 2026-07-24 — Plan Review Interface (Module 3)

**Module 2 quality metric: 5 edits on the 41-objective networking_101 fixture plan.**
Reviewed the real 12-unit/41-objective demo plan (`scripts/build_plan_demo.py`'s
output, `plan_id=d3b91bca-9752-4429-ab7f-131f7ee7478e`) end-to-end through the live
API (the same requests `apps/web`'s PlanReviewPage issues): 4 objective statements
in the "Application Layer Services" unit were missing the "Student can..." phrasing
every other objective in the plan uses (a real generation inconsistency, not a
planted example) and were corrected; 1 expected idea was re-anchored from an entire
sentence down to its specific supporting clause (`"Networks let users share files,
printers, and internet access..."` narrowed to `"share files, printers, and
internet access"`) to demonstrate the manual anchor-correction path. All 41
objectives came back `low_confidence=false` (consistent with the "118/118 ideas
anchored" figure already recorded in docs/BACKLOG.md's planbuilder section), so no
objective needed the reviewed-flag gate exercised on real content — that path is
covered instead by `tests/integration/test_plan_approval.py::test_reviewed_flag_persists`.
The plan was then approved; a subsequent edit attempt correctly returned 409, and
`GET /plans/{id}/edits` shows exactly 6 rows (5 `update` + 1 `approve`) — the whole
review pass is recoverable from `plan_edits`. Frontend verification was via
type-check (`tsc --noEmit`), lint, and a production build (`vite build`), not a
live browser session — no browser-automation tool is available in this
environment, so the click-through itself (as opposed to the API path it calls)
wasn't manually exercised.

**`plan_edits.objective_id` has no foreign key**, unlike every other
plan/objective-scoped table in `packages/persistence/models.py`. Deleting an
objective (this module's own DELETE endpoint) must not take its own audit
history down with it — an FK with `ON DELETE CASCADE` would do exactly that,
and `ON DELETE SET NULL` would still lose which objective a surviving `update`
row referred to. Left as a plain UUID, the same choice already made for
`session_objective_states.active_misconception_id`.

**The draft/approved-immutability guard lives in `PlanRepository`, not just the
router**, per CLAUDE.md invariant #5's spirit and this module's explicit
instruction ("Enforce in the repository layer, not just the router"). Every
mutating method (`edit_objective`, `delete_objective`, `replace_expected_ideas`,
`approve_plan`) re-checks the parent plan's status itself and raises
`PlanNotEditableError` (new: `packages/persistence/errors.py`), which
`apps/api/routers/plans.py` maps to 409. A future caller that bypasses the
router (a script, a background job) still can't mutate an approved plan.

**The reviewed-flag approval gate (disable Approve until every low_confidence
objective is reviewed) is enforced only in `apps/web/src/pages/PlanReviewPage.jsx`,
not in `POST /plans/{id}/approve`.** The prompt phrased this as a button
behavior ("Approve button, disabled until...") rather than an API-level
invariant, unlike the approved-plan-rejects-edits rule which was explicitly
called out as repository-enforced. Recorded in docs/BACKLOG.md as a
call worth revisiting if it should become a hard server-side rule.
