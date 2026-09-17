# ARV2 onboarding O3 follow-up — the catalog identity ladder (branch `onboarding/o3-catalog-identity-ladder`)

Executed via SDD in the worktree `/Users/aryankeshri/.claude/worktrees/semarang-o3b` against the
throwaway DB `clue_o4_agent`. Base: `integration/design-improvement` @ `7adeab870`.
Plan: `docs/superpowers/plans/2026-09-08-arv2-onboarding-o3-catalog-identity-ladder.md`.
Tasks/briefs/reports: `.superpowers/sdd/2026-09-08-arv2-onboarding-o3-catalog-identity-ladder/`.
Contract: `docs/specs/ARV2-PRODUCT-CATALOG-CONTRACT.md` §3, §5.1 (new), §6.2, §5/§6 pointers.

## Why (the evidence)

Four live re-runs on ONE workspace grew that brand's `product` rows **19 → 28**: the lineup asks the
same question every run and the model spells the same offering differently each time
(`Referrals AI Agent` / `Referral Management AI Agent` on one page; `Aura™ AI Scribe`;
`AI FrontDesk Agent` cited to the homepage).

Proof of concept over the four stored catalogs (`/tmp/o3-dedupe-poc/`, 2026-09-08):

- exact spelling alone merges only the mark/spacing cases;
- a model shown the page URLs as evidence merges every drift pair and keeps the two genuinely new
  offerings — **28 → 18 rows, no wrong merge**, identically on `openai/gpt-5-mini` and
  `x-ai/grok-4.6`;
- the one wrong merge seen (a partner program) disappeared once the prompt stated what page
  evidence means;
- the reworded Exa prompt listed each page exactly once *within* a call, but names still drift
  *between* calls (page title vs heading) — so the model stage stays necessary.

## What landed (5 commits, Tasks 1–4 + this note)

1. **`fb16ab7c5`** — migration `be9f4984729a` (revises `a3602967bb73`, single head) widens
   `onboarding_product_lineage_state` to `created | alias_reused | lineage_reused | model_reused |
   model_unsure` (`unresolved_ambiguous` stays the ONLY product-less state) and adds nullable
   `reconcile_confidence` (CHECKed `high|medium|low`) + free-text `reconcile_reason`. `downgrade()`
   RAISEs if a model-decided row exists, then reverses cleanly. Spine:
   `add_product_aliases(conn, *, product_id, workspace_id, aliases) -> Product` — append-only,
   order-preserving, never touches `name`, `ValueError` across a workspace boundary.
2. **`11d6c477d`** — settings `onboarding_catalog_reconcile_enabled` (default `True`) and
   `onboarding_reconcile_model` (default `openai/gpt-5-mini`), with the matching
   `CLUE_ONBOARDING_CATALOG_RECONCILE_ENABLED` / `CLUE_ONBOARDING_RECONCILE_MODEL` lines in
   `.env.example` (and the local `.env`, at parity); `CatalogProduct.official_url` (last field,
   default `None`, **deliberately NOT in `_fingerprint`**); `platform/api/clue_api/arv2/
   onboarding_reconcile.py` — `CatalogReconciler` protocol, `ExistingProduct`, `ReconcileDecision`,
   `RECONCILE_SYSTEM_PROMPT`, `reconcile_output_schema()`, `OpenRouterCatalogReconciler`.
3. **`1e67617a1`** + **`b0b839729`** — the ladder inside `synchronize_catalog(..., reconciler=None)`,
   alias write-back, the two new `ProductLink` fields; then rung 2 replaying *every* prior binding.
4. **`baf89c969`** — the Exa lineup text (`LINEUP_SYSTEM_PROMPT` + two
   `product_catalog_output_schema()` descriptions) asking for the offering's own page and that
   page's own spelling; `reconciler_factory` threaded through `OnboardingRunWorkHandler`;
   `fleet_main._build_catalog_reconciler_factory`; contract §3/§5.1/§6.2 and the frontend
   `api-contracts/projects.md` pointer.
