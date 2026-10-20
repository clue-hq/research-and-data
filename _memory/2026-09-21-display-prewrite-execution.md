# 2026-09-21 — Display pages written on the fleet, and shared blocks (SDD on `display/prewrite-and-shared-blocks`)

Spec `docs/superpowers/specs/archive/2026-09-12-display-prewrite-and-shared-blocks-design.md` (+ the
founder ruling of 2026-09-21); plan
`docs/superpowers/plans/2026-09-21-display-prewrite-and-shared-blocks.md`; ledger
`.superpowers/sdd/2026-09-21-display-prewrite-and-shared-blocks/progress.md`. Branch off
`research-streaming` at `ab31814a2`. Opus implementers, every review the controller's own.
Test DB `postgresql+asyncpg://clue:clue@localhost:55040/clue_jerusalem-v1_test` (never the lane DB).

**The change in one line:** display prose is no longer synthesised inside a browser request. The
fleet writes it — the account overview when the account job settles, the contact pages of an
account the first time anyone opens it, every other page on its own first open — and a read became
a *scheduler*: it serves what is stored, marks the sections a queued task will write `pending` with
`Synthesis in progress, please wait a few seconds.`, offers the page's task, and the page re-reads
itself every 5 s while anything is pending.

## What shipped (commits after `ab31814a2`)
- `284ae328b` T1 — `FleetTaskKind.ARV2_DISPLAY_PAGE` + migration `fd8795c4fd5a` (enum value):
  one task per `(subject, page)` through `arv2_display_work_id(subject_kind, subject_id, page)`,
  priority `-80` so a display page always yields to research.
- `e4ca864dc` T2 — the fleet handler `platform/api/clue_api/arv2/display/fleet_handler.py`
  (`display_page_payload(...)`, `people_of`), `ensure_page(job_id=)` so the page's spend is stamped
  on the research job's ledger row (column `entity_research_job_id`), and the worker wiring
  (`arv2_display_page_handler` keyword + kind guard, the discovery precedent).
- `97920e3e6` T3 — the account job offers its own overview page after the committee step, at
  settle, in the settling transaction.
- `bf410aedb` T4 — `ResearchSection.pending` on both contract sides (Pydantic + Zod) and in
  `apps/frontend/docs/api-contracts/accounts.md`; `a68f985b8` fixed the Zafran fixtures, which
  lacked the now-required `pending` on the Zod output type (10 `tsc` errors).
- `933eb8ea2` T5 — the read seam `DisplayPages` as scheduler:
  `PENDING_MESSAGE = "Synthesis in progress, please wait a few seconds."`, page offers with
  `reopen_terminal=True`, contact-page offers on the first open of an account (60 s per-process
  cooldown) and from the contacts tab, `DbWorkQueue` threaded from `projections_app`. Without a
  queue the seam is still the old inline writer.
- `6d0df146f` T6 — the frontend hook `usePendingSectionsRefresh` (`router.refresh()` every 5 s
  while any section is `pending`), mounted in `ResearchDocument`, `ResearchStack` and
  `ResearchOverview`; the client never holds its own copy of the sentence — it renders the served
  `emptyMessage` verbatim.
