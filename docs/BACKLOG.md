# Backlog

Deferred items surface here as modules are built. Empty at project start.

## From "Database Schema" module (packages/persistence, docker-compose, Alembic)

- ~~No API routes, job runner, or extraction wiring populate these tables
  yet.~~ **Resolved by the "Document Registry" module**: `apps/api` now
  does exactly this.

- ~~`documents.status` values are this module's own judgment call.~~
  **Resolved**: the "Document Registry" module's prompt pinned down the
  exact lifecycle (`uploaded -> extracting -> ready | failed`); enum values
  renamed to match (`UPLOADED`/`EXTRACTING` replacing the old
  `PENDING`/`PROCESSING` guesses).

- **No `users` table exists.** `documents.user_id` / `sessions.user_id` are
  bare, unconstrained UUID columns — Module 1 explicitly lists "multi-user
  auth" under **Future**, so there's nothing to FK against yet. The
  "Document Registry" module hardcodes a fixed dev user id
  (`apps/api/routers/documents.py::DEV_USER_ID`,
  `00000000-0000-0000-0000-000000000001`) on every upload — replace with
  the real authenticated user once auth lands, and add the FK then.

- ~~`document_blocks.id` / `document_id` type mismatch with the extraction
  module's current output is not reconciled.~~ **Resolved by the "Document
  Registry" module**: `apps/api/jobs/extraction.py::run_extraction_job`
  passes `str(document_id)` (the DB-issued UUID) into
  `extract_document(..., document_id=...)`, so `make_block_id` hashes the
  real UUID rather than extraction minting its own hash-based id. The
  pre-existing `upsert_document`/`file_hash` bug noted below is still
  unfixed, but it's now fully isolated to the legacy SQLite-cached debug
  extractor (`packages/extraction/service.py`, port 5052) — `apps/api`
  never calls `upsert_document` at all.

- **`objective_expected_ideas.block_id` and every cross-aggregate FK from
  session/turn data back into plan structure use `ON DELETE RESTRICT`**
  (not `CASCADE`), to stop citations and research data
  (`turn_events`/`llm_calls`) from silently vanishing if someone deletes a
  document or plan out from under them. Practical consequence: deleting a
  `document` that has any `learning_plans` row, or a `learning_plan` that
  has any `sessions` row, will fail with a FK violation by design — there is
  no cascade/archive path yet. Module 3's plan-approval/archive flow should
  decide whether "delete" should even be exposed once a plan has sessions,
  or whether it should soft-delete (`status=archived`) instead.

- **`objective_misconceptions.code` / `session_objective_states.active_misconception_id`
  are unconstrained strings, not FKs.** §2.9's `ObjectiveAssessment.misconception_id`
  reads as a per-objective catalog code (paired with `misconception_novel_text`
  for not-yet-catalogued ones), not `objective_misconceptions.id`'s UUID PK —
  and a code is only unique per-objective, not globally, so it isn't
  cleanly FK-able. Revisit if Module 5/6 need referential integrity here.

- **`plan_edits` audit table (Module 3) not created.** Out of scope for this
  module — §2.10 doesn't list it, Module 3's spec does.

- **`document_blocks.embedding` (semantic fallback retrieval, §2.18 v1.1
  extension point) not added.** Explicitly deferred to v1.1 per the roadmap.

## From "Document Registry" module (apps/api, apps/web Documents tab)