5. **This task** — the standing-rule checklist below, this note, the `_memory/README.md` pointer,
   and two carried-over doc fixes (the `_TOKEN` comment in `onboarding_lineage.py` still described
   the removed stoplist; a mid-sentence break in the `arv2/README.md` normalization paragraph).

## The ladder as coded (`onboarding_lineage.py::synchronize_catalog`)

Per entry, stopping at the first rung that answers:

1. **the same lineage row** — a row already at `(document_id, ordinal)` is mirrored verbatim
   (product, state, count, and now both reconcile columns). A fingerprint mismatch still raises
   `ValueError("catalog document entry changed under its lineage")`.
2. **a prior lineage binding of the same entry fingerprint** → `lineage_reused`.
3. **the entry's spelling key** (`normalize_identity`) against names **and aliases** on file — one
   hit `alias_reused` (writing the observed spelling back), several hits `unresolved_ambiguous`.
4. **one batched model reconciliation after the loop** over everything left over, shown each
   entry's `official_url` and `short_description` as evidence.

Automatic merge is narrow: rungs 1–3, plus rung 4 only at `confidence == "high"` → `model_reused`.
Every other `same_*` verdict **mints** and is recorded `model_unsure` with the model's confidence
and a reason carrying its suggestion, for the human gate. A duplicate is recoverable; a wrong merge
silently retargets a campaign. Every rung-3/rung-4 match writes the observed spelling back via
`add_product_aliases`, so the next run's rung 3 resolves deterministically what rung 4 reasoned
about. The only spine writes on this path are `INSERT product` and appending aliases — nothing
renames, merges or archives a row.

## Founder rulings (2026-09-08)

- **No generic-token stoplist.** `normalize_identity` keeps every word; dropping "AI"/"Agent"-style
  tokens is a one-company heuristic that would silently merge distinct products elsewhere.
- **A shared page is evidence, never an automatic key.** Many sites present several offerings on one
  page, so the same `official_url` is strong evidence, not a rule.
- **Automatic merge only for the deterministic rungs and high-confidence model decisions.**
  Everything else is minted and flagged `model_unsure` for the gate.

## Controller rulings this lane

- **Rung 2 replays any prior lineage binding regardless of state** (`b0b839729`). A lineage row IS
  the durable decision: a `high` merge was applied by design, and a `model_unsure` row bound its
  entry to the row it minted. Re-deriving either through rung 3 is not guaranteed to reach the same
  answer (a second product carrying the same alias would turn the entry `unresolved_ambiguous`), so
  the binding is replayed, not redone — and the identical entry never reaches the model twice.
- **In-run repeats of a leftover's spelling key follow that leftover and never reach the model.** A
  later entry whose key matches an earlier *leftover's* key is queued as a repeat, resolves to
  wherever that leftover landed, and is recorded `alias_reused` (with the write-back). This keeps
  the model's candidate list unique by spelling key, so its name-keyed answer stays unambiguous.
- **A 402 / halt degrades like any other failure.** `OpenRouterCatalogReconciler.reconcile` never
  raises: a non-200, a halt, a transport error, an unparseable body or a malformed decision becomes
  a full set of `new_product` / `low` decisions carrying the reason. The run mints and flags; it
  does not stop. `_validate` likewise turns an unknown product id, a self- or forward-candidate
  reference, a missing entry or an unknown enum into `new_product` / `low`.
- **`CatalogProduct.official_url` was added in Task 2 and fingerprints are unchanged.**
  `_fingerprint` still hashes only `name`, `short_description`, `aliases`, `POLICY_VERSION`, so
  existing lineage rows keep replaying.
- **Row descriptions shown to the model come from this run's own entries.** The spine `product` row
  carries neither a description nor a URL, so `ExistingProduct` is filled from the catalog entry
  that named that row in this same run, and is otherwise empty — there is nothing honest to show.
