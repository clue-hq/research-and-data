# ARV2 onboarding O3 — the run driver on the fleet (branch `onboarding/o3-fleet-driver`)

Executed via SDD in the worktree `semarang-o3` against the throwaway DB `clue_o3_driver`.
Base: `integration/design-improvement` @ `602a2dac5` (`071f0fc84` plus the O3/O4 plan-docs commit; the O1 + D1 join is `3742d1281a10`).
Plan/tasks: `.superpowers/sdd/2026-09-07-arv2-onboarding-o3-fleet-driver/`.

## What landed (6 commits, Tasks 1–6)

1. **Fleet kind + lineage table** — migration `af3cf1541ebe` (revises `3742d1281a10`, single head):
   `fleet_task_kind` gains `onboarding_run`; new table `onboarding_product_lineage` keyed on
   `(document_id, entry_ordinal)`. `build_multi_work_worker(..., onboarding_handler=)` with the
   same kind guard as its neighbours.
2. **`clue_api/arv2/onboarding_store.py`** — run/step/document transitions that honour the O1
   CHECKs (both `finished_when_terminal` biconditionals, the `failure_pair` biconditional, the
   step↔document write order), plus the current-run/current-document reads.
3. **`clue_api/arv2/onboarding_lineage.py`** — the catalog synchronizer: lineup entries → `product`
   rows over the artifact-keyed lineage, S5-B's reuse ladder ported verbatim
   (`created` / `alias_reused` / `lineage_reused` / `unresolved_ambiguous`).
4. **`clue_api/arv2/onboarding_driver.py`** — `OnboardingRunWorkHandler`: fast recon
   (overview ∥ lineup→catalog_sync ∥ reviews) off the loop via `asyncio.to_thread`, one
   `ProviderCaller` per step under `arv2_raw_root/onboarding/<run_id>/<step>/`, then the synthesis
   turn alongside the per-product fan-out capped at `onboarding_max_parallel_runs`. Two injected
   seams: `ClientEntityBinder` and `SynthesisLauncher` (both optional).
5. **`clue_api/onboarding_routes.py`** — `POST /onboarding` (202, enqueues one task) and
   `GET /onboarding/current`; mounted in `projections_app` behind `CLUE_ONBOARDING_V2_ENABLED`.
6. **This task** — `clue_api/onboarding_client_binding.py` (`Stage0ClientEntityBinder`), the fleet
   composition in `fleet_main._build_onboarding_handler`, the `arv2/README.md` O3 section
   (step graph, seams, composition, evidence sinks), this note.

## Rulings this lane took

- **Artifact-keyed lineage table, not the S5 one.** `product_catalog_lineage`'s identity is a
  Client-KB *claim* (`catalog_claim_id` NOT NULL FK `claim`) plus a NOT NULL KB version; Track O's
  catalog is a knowledge **document**. Re-pointing it would have dragged the Client-KB back onto
  the new lane, so the lane gets its own table and keeps the S5 resolution vocabulary verbatim.
- **The lineage trigger is UPDATE-only, and the document FK cascades.** Append-only means no
  in-place edits (a re-sync writes a new document + new lineage rows); it never meant the row
  cannot be deleted, so `ON DELETE CASCADE` from `brand_knowledge_document` keeps DSAR reach.
  (The S5 precedent `1043a61823f1` reads the same way.)
- **The returned `ProductLink` mirrors the durable lineage row, and a fingerprint mismatch fails
  loud.** A replay reads the existing row (same deterministic `lineage_id` from
  `(document_id, ordinal)`) and returns *its* product/state/count rather than re-resolving; if the
  stored `entry_fingerprint_sha256` disagrees with the entry being synchronized, the caller
  re-published a different catalog under the same document id — the append-only row cannot be
  corrected and returning it would hand back a link for the wrong entry, so it raises instead.
- **`finish_run` is guarded and sums live cost.** It updates only an open run (so the containment
  path can never be walked back off `failed`), returns the status the row *holds*, and sums the
  steps' `cost_usd` — a run with an `empty`/`failed` step lands `completed_with_gaps`, never a
  silent `completed`.
- **The driver holds at most one DB connection at a time**, behind its own `asyncio.Lock`. Its row
  writes are small ordered facts and the parallelism that matters is off the loop entirely; this
  also lets a test inject a single-connection factory without the fan-out colliding on it.
- **A failed enqueue is `fail_run` + 503**, not a queued run nobody will ever drain: the route
  creates the run, and if the queue refuses the offer the run is failed in the same request and
  the caller is told the fleet is unavailable.
- **The binder lives OUTSIDE `clue_api.arv2`.** It reuses `clue_research.stage0`'s client
  resolution, which the lane's import guard forbids inside `arv2/`; the driver holds it as the
  `ClientEntityBinder` protocol and never learns whose resolution it is.