- **No authentication — a single hardcoded dev user id.**
  `apps/api/routers/documents.py::DEV_USER_ID =
  uuid.UUID("00000000-0000-0000-0000-000000000001")` is attributed to every
  uploaded document, per this module's explicit instruction. Replace with
  real auth (§2.10's Future item) when that module is built; nothing else
  needs to change since `documents.user_id` is already a bare UUID column.

- **Re-upload idempotency is keyed on content hash, with two chosen
  behaviors — recorded here since the module asked for the rationale to be
  written down, not just implemented:**
  - Same bytes, existing document not `FAILED` → **200**, no-op, existing
    `document_id` returned, extraction is NOT re-triggered. Re-extracting a
    document whose blocks are already ready (or already in flight) would
    just burn OCR/vision cost for identical output, and would fight the
    in-flight job over the same rows.
  - Same bytes, existing document `FAILED` → **202**, treated as a retry:
    status resets to `uploaded`, extraction is rescheduled against the same
    `document_id`. Re-uploading a file that previously failed is exactly
    what a user does to ask "try again" — there's no separate retry
    endpoint, so this is the only way to retry via the API as built.
  - Not supported: retrying with *different* bytes under the same
    `document_id` (e.g. "I fixed the corrupt file, same upload slot").
    Different content hash → different `document_id` by design; this is
    arguably correct (different bytes are a different document) but worth
    a product decision later if it surprises users.

- **No `GET /documents` list endpoint.** Module 1's own API list is exactly
  `POST /documents`, `GET /documents/{id}`, `GET /documents/{id}/blocks`,
  `GET /health` — no list route. `apps/web`'s Documents tab only ever shows
  the most recently uploaded document (in-memory React state); there's no
  way to browse previously uploaded documents from the UI after a page
  reload. Add a list endpoint + a document picker when that's needed.

- **`VITE_API_BASE_URL` was repurposed.** It previously pointed the
  extractor-debug tool (`apps/web/src/utils/localExtractorApi.js`) at a
  base URL but was always blank in both env files, so in practice it did
  nothing (the tool always fell back to the `/local-extractor` Vite-proxy
  path). It now points the new typed `apps/web/src/api` client at `apps/api`
  (`http://localhost:8000` by default) per this module's explicit
  instruction ("the only VITE_ var"). `localExtractorApi.js` no longer reads
  it at all — the extractor-debug tool unconditionally uses the proxy path,
  which is what it was already doing in every configured environment.

- **`apps/web/src/api/client.ts`'s `uploadDocument` needs a manual
  `bodySerializer`,** not openapi-fetch's default multipart handling —
  passing `client.POST("/documents", { body: { file } })` alone produced an
  HTTP 422 against FastAPI's `File(...)` parameter (confirmed live, not
  theorized). The generated type for the upload body field is `string`
  (OpenAPI's `format: binary` has no native "File" type), cast to `unknown`
  then `string` at that one call site. If openapi-fetch changes its
  multipart defaults in a future upgrade, re-check whether the manual
  `bodySerializer` is still needed.

- **apps/api's OpenAPI spec only documents `200` for `POST /documents`,
  never the `202` it can actually return.** FastAPI infers the documented
  success status from the route decorator; this route sets
  `response.status_code` dynamically (200 vs. 202) instead of declaring a
  fixed one, and FastAPI doesn't introspect that. The response *body*
  shape (`DocumentCreateResponse`) is identical either way, so the
  generated TS types are unaffected — this is a spec-accuracy gap, not a
  functional one. Fix by adding `responses={202: {...}}` to the decorator
  if/when the OpenAPI spec itself needs to be authoritative (e.g. published
  externally).

- **`tests/integration/test_documents_api.py`'s per-test cleanup
  occasionally leaves a document's upload directory behind under
  `data/uploads/`** (Postgres rows are always cleaned — confirmed via
  `SELECT count(*) FROM documents` after a full run — only the on-disk
  directory can survive). `shutil.rmtree(..., ignore_errors=True)` silently
  swallows what looks like a Windows file-handle lock from
  `packages/extraction`'s PDF rendering, not from `apps/api` itself.
  Harmless (gitignored, disposable dev data) but not root-caused — chasing
  it would mean touching `packages/extraction` internals, out of scope for
  this module.

## From Module 0.5 (provenance-tagged Block extraction)

- **Fixture decks are synthetic.** No real lecture deck exists anywhere in
  the repo (checked — `data/`, `db/`, and the whole tree), so
  `tests/fixtures/decks/*/deck.pdf` are generated by
  `tests/fixtures/generate_decks.py`. Swap in real decks under the same path
  whenever convenient and re-run `generate_expected_blocks.py` to refresh the
  goldens; the regression suite doesn't care which.

- **Real vision calls are not wired into `extract_document`/the CLI.**
  `blocks.block_from_visual_description()` converts one vision-model
  description dict into a `model_generated` Block and is unit-tested, but
  nothing in `pipeline.py` calls the actual OpenCode vision API — today that
  only happens via the frontend-driven `/v1/visual-descriptions` endpoint in
  `service.py`, decoupled from `extract_document`. Wiring real vision calls
  into the core pipeline (and appending the resulting blocks) is deferred so
  the regression suite stays offline/deterministic; do it once there's a
  reason to make `model_generated` blocks part of the CLI/service's default
  output rather than a frontend-orchestrated side channel.

- **Mixed-page OCR is not implemented.** A page is currently classified as
  either fully `verbatim` (has ≥10 legible chars) or fully `ocr` (does not);
  there's no per-span detection of "mostly real text plus one illegible
  embedded screenshot" on the same page. Building that requires the
  redact-only-illegible-regions approach `ocr.py`'s `exec_modern_rapidocr`
  already uses for markdown rendering, adapted to emit blocks instead of
  mutating the page. See `packages/extraction/blocks.py`'s
  `_extract_ocr_blocks` docstring.

- **`markdown` is still pymupdf4llm output, not a rendering of blocks.** The
  roadmap's target end-state has Markdown derived from blocks (with the
  `<!-- block: ... provenance: ... -->` comment format shown in
  ARCHITECTURE_REVIEW_AND_ROADMAP.md §1.1). That format doesn't match what
  `apps/web/src/utils/imagePipeline.js` currently parses (`[Page N]` /
  `---`-separated sections), and this module's scope excludes touching
  `apps/web`. `blocks` is exposed as an additive field alongside the
  unchanged `markdown`/`chunks` fields; do the full switch (and the
  matching frontend parser update) together in whichever module takes on
  the frontend/block integration.