- **The model stage is a factory of one reconciler per run** (`fleet_main._build_catalog_reconciler_factory`),
  because the call spends through a `ProviderCaller` writing under
  `arv2_raw_root/onboarding/<run_id>/catalog-reconcile/`. Unlike the Exa key, a missing
  `CLUE_OPENROUTER_API_KEY` does **not** cost the lane its handler: the worker composes without a
  factory, logs `onboarding.reconciler_not_composed` once, and the ladder runs rungs 1–3 only.
  The factory call sits inside `_catalog_sync`'s `try`, so a hypothetical raise lands the step
  `failed` with its reason rather than dying in `handle`'s containment.
- **`_should_reconcile`**: the call is skipped when nothing was left over, and when a single
  leftover has nothing on file to compare against (the answer is knowable without spending).

## Standing-rule checklist (`_memory/2026-09-07-no-old-lane-gate-may-block-new-lane.md`)

Run 2026-09-09 against `git diff 7adeab870..HEAD`. All seven pass.

1. **Profile grants** — PASS. No file matching `profile` / `head_of_abm` is touched by the diff; no
   tool grant changed, so the boot-time audit's refusal set is untouched.
2. **Gate source** — PASS. The diff contains no `compile_client_knowledge_card_v2`,
   `current_kb_version`, `load_pinned_client_knowledge`, `ClientKnowledgeCard` or
   `ProductKnowledgeCard`. The ladder writes spine `product` rows and the artifact-keyed
   `onboarding_product_lineage`; the gate reads product rows, as §5–§6 require.
3. **Scope pin content** — PASS. No `agent_turn_scope_pin`, `AgentTurnScopePinConflict` or
   `company-and-selected-product` anywhere in the diff.
4. **Context composition** — PASS. No card compiler, no `Stage0ProjectStateCard` /
   `ProductProfileCard`, and `CLUE_MEMORY_ENABLED` is untouched.
5. **Launch path** — PASS. The diff mentions no `launch_account_research`,
   `product_selection_version`, `project.product_id` or `readiness_decision_id`; no new
   precondition was added anywhere near the launch path.
6. **Static guard** — PASS. `tests/arv2/test_import_guard.py` (4 tests) green; the new
   `onboarding_reconcile.py` imports only `clue_api.arv2.*`, `clue_obs`, `pydantic` and stdlib —
   no `clue_gateway`, no provider SDK, nothing quarantined.
7. **`.env.example` posture** — PASS, untouched: `CLUE_SELF_SERVE_PROVISIONING_ENABLED=false`
   (line 121), `CLUE_STAGE0_OFFICIAL_SITE_CRAWL_MODE=off` (line 91),
   `CLUE_ENTITY_RESEARCH_RUNTIME_ENABLED=false` (line 380). The lane added only its own two keys.

Brief's greps, 2026-09-09:

- `grep -rn "client_kb_version\|readiness_decision\|project_run_stage0_pins\|evaluate_stage0_readiness"
  platform/api/clue_api/arv2/onboarding_reconcile.py platform/api/clue_api/arv2/onboarding_lineage.py`
  → **zero hits**.
- `set -a; source .env; set +a; uv run alembic heads` → **`be9f4984729a (head)`**, exactly one line.

## Verification performed

- Task 1: migration up → down (`a3602967bb73`) → up on `clue_o4_agent`;
  `tests/db/test_arv2_onboarding_lineage_reconcile_migration.py` +
  `tests/clue_spine/test_product_aliases_db.py` + `tests/db/test_arv2_onboarding_kind_migration.py`
  → 5 passed (proven red first). Regression `tests/clue_spine tests/arv2/test_onboarding_lineage_db.py`
  → 25 passed.
- Task 3: `test_onboarding_lineage.py` + `test_onboarding_lineage_db.py` +
  `test_onboarding_reconcile.py` + `test_import_guard.py` → 29 passed (proven red first).
