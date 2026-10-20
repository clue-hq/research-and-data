# 2026-09-08 — ARV2 onboarding O4 follow-up: the synthesis split

Branch `onboarding/o4-synthesis-split` (worktree `semarang-o4split`), base `6ed8a4642`, five
commits `4b217b486 … 4a23fd0d7`. Spec:
`docs/superpowers/specs/archive/2026-09-08-arv2-onboarding-o4-synthesis-split-design.md` (founder-approved
2026-09-08). Plan: `docs/superpowers/plans/2026-09-08-arv2-onboarding-o4-synthesis-split.md`.
**Not pushed. The live proof (plan Task 6) has not run — it is founder-triggered.**

## Why

Measured on the two successful Insight Health runs (`280cd8f5`, `54246e39`): synthesis took 12–14
minutes in one turn. The ICPs were finished about four minutes in but only reached the Knowledge
page eight to ten minutes later, because the three personas queued behind each other inside the
same turn and every output row was registered only after the whole turn finalized. Two unchosen
behaviours also showed up: the launcher fed the agent *every* servable document (so a re-run's ICP
turn read the previous run's ICPs **and** personas, ~90 KB of derived text), and the prompt told
the agent to read every file under `product/` (22 files, ~350 KB), which it cannot and does not do.

## What changed

**One run is `1 + N` governed turns**, same recipe (`onboarding-synthesis-unit@1`), same per-brand
system project, same per-turn `$5` budget envelope, same replay short-circuit:

| turn | identity_key | execution id | turn id |
|---|---|---|---|
| ICP (one per run) | `f"{run_id}:icp"` | `operation_id_from_key(identity_key, "onboarding-synthesis-unit@1")` | `uuid5(TURN_NAMESPACE, identity_key)` |
| persona (one per registered ICP) | `f"{run_id}:persona:{icp_key}"` | same rule | same rule |

Old single-turn runs (keyed on the bare run id) are dev data; not migrated.

**Resources — `onboarding-synthesis@v2`.** `prompts/onboarding-synthesis/v2/SYSTEM.md` (the prompt
file is `SYSTEM.md`), `skills/icp-synthesis/v2`, `skills/audience-persona/v2`,
`profiles/onboarding-synthesis/v2`; the v1 profile is `status: retired`. Model, timeouts (60 s
model / 1200 s turn) and the 48-round cap are unchanged from v1. Registry digest re-pinned to
`676ef758e01e667ee9ad18f2a25203bbd71d86ffe0d32c04f2a95e9a9a8286da`
(`tests/api/test_agent_registry_wiring.py`).

**Surface.** The ICP turn resolves the role on the declared surface `onboarding_icp`
(`ONBOARDING_ICP_SURFACE`, `agent_registry_wiring.py`), which withholds `exa_search_evidence`
(reason code `icp_turn_writes_from_files_only`). That is the role's whole spendable surface, so the
ICP turn is structurally unable to spend — the ICP skill's "from the files and nothing else" is now
a tool that is not installed rather than a sentence. **Deliberate consequence:** the effective skill
set on that surface is `["skill:icp-synthesis@v2"]` — `audience-persona` drops out because it
requires the withheld tool — so the narrowed resolution has its own aggregate manifest digest while
carrying the same reviewed profile ref and prompt. Persona turns resolve the unnarrowed role.

**Inputs (`_select_inputs`, `onboarding_synthesis_wiring.py`).**

- ICP turn: focus = the core three (company overview, product catalog, customer reviews) + **every
  ICP on file**; seeds = the same + every `product-research` file.
- Persona turn: focus = the core three + **the one ICP** (exact version); seeds = the same + only
  the `product-research` files whose own front-matter `product_id` that ICP's `product_ids` names.
  A product file whose product id cannot be read is **kept** (over-inclusion is harmless, omission
  hides research from the one turn that writes about the buyer).
- `audience-persona` rows are **never** an input to either turn (a persona is this surface's
  output; feeding it back would let a re-run copy itself).

**Opening context.** `DbCompiledContextCardReader(storage=...)` gained `object_type =
"brand_knowledge_document"`: the card body is the verified artifact text (`read_verified_artifact`)
and `ref.version` is the document row's version. A row still `running`, or with no `artifact_key`,
is an honest miss (`None`), never a blank body. The launcher passes exact-version `DomainObjectRef`s
as `AgentTurnRequest.focus_refs`, so the core documents are messages in the opening context on the
model's first call; they are **also** seeded read-only under `inputs/brand/knowledge/` so citations
keep their paths. The L5 focus budget is `262_144` bytes (`utf8-bytes-v1`) — v1's 8 KiB could not
hold a company overview, and an over-budget candidate is excluded *silently*, so every input
previously arrived as a path only.

**User-message objectives.** `Task: icp. Write the ICP documents, then finalize_turn.` plus, when
any ICP is on file, ` ICPs already on file: <key> (<path>, version <n>); …` — the keys must be
*named in the instruction* for the known-ICPs rule to be honourable. Persona: `Task: persona:<key>.
The ICP is <path>, version <n>. Write outputs/audience/persona-<key>.md, then finalize_turn.`
A persona turn skips (and logs) an `icp-definition` output or a persona written for another key.
`icp_version` in persona front matter is the **registered document version**, never a literal `1`.

**Driver (`arv2/onboarding_driver.py`).** The `synthesis` step keeps its kind and its fast phase and
now covers the ICP turn only. Each persona is its own step `kind='persona'`, `phase='background'`,
`subject_ref=<icp_key>`, opened the moment the ICP turn returns (never after the product reports)
and queued on the same `onboarding_max_parallel_runs` semaphore as the product fan-out, so the cap
counts both. An ICP turn that ends anything but `completed` opens no persona step. Duplicate ICP
keys in the returned work list are deduped loudly (the step identity *is* `(run, 'persona', key)`).
`fleet_main._SynthesisSeam` carries both calls, copying the four `RegisteredIcp`/`IcpRef` fields in
both directions — the lane may not import the synthesis wiring.

**Migration `ae4a5dfb3943`** (down `a3602967bb73`): widens the `onboarding_step_kind` CHECK to admit
`persona`. `downgrade()` RAISEs if any `persona` step exists (house convention, same shape as
`000b9d8bb17b`). The `onboarding_step_identity` index already keys on
`(run_id, kind, COALESCE(subject_ref, ''))`, so repeating a kind within a run needed no index
change. It is the only revision off `a3602967bb73` in this tree — one head here.

## The hang guard, and the live hazard behind it

`SYNTHESIS_TURN_HARD_TIMEOUT_S = 1800.0` wraps **each** launcher call in `asyncio.wait_for`; a trip
lands that one step `failed` with `failure_code="turn_hung"` and logs
`onboarding.synthesis_turn_hung`. Every other step and the run itself keep going. This is
containment, not an agent cap (the profile already has a 1200 s turn timeout).

**The hazard it contains is not this lane's to fix.** `RecipeExecutor.execute`
(`platform/execution/clue_execution/executor.py:864`, the `while True:` cursor loop) spins forever
when a recipe gate is opened and its dynamic child never completes — a refused governed tool call
(e.g. `exa_not_configured`) is still a *tool result*, so the child stays incomplete and the cursor
never reaches a terminal status. Reproduced at base `50afb9c67` with the untouched launcher.
**Owner: the execution substrate.** Consequence accepted here: the DB suite no longer scripts the
persona turn's evidence call, which loses the coverage of the pin-provider `conflicting_requirement`
guard (`OnboardingSynthesisStepPinProvider` — it must *not* re-request the statically pinned
`audience-persona` skill; that was live-run failure #2 on 2026-09-08).

## Standing-rule checklist (`_memory/2026-09-07-no-old-lane-gate-may-block-new-lane.md`)

Run against `git diff 6ed8a4642..HEAD` on 2026-09-08. **7/7 pass.**

1. **Profile grants — PASS.** The Head-of-ABM profile is untouched; the only profiles in the diff
   are `onboarding-synthesis` v1 (retired) and v2. Grepping the diff for `evaluate_stage0_readiness`,
   `override_stage0_readiness`, `start_confirmed_project_run`, `list_client_knowledge`,
   `inspect_client_claim`, `list_product_knowledge`, `inspect_product_claim`, `synthesize_icps`,
   `submit_onboarding_input`, `start_recon` returns nothing. v2's whole tool list is
   `exa_search_evidence@1`.
2. **Gate source — PASS.** No `compile_client_knowledge_card_v2`, `current_kb_version`,
   `load_pinned_client_knowledge`, `ClientKnowledgeCard`, `product_set_selection` or
   `open_product_selection_gate` anywhere in the diff; the product-set gate is untouched.
3. **Scope pin content — PASS.** The synthesis wiring writes no `agent_turn_scope_pin` and names no
   `company-and-selected-product-*` pin kind; the turns are brand-scoped.
4. **Context composition — PASS.** The new L5 source is `brand_knowledge_document` (verified
   artifact bytes) plus the seeded knowledge files; no Client-KB card compiler runs. The assembler
   is `_NoMemoryContext` with L4 = 0 and L6 = 0; `.env.example` `CLUE_MEMORY_ENABLED=false`
   unchanged.
5. **Launch path — PASS.** `account_research_launch.py` and every launch precondition are untouched
   by this diff; no new `client_kb_version` / `readiness_decision_id` / `project.product_id`
   requirement is introduced.
6. **Static guard — PASS, run.** `uv run --frozen pytest tests/arv2/test_import_guard.py -q` → 4
   passed. The guard walks `platform/api/clue_api/arv2/**`, which includes the changed
   `onboarding_driver.py`.
7. **`.env.example` posture — PASS.** `.env.example` and `settings.py` are not in the diff;
   `CLUE_SELF_SERVE_PROVISIONING_ENABLED=false`, `CLUE_STAGE0_OFFICIAL_SITE_CRAWL_MODE=off`,
   `CLUE_ENTITY_RESEARCH_RUNTIME_ENABLED=false` all still as written. The split introduced no new
   flag.

## Pre-existing failures at base (NOT this lane)

Confirmed present at `6ed8a4642` before any lane commit:

- `tests/api/test_production_context_s3_db.py` — 3 failures (a pydantic `Field` required error
  around line 165).
- `tests/api/test_agent_registry_wiring.py::…head_resource_map` — 137 vs 139.
- the `design_profile` model assertion in the same file — `LUMEN_AGENT_MODEL` is set in the local
  `.env`.

## Owed

- **The live proof — plan Task 6, founder-triggered.** One unseeded Insight Health re-run on the
  current catalog. Spec §6 acceptance, all six:
  1. the three ICP documents are servable within ~6 minutes of the request (`synthesis` step
     `completed`, ICP rows present) **while `persona` steps are still running**;
  2. three `persona` steps run concurrently and the run settles `completed`;
  3. the ICP keys on file are reused — no new `audience/icp-*` path;
  4. each persona front matter's `icp_version` equals its ICP row's version;
  5. fifteen `exa_search_evidence@1` invocations, as before;
  6. **no** `exa_search_evidence@1` invocation attributed to the ICP turn.
- **`alembic merge`** if the catalog-identity-ladder lane (also cut off `a3602967bb73`) merges
  first: `alembic merge -m "merge <a>+<b>" <head1> <head2>`, never a hand-renumber. `alembic heads`
  must return one.
- Minor doc drift, deliberately not touched: `platform/agents/skills/audience-persona-v1/SKILL.md`
  (the flat pin stub the recipe's discovery resolves) still names the **v1** catalog file as
  authoritative. The recipe pin stays `audience-persona@v1`; editing the stub's body was left alone
  so the discovery digest is not disturbed. The `clue_api/arv2/README.md` bullet now states which
  catalog version the active profile actually pins.

## Files

- `alembic/versions/ae4a5dfb3943_arv2_onboarding_persona_step.py`
- `platform/agents/catalog/{prompts/onboarding-synthesis/v2/SYSTEM.md, skills/icp-synthesis/v2,
  skills/audience-persona/v2, profiles/onboarding-synthesis/v2}` (+ v1 profile retired)
- `platform/api/clue_api/{onboarding_synthesis_wiring.py, agent_registry_wiring.py,
  account_research_turn_wiring.py, fleet_main.py, arv2/onboarding_driver.py, arv2/README.md}`
- `docs/specs/ARV2-ONBOARDING-PLAN.md` (§3 kind enum, §5 addendum, §6.2 addendum, §9 O4 row)
- tests: `tests/api/{test_onboarding_synthesis_inputs.py, test_onboarding_synthesis_wiring_db.py,
  test_agent_platform_wiring.py, test_agent_registry_wiring.py, test_fleet_wiring.py}`,
  `tests/arv2/test_onboarding_driver.py`, `tests/agents/test_catalog.py`,
  `tests/db/test_arv2_onboarding_persona_step_migration.py`

## Merge addendum (2026-09-09)
Merged into `integration/design-improvement` (merge commits f5d506196 ladder, a3e8a1355 split; one hand-resolved conflict in `tests/arv2/test_onboarding_driver.py` — both lanes had appended tests, both sets kept, 22 pass). Alembic join `850fcace722a` (be9f4984729a + ae4a5dfb3943), up/down/up smoked on `clue_o4_split`; `clue_semarang` upgraded to the join. `.env` gained the two reconcile keys. Live proofs (both plans' Task 6) still owed, founder-triggered; the fleet worker on this box must be restarted (reproduce `.env`, never pkill) before either.

## Live proof addendum (2026-09-09)
Run eef4a3fd on Insight Health (merged code, worker restarted): PASSED — see `.context/arv2-onboarding-live-proof-2026-09-09/SUMMARY.md`. Split: ICPs registered at 457 s (was 14–17 min), three persona steps in parallel 457→734 s, run completed in 734 s, 15 evidence calls all under persona executions. Ladder: 21 entries → 18 alias_reused, 1 created (genuinely new page, model high), 2 unresolved_ambiguous (pre-existing ™ duplicate pairs from older runs; O6 gate to merge), products 27→28, one $0.0019 reconcile call. Follow-up (O4): the ICP turn still spends ~110 s reading product files one call at a time; ask for batched reads.

## Follow-up landed (2026-09-09)
`icp-synthesis@v3` adds one sentence: read every named product file in a single turn (batched read_file calls), not one per turn. Profile `onboarding-synthesis@v3` pins it (v2 retired); registry digest re-pinned to `8f2dd5ae030adcfa604a5702f1af85e7d526008aa4b0257be14eb29e2fb4a659`. Merged into integration/design-improvement; semarang worker restarted. Unproven live until the next Insight Health run — expect the ICP turn to drop from ~300 s toward ~180 s.