- **`service.py`'s extraction cache doesn't persist `blocks`/`documentId`.**
  A cache **hit** in `/v1/convert/file` still returns the old shape (no
  `blocks`, no `documentId`) since `cache.py`'s `document_extractions` table
  schema wasn't extended — only a cache **miss** (full extraction) returns
  them. Extending the SQLite cache is arguably premature given
  `packages/persistence` is the module meant to own durable storage; revisit
  there.

## From "packages/llm" module (OpenCode Zen client)

- **`response_format: json_schema` is unusable on this gateway, for all
  three models** (`scripts/probe_gateway.py` table): `deepseek-v4-pro` /
  `deepseek-v4-flash` return HTTP 400 (`Upstream request failed`);
  `mimo-v2.5` returns HTTP 200 but silently ignores the schema and returns
  an unrelated shape. `structured.py` never sends it — schema is described
  in-prompt and enforced by Pydantic validation instead. Re-probe if
  OpenCode Zen changes its upstream providers; native schema mode would be
  strictly better if it ever becomes reliable.

- **All three models are reasoning models that spend `max_tokens` on hidden
  `reasoning_content`/`reasoning` before the real answer.** `client.py`
  defaults `max_tokens=1024`, which was enough in every probe/demo run, but
  no purpose-specific tuning has been done. If a real prompt's completion
  gets truncated (`finish_reason=length` with a short `content`), that's
  this — raise the caller's `max_tokens`, not a client.py bug.

- **`deepseek-v4-flash` returned empty `content` with `finish_reason=stop`
  on ~1/6 identical `json_object` requests during probing** (harmless
  variance in how much of the budget reasoning consumes, not a bug we can
  fix client-side). The repair retry already absorbs this — an empty first
  attempt just triggers the same repair path as an invalid one — but it's
  worth knowing this is a real, observed gateway behavior and not a
  hypothetical. **Confirmed at higher stakes building packages/planbuilder**:
  on the 40-slide demo deck, 3 of 12 concurrent `generate_objectives` calls
  failed both the primary *and* repair attempt (empty content twice in a
  row) in one batch, and one specific unit failed three separate build
  attempts before succeeding — i.e. double-failure isn't a negligible tail
  risk at production scale, it happens regularly across a dozen-plus calls.
  `packages/planbuilder`'s per-unit fault isolation (skip and leave
  resumable, don't abort the whole job) exists specifically because of this.

- **No secondary-provider fallback.** §2.13 of the roadmap says "2 retries,
  then fall back to secondary provider" — there is only one provider
  (OpenCode Zen) configured today, so `client.py`'s retries exhaust into a
  raised `LlmRequestError` with no fallback target. Add one if/when a
  second provider is actually in scope.