- Task 4: `uv run pytest tests/arv2 --ignore-glob='*_live.py' tests/api/test_fleet_wiring.py`
  → **628 passed in 22.6s**; `uv run ruff check platform/api/clue_api/arv2 tests/arv2` clean.
- Task 5 (this one): `git diff --check` clean;
  `uv run ruff check platform/api/clue_api/arv2/onboarding_lineage.py` → all checks passed;
  `uv run pytest tests/arv2/test_import_guard.py tests/arv2/test_onboarding_lineage.py
  tests/arv2/test_onboarding_reconcile.py tests/arv2/test_onboarding_settings.py -q` → 24 passed.
- **No `make check` and no repo-wide pytest** at any point: `.env` holds real provider keys.
- **No live provider call was made by this lane.** The reconciler has no live test in the suite.

## Not this lane (open, unowned unless stated)

- **The live proof has NOT run.** Plan Task 6 (a real onboarding run on a workspace with existing
  products, checking the lineage states and that no wrong merge happened) is **founder-triggered**
  and still owed. Nothing here has been exercised against a live OpenRouter call.
- **`_alias_fold` in `clue_spine/spine.py` duplicates `normalize_identity`** in
  `clue_api/arv2/onboarding_lineage.py`. Deliberate: the spine sits BELOW `clue_api` and cannot
  import it. The two must not drift — a shared home would have to be a lower lib.
- **Ruff is not clean repo-wide on the integration branch**: `uv run ruff check alembic/` reports
  **6 fixable errors** (I001 + two F401 each) in two committed design-lane merge revisions,
  `6eff96862040_merge_thumbnail_cache_cancellation_heads.py` and
  `7247c55459c4_merge_design_run_cancellation_clone_.py`. Pre-existing at base `7adeab870`, not
  this lane's to fix, but it means a naive `ruff check alembic/` fails on any O-lane branch.
- **Two migrations off the same head.** This lane's `be9f4984729a` and the sibling lane
  `onboarding/o4-synthesis-split`'s `ae4a5dfb3943` both set `down_revision = "a3602967bb73"`.
  Whichever merges into `integration/design-improvement` second must run
  `alembic merge -m "merge be9f4984729a+ae4a5dfb3943" <head1> <head2>` — never a hand-renumber.
- **How `model_unsure` renders in the product-set gate is O6's**, not fixed here; the frontend
  contract pointer (`apps/frontend/docs/api-contracts/projects.md`) says so explicitly.

## Merge addendum (2026-09-09)
Merged into `integration/design-improvement` (merge commits f5d506196 ladder, a3e8a1355 split; one hand-resolved conflict in `tests/arv2/test_onboarding_driver.py` — both lanes had appended tests, both sets kept, 22 pass). Alembic join `850fcace722a` (be9f4984729a + ae4a5dfb3943), up/down/up smoked on `clue_o4_split`; `clue_semarang` upgraded to the join. `.env` gained the two reconcile keys. Live proofs (both plans' Task 6) still owed, founder-triggered; the fleet worker on this box must be restarted (reproduce `.env`, never pkill) before either.

## Live proof addendum (2026-09-09)
Run eef4a3fd on Insight Health (merged code, worker restarted): PASSED — see `.context/arv2-onboarding-live-proof-2026-09-09/SUMMARY.md`. Split: ICPs registered at 457 s (was 14–17 min), three persona steps in parallel 457→734 s, run completed in 734 s, 15 evidence calls all under persona executions. Ladder: 21 entries → 18 alias_reused, 1 created (genuinely new page, model high), 2 unresolved_ambiguous (pre-existing ™ duplicate pairs from older runs; O6 gate to merge), products 27→28, one $0.0019 reconcile call. Follow-up (O4): the ICP turn still spends ~110 s reading product files one call at a time; ask for batched reads.