- **Flag on with no `CLUE_EXA_API_KEY` composes NO handler** (this task's ruling). The factory
  raises `ValueError`; `fleet_main` catches it, logs `onboarding.handler_not_composed` naming the
  variable, and drains no onboarding work — the enqueued runs wait for a correctly-credentialed
  worker. Refusing the boot would take every other kind of work on the process down with it; a
  keyless handler would fail each run at its first provider call.
- **`synthesis=None` in the production composition.** O4's `build_onboarding_synthesis_launcher`
  fills that seam at the merge (O4 is a sibling lane, not in this tree); until then the synthesis
  step settles `empty` with "synthesis agent not composed (O4)".

## Standing-rule checklist (`_memory/2026-09-07-no-old-lane-gate-may-block-new-lane.md`)

Run against the onboarding modules on this branch, 2026-09-07 — all seven pass.

1. **Profile grants** — PASS. No readiness / Stage-0 / Client-KB / Product-KB tool name appears in
   `arv2/onboarding_*.py`, `onboarding_routes.py` or `onboarding_client_binding.py`.
2. **Gate source** — PASS. Zero hits for `compile_client_knowledge_card_v2`, `current_kb_version`,
   `load_pinned_client_knowledge`. The catalog synchronizer reads the knowledge document.
3. **Scope pin content** — PASS. No `agent_turn_scope_pin` / `AgentTurnScopePinConflict` path here.
4. **Context composition** — PASS. No `ClientKnowledgeCard` / `Stage0ProjectStateCard` /
   `ProductKnowledgeCard` / `ProductProfileCard` reference; `CLUE_MEMORY_ENABLED=false` unchanged.
5. **Launch path** — PASS. Zero hits for `client_kb_version`, `readiness_decision`,
   `project_run_stage0_pins`, `project.product_id` across the same files. The binder reuses
   Stage-0's *client-entity resolution only* and writes no version, decision or pin.
6. **Static guard** — PASS. `tests/arv2/test_import_guard.py` green (4 tests); it scans
   `platform/api/clue_api/arv2/**`, which is why the binder had to live outside it.
7. **`.env.example` posture** — PASS, unchanged: `CLUE_SELF_SERVE_PROVISIONING_ENABLED=false`,
   `CLUE_STAGE0_OFFICIAL_SITE_CRAWL_MODE=off`, `CLUE_ENTITY_RESEARCH_RUNTIME_ENABLED=false`,
   `CLUE_ONBOARDING_V2_ENABLED=false`.

`uv run alembic heads` → `af3cf1541ebe (head)` — one line.

## Tests (all offline except where the DB is named; no provider calls)

| File | Tests |
|---|---|
| `tests/arv2/test_onboarding_store_db.py` | 6 |
| `tests/arv2/test_onboarding_lineage_db.py` | 6 |
| `tests/arv2/test_onboarding_driver.py` | 6 |
| `tests/arv2/test_onboarding_driver_db.py` | 1 |
| `tests/api/test_onboarding_routes_db.py` | 4 |
| `tests/api/test_onboarding_client_binding_db.py` | 3 |
| `tests/api/test_fleet_wiring.py` (24 total; 3 are Track O) | 24 |

Task-6 gate command — `pytest tests/api/test_onboarding_client_binding_db.py tests/arv2
--ignore-glob='*_live.py' tests/api/test_fleet_wiring.py tests/api/test_onboarding_routes_db.py`
→ **393 passed**. `ruff check` + `ruff format --check` clean on the touched files; `mypy` clean on
`clue_api/arv2`, `onboarding_client_binding.py` and `fleet_main.py`.

The binder tests were written first (RED on the missing module) and each behaviour was then
mutation-checked: skipping the existing-binding read → `WorkspaceClientBindingConflict`; an
unconditional stamp → the already-stamped run is repointed; no stamp at all → two failures.

## Not done / follow-ups

- **The acceptance run was NOT executed — Task 7 is founder-triggered.** No live onboarding run has
  been driven end to end against a real Exa key on this branch; every result above is offline or
  DB-only.
- **O4 merge**: `synthesis=None` in `fleet_main._build_onboarding_handler` must become O4's
  `build_onboarding_synthesis_launcher(...)` when the sibling lane merges. The step's `empty`
  reason string is the marker to grep for.
- **D1 sinks**: `build_onboarding_provider_caller` still writes `FileRawSink` + `JsonlLedger`.
  When D1's `provider_call_ledger` gets its database `LedgerSink` (and the artifact-backed raw
  sink) the swap is at that one composition site; nothing above the sink protocol changes.
- The route is mounted behind `CLUE_ONBOARDING_V2_ENABLED` in `projections_app`; a deployment must
  turn the same flag on for **both** the web process (the route) and the fleet worker (the drain).

## Addendum — name-drift duplicates (2026-09-08, founder ruling)
Four live runs on one workspace grew the product rows 19 → 23 → 28 because Exa spells the same
offering differently run to run (`Aura™ AI Scribe`, `AI FrontDesk Agent`, `AI Phone Triage`) and the
sync reused a row only on an exact normalized match. Commit `a5bdf0ea2`: `normalize_identity` now
strips ™/®/©/℠ before NFKC, casefolds, drops the generic tokens `ai`/`agent`/`agents` (kept when a
name is entirely generic), and joins the rest with nothing (spacing/punctuation-insensitive); the
observed pairs are pinned as tests, including the pairs that must STAY separate (`… for Clinics`,
`Referral Management …`, `… AI Intake`). The lineup query names the brand's known products on a
re-run through an injectable `known_products` reader (default: `clue_spine.list_products`); a
failing reader degrades to the bare query. Fingerprints unchanged, so existing lineage still
replays. Not done: the 28 existing rows are neither merged nor renamed (append-only; the
product-set gate prunes). Residual: a real DB error inside the lineup's connection block aborts
that transaction, so the run then fails at the next write — reading the names on their own
connection is a composition change, recorded not done. The semarang fleet worker was restarted on
this code.