- **`LLM_COST_RATE_*` is unset for all three models** — every `llm_calls`
  row logs `cost_usd=NULL` (by design: CLAUDE.md's "never guess" applied to
  cost). Add real per-model USD-per-1M-token rates to `.env.local` once
  they're known (OpenCode Zen's dashboard/invoice, not this module) to get
  real cost tracking.

- **`stream=True` aggregates the full SSE response before returning** —
  `complete()`'s signature is request/response (`-> parsed result`), so
  there is no generator/callback surface for incremental tokens yet. Fine
  for probing "does streaming work"; a real streaming UX (tutor response
  appearing token-by-token in `apps/web`) needs a different entrypoint,
  deferred to whichever module builds turn generation.

- **Only one real prompt exists**: `prompts/example/v1.md`, scaffolding used
  by `scripts/demo_structured_call.py` to exercise the registry +
  structured-output pipeline end to end. Real prompts (`assess_response`,
  `plan_segment`, ...) belong to the modules that own that pedagogy.

## From "packages/planbuilder" module (unit segmentation + objectives)

- **No `learning_plans.error` column.** `documents` has an explicit `.error`
  field for failed extraction; `learning_plans` doesn't (§2.10's original
  column list for `learning_plans` never included one, and this module's
  own instructions only asked for "stays draft, resumable" — not "records
  why it stopped"). `run_plan_build_job` logs the exception via
  `logger.exception(...)` only; there's no way to see *why* a plan is stuck
  incomplete from the DB alone, only that it is (`GET /plans/{id}` shows
  units with no objectives, or zero units). Add a column + migration if
  that visibility gap becomes a real problem.

- **`ObjectiveDraft.is_recall_only` isn't persisted anywhere.**
  `learning_objectives.low_confidence` already has a reserved meaning ("fewer
  than 2 anchored ideas", set by the evidence-card/anchoring stage —
  deferred, not yet built) and repurposing it here would collide with that
  once anchoring lands. `is_recall_only` is used only in-memory by
  `filter_recall_only()` to decide what to keep; objectives that survive
  filtering (including the rare all-recall unit where nothing better
  exists) are persisted with no trace of which ones were borderline.

- **Evidence cards and span anchoring are not built** (`objective_expected_ideas`,
  `objective_misconceptions` stay empty) — explicitly out of scope per this
  module's own instructions ("that is Prompt 7").

- **No `GET /documents/{id}/plans` list endpoint** and no way to see a
  document's plan-version history from the API — only the two routes this
  module's instructions named (`POST .../plans`, `GET /plans/{id}`) exist.
  `PlanRepository.latest_version()` already supports listing internally;
  exposing it is just a missing route.