- `34ab18fbe` T7 — shared blocks: `SectionRecipe.shared_from`, migration `2b702a116c15` (two
  nullable columns, and it retires the two sections' own live blocks), `shared_blocks` /
  `compose_display_block(..., shared=)` / `cited_claim_ids` (replacing the two `_cited` helpers),
  a stale owner re-offered through `_offer_owner_pages`, `PAGE_SUBJECT_KIND` moved
  `page.py → recipes.py` to avoid a blocks→page import.
- This commit T8 — the records: master plan §7, the contract note, the spec status line, this
  file, `_memory/README.md`, the `[display×prewrite]` backlog bullet in `CLAUDE.md`, and the
  DEV_STACK paragraph.

## Rulings taken during execution (controller)
1. **Preflight:** T3 may import `display_page_payload` from `clue_api.arv2.display.fleet_handler`;
   if `lint-imports` objects, the builder moves to `clue_api/arv2/fleet_task.py` (pure) — no
   interface change beyond the import path.
2. **Preflight:** the pending sentence is exactly `Synthesis in progress, please wait a few
   seconds.` (spec ruling 2026-09-21).
3. **T2:** `build_arv2_display_page_handler(settings, secrets, *, artifacts, conn_factory=transaction)`
   instead of `storage=` — the brief's body would have imported `DurableAgentArtifactStore` inside
   `clue_api.arv2` (forbidden by the arv2 import guard); the sink is built in `fleet_main` and
   injected, the R4 precedent.
4. **T3:** a settle whose committee step exploded **still** offers the overview page — the account
   job completed and its claims exist, and spec §2 keys the offer on the account job settling, not
   on the committee. The pre-existing test's `not store.named("enqueue")` was narrowed to "no
   research offer, exactly one display offer".
5. **T5:** `page()` stamps `pending` on **every** section (`False` where nothing is coming) rather
   than only on pending ones — the composed dict had no key and the contract default is `False`, so
   the wire shape is unchanged.
6. **T5:** the "matches nothing" test seeds a claim-free account+contact instead of the fixture's
   `silent` contact — every contact recipe also admits account keys, so Zafran's account claims
   fill four of five sections for anyone under it.
7. **T7:** the insights test asserts `generated + skipped_empty == the four owned sections` (the
   shared fixture holds no claims for two of them); the brief's `generated == four` was impossible
   on that fixture — the property is the same.
8. **T7 (parked, product-visible):** an **unwritten** owner is not offered from the sharing page —
   only a stale one is. The overview is written at settle and on the account's own screen, and
   contact owners by the on-open sweep, so Insights can read empty for `context-only` only until
   the overview's first write. Fix if wanted: one more `_offer_page` call in `_offer_owner_pages`
   when the owner block is absent.

## Verified first-hand (controller, per task)
- Every task's diff read before it was accepted.
- T1: pure + DB parity tests re-run; one head `fd8795c4fd5a`.
- T2: handler + page + wiring suites and `lint-imports` re-run; the ledger column confirmed
  `entity_research_job_id`.
- T3: driver suite, 42 passed.
- T4: `contract_v1` 49 passed; frontend 3238/3239 (1 pre-existing skip); after `a68f985b8`,
  `tsc` grep on the two touched files empty and `npm test` 3242/3243.
- T5: the five suites re-run.
- T6: `npm test` 3242 pass / 1 skip and lint 0 errors.
- T7: 175 passed / 1 skipped across the display, seam, workspace, detail, contacts and migration
  suites; one head `2b702a116c15`; `lint-imports` 28/0.
- **The frontend build gate ran green** after T7, with the lane stack down (runbook rule):
  `npm run design-system:build` + `npm run lint` (0 errors, 2 pre-existing warnings) +
  `npm run build` ("Compiled successfully"), exit 0, stack restarted afterwards. During execution it
  was deliberately skipped per task (the lane's dev server uses this worktree's plain `.next`;
  `npx tsc --noEmit` carries 61 pre-existing errors, none in touched files).
- Notes on the other gates: `tests/api/test_fleet_wiring.py::test_the_discovery_handler_is_off…` fails only
  with the lane `.env` sourced (pre-existing key leak, slice-5 note) and is green in a clean env;
  `tests/arv2/test_import_guard.py` is pre-existing red on two other files (ruling T1-1 of slice 5);
  `ruff format --check` on `frontend_read/project_memory.py` is pre-existing red.

## Owed — founder-triggered live proofs (they spend money; not run here)
1. Launch account research on one account; when the account job settles, `fleet_task` holds one
   `arv2_display_page` row for its overview; opening the account shows written sections with no
   wait, and the `provider_call_ledger` rows for the page carry the account job's `job_id`.
2. Open a researched account whose contact pages do not exist: the contacts tab and the overview
   each offer the members' pages once; opening a contact within seconds shows every section as
   `Synthesis in progress, please wait a few seconds.`; the page fills in on its own within two
   polls; no request took longer than the read itself.
3. Open a contact with no claims: no placeholder, the ordinary "No … information found" text, no
   task offered.
4. Add a claim under a written section's recipe; open the page: served as stored, one
   `arv2_display_page` task queued, and the section is replaced on a later open.
5. The insights page shows `Context only` equal to the overview's `Watch-outs` items and
   `Contact insights` equal to the committee's `Why this person` items, with no
   `display-insights-context-only` / `display-insights-contact-insights` labels on the ledger after
   the migration.

Also owed: the live placeholder→content proof for the 5 s poll (T6's poll is source-asserted only;
there is no React renderer in the `node:test` setup). Nothing else — the frontend build gate is
done and green (see above).

## Residuals / deferred minors
- **Deployment.** `projections_app` composes `DbWorkQueue()` unconditionally, so **every**
  deployment with `CLUE_ARV2_DISPLAY_GENERATE_ON_READ=true` now *schedules* instead of writing
  inline; its fleet workers must compose the T2 handler (the same flag on, plus
  `CLUE_OPENROUTER_API_KEY`) or pages simply stop being written. Recorded in `DEV_STACK.md` and the
  `CLAUDE.md` backlog.
- **Deployment.** Migration `2b702a116c15` retires every live `insights/context-only` and
  `insights/contact-insights` block on `alembic upgrade head`; the downgrade does not restore them
  (the next read re-composes them from the owners). Other lanes on this machine need
  `alembic upgrade head` (both migrations) before running this branch.
- **Deployment — migrate BEFORE booting (found live on the lane, 2026-09-22).** A fleet worker
  booted on this branch against an un-migrated DB **crashes at boot**:
  `clue_api.composition.load_research_packs` seeds the display recipes and hits an asyncpg
  `UndefinedColumnError` on `display_section_recipe.shared_from_page`. `dev_stack … up` then
  reports the workers DOWN with the traceback in `/tmp/<lane>_fleet_worker.log`. The rule: bring the
  lane DB to `2b702a116c15` first, then boot (or `restart-workers`). The failure is loud, not
  silent.
- An unwritten owner is not offered from the sharing page (parked ruling 8 above).
- The contact-offer cooldown (60 s) and the in-flight regeneration table are **per web process** — a
  second twin may offer once more; a DB no-op by dedup on the work id.
- A pending section on a page whose provider is refusing shows the provider-incident outage
  sentence and keeps polling.
- The inline write survives only as the queue-less fallback and the CLI.
- T2: a malformed `job_id` in a payload is silently downgraded to unstamped spend with no log line
  (`fleet_handler._scope`).
- T3: no explicit test for the enqueue-failure branch or the person-job early return of
  `_offer_display_page`.
- T4: `zod-fields.json` covers only the six top-level payload schemas, so nested `ResearchSection`
  parity between Pydantic and Zod has **no mechanical oracle** (pre-existing gap; `pending` was
  added on both sides by hand). Every section now serialises `"pending": false`, the same posture
  as `restricted`/`defaultOpen`.
- T5: the queue path reads live blocks + staleness twice per read (once in
  `_offer_missing_and_stale`, once in `page()`).
- T7: `tests/api/test_frontend_read_v1_live_zafran_db.py` **skips** on the throwaway DB (no answer
  key), so its insights expectations are unverified until it runs on a D1/D2-seeded DB;
  `_offer_owner_pages` re-reads the owner recipes per shared recipe per read.

## Addendum 2026-09-22 — the insights page is written at settle too (founder ruling)
`Arv2AccountResearchWorkHandler._offer_display_page` now offers `("account", id, "overview")` and
`("account", id, "insights")` in that order (`_SETTLE_PAGES`), each its own `arv2_display_page`
task with the job id stamped; the driver tests assert both offers. The insights task writes only its
four owned sections; `context-only`/`contact-insights` still compose from the overview's and the
members' blocks at read time, so nothing is synthesised twice. Spec §6's "not at settle" line is
struck. Workers must be restarted to pick this up (done when the queue was idle).