- **Plan-build "resumability" is a heuristic, not a stored flag**
  (`apps/api/jobs/plan_build.py::is_incomplete`): a plan counts as
  incomplete if it has zero units, or any unit with zero objectives. This
  is correct for how the job persists incrementally (commit per unit, then
  per unit's objectives) but would need revisiting if a future module adds
  a legitimate reason for a fully-built plan to have a unit with
  deliberately zero objectives.

- **Retrying a genuinely bad plan isn't possible without DB surgery.** If
  segmentation's one retry (`segment.py::build_units`) still fails
  (`PartitionError`), the job logs and exits with the plan still at zero
  units — the *next* `POST /documents/{id}/plans` call will correctly
  detect it as incomplete and resume it (same plan_id, tries segmentation
  again from scratch), so in practice this self-heals on retry. No
  intervention needed, just noting it here since it wasn't obvious from the
  code alone.

- **No fixture-deck regression corpus for planbuilder** (unlike Module 0.5's
  10-deck golden corpus) — `tests/fixtures/generate_planbuilder_deck.py`
  produces exactly one 40-slide synthetic deck for manual/demo verification
  (`scripts/build_plan_demo.py`), not an automated pytest fixture with
  golden expected units (LLM output isn't deterministic enough for a golden
  file the way extraction's pure-code output is). `tests/unit/test_segment_partition.py`
  covers the partition-validation logic itself, offline, instead.

- **`SEGMENTATION_MAX_TOKENS` (4096) and `OBJECTIVES_MAX_TOKENS` (3072) are
  empirically-tuned constants, not derived from anything.** The first real
  40-slide run failed outright at `client.py`'s default `max_tokens=1024` —
  both the segmentation call and every objectives call were silently
  truncated to exactly 1024 output tokens (reasoning alone ate the whole
  budget), which `structured.py`'s repair retry cannot fix since the
  *repair* attempt hits the identical ceiling. Segmentation was fixed at
  4096; objectives needed a second bump from 2048 to 3072 after the largest
  unit in the deck (5 slides) specifically kept failing at 2048 while every
  smaller unit succeeded first try — suggestive that budget should scale
  with a unit's slide count rather than being a flat constant, but that's
  unverified with only one data point. Re-tune (or make it size-adaptive)
  once this runs against more/larger real decks.

- **Objective generation runs concurrently (`ThreadPoolExecutor`, bounded by
  `LLM_MAX_CONCURRENCY`) — sequential was measured, not assumed, to miss the
  3-minute target.** The first successful full build (12 units, sequential,
  before the concurrency fix) took 367s end to end. Concurrent, the same
  deck's remaining objectives batches ran in 100s / 73s / 48s across three
  resumes. Worth knowing if `LLM_MAX_CONCURRENCY` is ever lowered for
  gateway rate-limit reasons: it directly trades off against this module's
  own "under 3 minutes" acceptance target.

- **`OpenCode Zen`'s `cost` field in every chat completion response is
  always the literal string `"0"`**, regardless of actual token usage
  (checked directly: same request at `max_tokens=50/500/1500` all returned
  `cost: '0'`) — not real per-call billing, just an unwired placeholder on
  this gateway. `packages/llm/logging.py` was deliberately left as-is
  (env-configured `LLM_COST_RATE_*`, `NULL` if unset) rather than trusting
  it. Re-check if OpenCode Zen ever wires this field up for real.

- **Pre-existing bug found while building this module:** `service.py`'s
  document registry (`upsert_document`, keyed on `file_hash`) hashes the
  *converted* PDF for PPT/PPTX/ODP uploads, and LibreOffice's PDF export
  embeds a fresh timestamp on every conversion — so re-uploading the exact
  same `.pptx` gets a different `document_id` every time. Confirmed in the
  existing cache: `data/slidevision-cache.sqlite` has 4 different
  `document_id`s all named `Week 15 IR Optimization.pptx`. The new
  block-level `document_id` (hash of the *original* upload, computed before
  conversion) does not have this problem — but `upsert_document`'s own
  `document_id` param is untouched here to keep this module's diff minimal.
  Point `upsert_document` at the same original-file hash when someone next
  touches the document registry.

## From "evidence-anchoring" module (packages/planbuilder/evidence.py, anchor.py, validate.py)

- **No separate `evidence_cards` table** — matches the existing schema
  (`learning_objectives` + `objective_expected_ideas` + `objective_misconceptions`,
  built by the "Database Schema" module before this one). An "evidence card"
  is represented implicitly as one objective's rows across those two child
  tables; there was nothing to add.

- **`source_block_ids` (named in §2.6 Stage 4's JSON example) isn't a
  persisted column.** Trusting the model to list which block ids it used is
  exactly the kind of unverified claim this module exists to eliminate —
  it's derived instead, at read time, from the `block_id` on each
  *anchored* idea (`scripts/build_plan_demo.py`'s report/example-card
  printer does this). Add a computed property or a view if some future
  consumer needs it as a first-class field rather than a derived one.

- **Prior-objective context grows without bound across the curriculum.**
  `evidence.py`'s prompt includes every objective that comes before the
  current one in unit/objective order, so objective #40 in a 41-objective
  plan carries ~39 prior statements versus #2's one. This is the most
  likely cause of the real run's observed slowdown/timeouts concentrated
  on the last few objectives (see below) — confirmed correlated, not proven
  causal. Consider windowing to same-unit + immediately-preceding unit(s)
  only if this gets worse on larger real decks.

- **A real 41-objective run (`scripts/build_plan_demo.py` against the
  40-slide demo deck) took ~20 minutes of cumulative wall time across
  several resumes** (one genuine network outage included) even at
  `LLM_MAX_CONCURRENCY=4` — evidence generation is one LLM call *per
  objective*, so a real course with more objectives will scale linearly
  against that concurrency ceiling. The current demo script is a
  synchronous CLI with no progress-polling API; a real UI-facing build
  would need `GET /plans/{id}` (already returns partial state, since the
  job persists incrementally) polled from the frontend rather than a
  blocking wait.

- **Objectives whose LLM call never succeeds even once are indistinguishable,
  in the DB, from an objective the evidence stage hasn't reached yet** —
  both have zero `expected_ideas` and zero `misconceptions`. This is the
  correct resumability signal (`apps/api/jobs/plan_build.py::is_incomplete`)
  but means there's no way to tell "never attempted" from "attempted and
  transport-failed every time" without reading application logs. On the
  real run, 5/41 objectives fell into this bucket from `LlmRequestError`
  (read timeout) and `StructuredOutputError` (empty content) failures —
  not anchoring-quality failures; every idea the model *did* successfully
  return anchored (118/118, 100%, see the build report). A dedicated
  failure-count/last-error column would help distinguish these if a plan
  ever gets stuck failing the same objective repeatedly.

- **The build report's `dropped_ideas` detail resets across resumes**
  (documented in `apps/api/jobs/plan_build.py::_result_from_persisted`'s
  docstring) — dropped ideas aren't persisted anywhere, only logged, so a
  cumulative report after multiple resumes undercounts historical drops.
  The summary numbers that matter for the acceptance gate (anchored count,
  `low_confidence`, `zero_ideas`) are unaffected since those come from
  what's actually persisted.

- **No review UI, no embeddings** — both explicitly out of scope per this
  module's own instructions.

## From "Plan Review Interface" module (Module 3: apps/api PATCH/DELETE
objectives, POST approve, apps/web PlanReviewPage)

- **The reviewed-flag approval gate is a frontend affordance only, not
  enforced server-side.** The prompt's acceptance criterion ("Approve button
  disabled until every low_confidence objective has been reviewed") reads as
  a UI behavior, not an API invariant — `POST /plans/{id}/approve` approves a
  draft plan regardless of any objective's `reviewed` value. A determined
  caller (a second tab, a direct API call) can bypass the frontend gate. Add
  a server-side check in `PlanRepository.approve_plan` if this ever needs to
  be a hard invariant rather than a reviewer nudge.

- **No `PlanEditOut` UI** — `GET /plans/{id}/edits` exists (used for
  verification and available for a future audit-trail view) but
  `apps/web/src/pages/PlanReviewPage.jsx` doesn't render it. Nothing in this
  module's prompt asked for an edit-history view in the UI itself.

- **Misconceptions are read-only in the review UI.** The prompt's PATCH
  spec only names "add/edit/remove expected ideas" — `objective_misconceptions`
  rows are displayed nowhere in `PlanReviewPage` (not fetched into
  `ObjectiveOut.misconceptions` display) and have no edit path. They still
  cascade-delete correctly when an objective is deleted (DB `ON DELETE
  CASCADE`, exercised by `test_delete_objective_cascades_ideas_and_misconceptions`).

- **Adding a brand-new expected idea requires a source-panel text selection**
  (`SourcePanel.jsx`'s "Add as new idea" flow) — there is no "add idea with no
  anchor yet" affordance, since every `objective_expected_ideas` row has a
  `NOT NULL` `block_id`/`char_start`/`char_end` (DB invariant #4: evidence
  must anchor to a real span). This matches the module's own framing of
  manual re-anchoring as "the highest-value interaction," not a gap.

- **No optimistic UI / no per-field save indicator.** Every mutation
  (statement blur, reviewed toggle, idea add/edit/remove, delete, approve)
  round-trips through `PATCH`/`DELETE`/`POST` and then a full `GET
  /plans/{id}` refetch (`PlanReviewPage.jsx::reload`) before the UI updates —
  simple and correct, but means each edit has a visible network round-trip
  rather than an instant local update. Fine at single-reviewer, 41-objective
  scale; revisit if plans grow much larger or latency becomes noticeable.

- **No dedicated route library** — `/plans/{id}/review` is parsed directly
  from `window.location.pathname` in `App.jsx` (`parsePlanReviewRoute`)
  rather than via `react-router-dom`, since the whole app has exactly one
  real URL route. Revisit (add a router) if a second real route is ever
  needed — e.g. Module 4's session runtime page.
