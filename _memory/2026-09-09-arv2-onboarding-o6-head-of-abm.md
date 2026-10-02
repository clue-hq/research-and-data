# ARV2 onboarding O6 — the Head-of-ABM integration (`onboarding/o6-head-of-abm`)

Date: 2026-09-09. Branch `onboarding/o6-head-of-abm`, base `3ceb81f36` (= `7e8dd1a7e` + the plan
commit) off `integration/design-improvement`. Worktree `~/.claude/worktrees/semarang-o6`, throwaway
DB `clue_o6_head`. Plan: `docs/superpowers/plans/2026-09-09-arv2-onboarding-o6-head-of-abm.md`.
Spec: `docs/specs/ARV2-ONBOARDING-PLAN.md` §8 (now carrying an "Addendum 2026-09-09 — O6 as built"),
`ARV2-PRODUCT-CATALOG-CONTRACT.md` §6.3/§7, `ARV2-MASTER-PLAN.md` §5.

**Status: built and offline-verified. The live O6 exit gate has NOT run — it is founder-triggered.**
No live agent turn, no real project, no `.context/` evidence for O6 yet.

## What landed, per task

| Task | Commits | What |
|---|---|---|
| 1 | — | Lane setup: worktree at `3ceb81f36`, `clue_o6_head` at head `63294c3ce019`. Baseline reds recorded (two registry failures; `tests/arv2` env-parity green). |
| 2 | `3ceb81f36..8720f3509` | Migration `a3fc75e248e0` — `agent_turn_knowledge_pin` (insert-once per turn). `platform/api/clue_api/brand_knowledge_context.py`: current servable documents, the per-turn pin (`load_or_create_knowledge_pin`), the pinned bodies, seed files under `inputs/brand/knowledge/`, `BrandKnowledgeIndexCard@1`, and `confirmed_icp_for_project`. `onboarding_synthesis_wiring._current_input_documents` delegates to it. |
| 3 | `8720f3509..d513f5f43` | `open_product_set_selection_gate@1` (`product_set_selection_gate_tools.py`) + the set-valued gate answer route (`chat/schemas.py`, `chat/router.py`, `chat/turn_stream.py`: `selected_product_ids` → `confirm_project_product_set`). |
| 4 | `d513f5f43..88421bb68` (incl. fix round `89803d5c4..88421bb68`) | `platform/api/clue_api/arv2/icp_confirmation.py` (`current_icp_document`, `icp_gate_subject_ref`, `icp_gate_snapshot`, `confirm_icp_document`) + `open_icp_confirmation_gate@2` (`icp_artifact_gate_tools.py`) over a knowledge-document artifact ref; `agent_gate.icp_artifact_gate_id`; the `@2` answer branch. |
| 5 | `88421bb68..5197dba8e` | Recipe v22 (`platform/execution/recipes/recipe0-stage0-v22.json`), the four standing addresses in `RECIPE_0_TOOL_ADDRESSES`, `CONVERSATION_RECIPE_VERSION = 22`, `pin_requirements = ("project",)` on the two R2 launch/read tools and both new gate tools, and the Stage-0 project pin provider. |
| 6 | `5197dba8e..b550fdfda` (incl. fix round `7d33a72d3..b550fdfda`) | Prompt `head-of-abm/v8`, skill `stage0-interview/v21`, profile `head-of-abm/v44`; `C6_AGENT_TOOL_AUTHORITY`, `_roles_for`, `_RESERVED_REASON`, the surface policies and the toolbelt default flipped in one commit; `PROJECT_CONVERSATION_AGENT_PROFILE_ID = "head-of-abm@v44"`. |
| 7 | `b550fdfda..5e7ccc5f1` | The production project conversation pins the knowledge documents, compiles the `brand_knowledge_index` card into L3, seeds the pinned bytes read-only, and drops the four old cards (`agent_turn_fleet_wiring`). `input_seeds` threaded through `ConversationTurnEngine.execute` → `HeadOfAbmStage0Runtime.run`; `storage` injected into `ProjectConversationTurnRunner` from `fleet_main`. A reclaimed turn re-verifies its frozen input tree. |
| 8 | `5e7ccc5f1..83817317e` | Frontend: the `product_set_selection` gate card + wire (`selectedProductIds`), the active-only project sidebar, Knowledge title wrap; contract docs (`ARV2-PRODUCT-CATALOG-CONTRACT.md` §6.3/§7.1, `apps/frontend/docs/api-contracts/projects.md`). |
| 9 | this commit | Docs addenda, this note, the checklist and the offline verification, and the §7.1 `resolution_state` example fix (`model_matched` → `model_reused`; no such state exists — §6.2 lists `created`, `alias_reused`, `lineage_reused`, `unresolved_ambiguous`, `model_reused`, `model_unsure`). |

## Decisions D1–D12 (the plan's table; full text in the §8 addendum)

- **D1** Profile v44 drops the eight tools §8 names plus `synthesize_icps@3`, `start_recon@1`,
  `submit_onboarding_input@1`, `open_discovery_configuration_gate@1`; adds
  `open_product_set_selection_gate@1`, `open_icp_confirmation_gate@2`,
  `launch_arv2_account_research@1`, `read_arv2_account_research_run@1`.
- **D2** The launch is R2's `launch_arv2_account_research@1`; the old directive chain stays granted;
  `account-deep-steering@v8` is not rewritten in O6.
- **D3** Gate order: pick the ICP → product-set gate (pre-checked from the ICP's `product_ids[]`) →
  ICP confirmation gate, whose approval stamps `product_selection_version`. The other order is
  tolerated (no stamp; the launch pins the set version itself).
- **D4** `revised` on the ICP gate is recorded in project context, not authored — no ICP-authoring
  tool in O6.
- **D5** The Client-KB v2, Stage-0 project-state, product-profile and product-knowledge cards leave
  the production conversation for **every** workspace, not behind a flag.
- **D6** Knowledge documents are pinned per turn in `agent_turn_knowledge_pin`.
- **D7** Recipe v22 = v19 + the four new addresses + `draft_account_research_directive@5` for `@3`;
  old addresses stay in the slot (the slot is a ceiling, the profile is the grant).
- **D8** The exact-quote rule stays in skill v21 because `record_interview_answer@1` refuses a
  paraphrased quote. Follow-up, not built.
- **D9** `pin_requirements = ("project",)` on the two R2 tools and both new gate tools; the pin
  provider resolves `project` from the execution row or the presenting turn.
- **D10** Product-set gate subject `brand-product-catalog:{brand_id}:{catalog_document_id or 'none'}`
  at the catalog document's version; the catalog contract's
  `client-product-catalog:{client_entity_id}:v{kb}` form is superseded (it named a Client-KB version).
- **D11** The projects sidebar lists `status = 'active'` projects only.
- **D12** `qualifier_fields` registration (seam-freeze 2b) is not built anywhere in the tree; the
  confirmed document keeps them in front matter. Recorded, not built.

## Execution rulings (the ledger, verbatim in substance)

- **Pre-flight, T5 ↔ T6:** `build_agent_profile_registry` refuses to compose when a role's authority
  and its profile's tool list disagree, so changing `C6_AGENT_TOOL_AUTHORITY` in T5 while v43 was
  still active would have broken **every** registry-backed test and a worker boot, not just the
  digest assertion the plan expected. **Ruling:** the authority map, `_RESERVED_REASON` and the
  surface-policy withheld sets moved from T5 into T6, landing in the same commit as profile v44.
- **T2:** the brief said the index card "shrinks under `max_bytes=600`"; one entry is ~480 bytes so
  that literal budget is unreachable. Tested at a reachable budget plus the 600 floor
  (`omitted_count == 2`). Plan-text defect, no cost.
- **T3:** the answer route refuses a `revision_request` on `product_set_selection` (422) rather than
  folding it into `decision_payload` — the trigger admits only `selected_option_refs` on approve and
  no payload on reject/revise. The brief's text was wrong; the frontend never sends text on this kind.
- **T3:** `"open_product_set_selection_gate": ()` was registered **ungranted** in
  `C6_AGENT_TOOL_AUTHORITY` at T3 (the audit refuses an unlisted live tool); T6 flipped the value.
  Never re-add the key.
- **T4:** `open_icp_confirmation_gate@2` was registered with `make_default=False` at T4 (the registry
  digest test derives expected pins from the DEFAULT version, and v43 still pinned `@1`); T6 flipped
  it to default alongside profile v44.
- **T4 (review finding, fixed):** `confirm_icp_document` retires the subject row **only** when it is
  `proposed`, or `confirmed` for the *same* project. Another project's confirmed row stays confirmed
  — retiring it would have broken that project's launch (`_pinned_icp` requires `confirmed` by
  artifact key). **Known limitation:** two confirmed versions of one path can then coexist and
  `current_knowledge_documents` serves only the newest, so the displaced project's index card loses
  its confirmation. Deferred to O7 multi-project.
- **T4 (review finding, fixed):** a replayed confirmation short-circuits before writing, instead of
  re-rendering and recording an orphan artifact.
- **T5:** **recipe v22 re-pins `open_icp_confirmation_gate` at `@2` and drops `@1`** from its
  allowlists/requirements. The compatibility loader resolves one version per tool key; both present
  = `conflicting_requirement` and the seeder refuses promotion (the v16 fresh-boot wedge). `@1` stays
  in `RECIPE_0_TOOL_ADDRESSES` for replay; v19 remains the exact replay input for `@1` turns.
  Consequence carried to T6: v44 MUST pin `@2`.
- **T6:** prompt v8 and skill v21 are the plan's text verbatim — the founder said "proceed" on the
  plan and no separate wording pass happened in chat. A v9/v22 re-pin after a founder edit is cheap.
- **T6 (review finding, fixed):** the **trial** surface withholds `launch_arv2_account_research` and
  both new gate tools.
- **T6:** `READINESS_HISTORY` and `CLIENT_KNOWLEDGE_OVER_CAP` become `_UNRESOLVABLE_BY_DESIGN` in the
  C8 omission contract — the Stage-0 card leaves production composition (D5) and its resolvers were
  retired. The trial (old lane, Phase-6-bound) may still emit them unresolved.
- **T6:** the trial surface now discloses **no** Stage-0 skill at all (v21 requires the three
  withheld tools, so the skill drops). Accepted: the trial is the old-lane dev harness,
  quarantine-bound.

## Standing-rule checklist (`_memory/2026-09-07-no-old-lane-gate-may-block-new-lane.md`)

**6 of 7 pass. Item 7 fails, and not because of this lane** (see below).

1. **PASS.** `grep -c "evaluate_stage0_readiness\|inspect_readiness_history\|list_client_knowledge\|inspect_client_claim\|list_product_knowledge\|inspect_product_claim\|start_confirmed_project_run\|open_product_selection_gate\|synthesize_icps\|start_recon\|submit_onboarding_input" platform/agents/catalog/profiles/head-of-abm/v44/profile.yaml` → `0`. The registry authority assertion is green (`tests/api/test_agent_registry_wiring.py`, only the pre-existing design-profile failure below).
2. **PASS.** `grep -n "compile_client_knowledge_card_v2\|current_kb_version\|load_pinned_client_knowledge" platform/api/clue_api/product_set_selection_gate_tools.py` → no hits.
3. **PASS.** `grep -rn "AgentTurnScopePinConflict" platform/api/clue_api/product_set_selection_gate_tools.py platform/api/clue_api/icp_artifact_gate_tools.py platform/api/clue_api/brand_knowledge_context.py` → no hits. The `product_id IS NULL` composition test passes (`tests/api/test_o6_conversation_composition_db.py`, all green).
4. **PASS.** `grep -n "compile_client_knowledge_card_v2\|compile_stage0_project_state_card\|compile_product" platform/api/clue_api/agent_turn_fleet_wiring.py` → zero hits. `.env.example:117` = `CLUE_MEMORY_ENABLED=false`.
5. **PASS.** `grep -n "client_kb_version\|readiness_decision_id\|project.product_id" platform/api/clue_api/arv2/account_research_launch.py` → no hits at all.
6. **PASS.** `uv run pytest tests/arv2/test_import_guard.py -q` → `....` (4 passed). The guard walks every module under `platform/api/clue_api/arv2/`, so the new `icp_confirmation.py` is in scope; it imports only `clue_storage`, `clue_core`, `yaml`, `pydantic`, SQLAlchemy and its `arv2` siblings.
7. **FAIL — pre-existing, not this lane's doing.** `git diff 3ceb81f36 HEAD -- .env.example libs/clue-config/clue_config/settings.py` is **empty** (O6 added no flag and changed no value), but `.env.example:380` carries `CLUE_ENTITY_RESEARCH_RUNTIME_ENABLED=true`, set by commit `aa476413e` (2026-09-09, *"chore(env): .env.example matches the working deployment"* — the parity sweep that propagated the dev box's `.env` values). `ARV2-MASTER-PLAN.md` §11 and this plan's Global Constraints require `false`. The local `.env` carries `true` too (line 130). **Not touched here** (founder decision; it changes what the running fleet worker composes) — see the follow-ups.

## Offline verification (all run in the worktree on `clue_o6_head`, `set -a; source .env; set +a`)

**Lint / types — clean.**

```
uv run ruff check platform/api/clue_api/brand_knowledge_context.py \
  platform/api/clue_api/product_set_selection_gate_tools.py \
  platform/api/clue_api/icp_artifact_gate_tools.py \
  platform/api/clue_api/arv2/icp_confirmation.py \
  platform/api/clue_api/agent_turn_fleet_wiring.py platform/api/clue_api/head_of_abm_wiring.py \
  platform/api/clue_api/stage0_recipe.py platform/api/clue_api/agent_registry_wiring.py \
  platform/api/clue_api/chat/router.py platform/api/clue_api/chat/schemas.py \
  platform/api/clue_api/chat/turn_stream.py platform/projections/clue_projections/threads.py
→ All checks passed!

uv run mypy platform/api/clue_api/brand_knowledge_context.py \
  platform/api/clue_api/product_set_selection_gate_tools.py \
  platform/api/clue_api/icp_artifact_gate_tools.py \
  platform/api/clue_api/arv2/icp_confirmation.py
→ Success: no issues found in 4 source files
```

**The full offline set**, on an emptied `clue_o6_head` (`DROP SCHEMA public CASCADE; CREATE SCHEMA
public;` then `uv run alembic upgrade head` — the migration tests downgrade to base):

```
uv run pytest tests/api/test_agent_registry_wiring.py tests/api/test_recipe_contracts.py \
  tests/api/test_product_set_selection_gate_db.py tests/api/test_product_set_selection_gate_tool_db.py \
  tests/api/test_icp_artifact_gate_db.py tests/api/test_chat_gate_answers_o6_db.py \
  tests/api/test_brand_knowledge_context_db.py tests/db/test_arv2_onboarding_knowledge_pin_migration.py \
  tests/api/test_onboarding_synthesis_wiring_db.py tests/api/test_fleet_wiring.py \
  tests/agents/test_catalog.py tests/arv2 --ignore-glob='*_live.py' -p no:randomly --tb=no
→ 836 tests: 832 passed, 3 skipped, 1 failed
FAILED tests/api/test_agent_registry_wiring.py::test_design_profile_resolves_with_the_full_granted_write_surface
  AssertionError: assert 'openai/x-ai/grok-4.6' == 'openai/gpt-5.6-terra'
```

The second lane suite:

```
uv run pytest tests/api/test_o6_conversation_composition_db.py tests/api/test_icp_artifact_gate_db.py \
  tests/api/test_production_context_s3_db.py tests/api/test_c8_omission_resolution_contract.py \
  tests/api/test_c8_trial_surface.py \
  tests/execution/test_recipes.py::test_system_seed_is_promoted_digest_exact_and_replay_safe
→ 36 passed in 10.97s
```

**Alembic — one head; db-smoke clean.**

```
uv run alembic heads                → a3fc75e248e0 (head)
uv run alembic downgrade base       → ... Running downgrade 0001 -> , enable pgvector
uv run alembic upgrade head         → ... Running upgrade 63294c3ce019 -> a3fc75e248e0, arv2 onboarding knowledge pin
uv run alembic downgrade base       → ... Running downgrade 0001 -> , enable pgvector
uv run alembic upgrade head         → ... Running upgrade 63294c3ce019 -> a3fc75e248e0, arv2 onboarding knowledge pin
uv run alembic current              → a3fc75e248e0 (head)
```

**No flag added.** `git diff 3ceb81f36 HEAD -- .env.example libs/clue-config/clue_config/settings.py`
→ empty.

## Pre-existing failures, left exactly as they are

Every one of these was red before O6 or is red for a reason O6 recorded. None is a lane defect and
none was fixed here (Task 9 is docs-only).

- `tests/api/test_agent_registry_wiring.py::test_design_profile_resolves_with_the_full_granted_write_surface`
  — asserts `openai/gpt-5.6-terra` on the `design@v1` profile; the composed id is
  `openai/x-ai/grok-4.6` (a malformed double-prefix, recorded back at O4). Red at base.
  *(The lane's other baseline red — `test_head_resource_map_is_exhaustive…`, 137 vs 139 — is now
  GREEN: profile v44's tool list is what it expected.)*
- `tests/api/test_production_context_s31_fleet_db.py::test_real_fleet_chain_keeps_original_pin_through_checkpoint_finalization_and_replay`
  — red at base; its body targets the four cards D5 retired. The **rewrite belongs to the v44
  fallout / Phase 6**, not to O6.
- `tests/api/test_project_read_surfaces_db.py::test_project_shell_is_scoped_real_and_fixture_free`
  — red at base; asserts the Terra model name on the profile id (same cause as the design-profile
  failure).
- `tests/execution/test_recipes.py::test_c67_account_unit_is_preserved_as_replay_only_not_system_seeded`
  and `::test_latest_recipe0_is_the_only_promoted_executable_stage0_revision` — the two seeding
  contracts (replay-only list size; recipe0 version contiguity across the v16–v18 gap). Red at base.
- `tests/api/test_toolbelt_wiring.py::test_out_of_order_matrix` and
  `::test_build_toolbelt_registers_the_full_set` — the `_MATRIX` drift. The drift set is exactly
  `{launch_arv2_account_research, read_arv2_account_research_run, design_set_web_noindex}` — the same
  three unmatrixed tools as at base. **Both O6 gate tools ARE in the matrix**, so O6 did not widen it.

## Deferred minors (from the ledger)

- **T2:** `_summary` skips heading-only blocks — deliberate and tested, not in the brief. Kept.
- **T3:** the product-set snapshot's `omitted_count` counts *unresolved catalog entries*
  (implementer-defined semantics).
- **T4:** the `_roles_for` exact-address rule for `open_icp_confirmation_gate@1`/`@2` had to flip
  together with `make_default` and the v44 pin (done in T6).
- **T6:** seven stale exact-address `_roles_for` rules were deleted and the `@1` ICP gate lost its
  default alias in `agent_gate_wiring` — both forced by composition.
- **T7:** the brief's "a workspace with a `client_kb_version` composes no Client-KB card" scenario is
  not a separate test — the compilation code is *deleted*, so the guard is structural (checklist
  item 4 = zero hits).
- **T8:** the catalog contract §7.3 source chip parses `officialUrl` but does not render it (a
  server-side resolver is not built). The visual check of the wrapped Knowledge titles is owed at
  the live gate.
- **T5:** no DB test drives `_execution_project_pin` on a real turn — the acceptance walk is the
  first proof.

## Follow-ups

1. **`record_interview_answer@2` (D8).** `@1` refuses a paraphrased quote, so the master plan's
   "quote rule removed" line cannot land until a `@2` admits one. Skill v21 keeps the exact-quote
   rule until then.
2. **Qualifier-field registration (D12).** `qualifier_fields` exists only in the confirmed ICP
   document's front matter; registering it into the field catalog is the R lane's, at launch.
3. **`account-deep-steering@v8` rewrite for the ARV2 launch.** v44 still pins the old skill, which
   teaches the old directive/launch chain. Skill v21 teaches only
   `launch_arv2_account_research@1`; the steering skill should follow before the old chain's
   documentation misleads a turn.
4. **The "start onboarding" affordance (O5 finding 3).** The Knowledge page's refresh hook arms only
   when the *server render* sees a live run, so a tab opened before a run starts does not poll until
   reloaded. Whatever surface starts an onboarding run must navigate or refresh after the POST.
5. **The ™ duplicate product pairs.** The O3 identity-ladder run left 2 `unresolved_ambiguous`
   entries — pre-existing ™ duplicate pairs from older runs. They surface at the product-set gate
   flagged `model_unsure`; a human merges them there.
6. **Multi-project ICP confirmation (T4 ruling).** Two projects confirming different versions of one
   ICP path leaves the older project's index card without its confirmation, because
   `current_knowledge_documents` serves only the newest version. Deferred to O7.
7. **`CLUE_ENTITY_RESEARCH_RUNTIME_ENABLED` is `true` in `.env` and `.env.example`** (set by
   `aa476413e`); master plan §11 says it must be `false`. **Flip it back — founder decision, because
   it changes what the running fleet worker composes.** Checklist item 7 stays failing until it is.
8. **`tests/api/test_production_context_s31_fleet_db.py` rewrite** — its assertions target the four
   cards D5 retired; owner is the v44 fallout / Phase 6, not O6.
9. **`tests/api/test_project_read_surfaces_db.py::test_project_shell_is_scoped_real_and_fixture_free`
   and the `design@v1` model-id test** — both assert `openai/gpt-5.6-terra` against the composed
   `openai/x-ai/grok-4.6`. One malformed profile model id, two red tests; fix the profile, not the
   assertions.
10. **The two `tests/execution/test_recipes.py` seeding contracts** — the replay-only list size and
    the recipe0 version contiguity across the v16–v18 gap. Pre-existing; the execution substrate's.
11. **The toolbelt `_MATRIX` drift** — `launch_arv2_account_research`,
    `read_arv2_account_research_run` and `design_set_web_noindex` are registered but unmatrixed.
12. **The live O6 exit gate is owed** (founder-triggered): a new project on Insight Health walking
    interview → ICP pick → product set → ICP confirmation → launch, with the old lane off.

## Where things are

- Plan: `docs/superpowers/plans/2026-09-09-arv2-onboarding-o6-head-of-abm.md`.
- Spec addendum: `docs/specs/ARV2-ONBOARDING-PLAN.md` §8 "Addendum 2026-09-09 — O6 as built"; the §9
  O6 row records "built 2026-09-09 … live exit gate owed".
- Lane module map: `platform/api/clue_api/arv2/README.md` §"O6 — the Head-of-ABM integration".
- SDD ledger (git-ignored): `.superpowers/sdd/2026-09-09-arv2-onboarding-o6-head-of-abm/progress.md`.

## Task 9b — the durable project ICP pin (founder rulings 2026-09-10)

Migration `71e80c777cf6` adds `project_icp_pin` (append-only, PK `(project_id, pin_seq)`; the
current pin is the greatest `pin_seq`; composite FKs to `project` and `brand`, FK to
`brand_knowledge_document`; bare-64-hex digest CHECK; `product_selection_version` nullable for the
ICP-first order). Single alembic head after it: `71e80c777cf6`.

- **Writer/reader live in `arv2/icp_confirmation.py`** (`pin_project_icp`, `current_project_icp_pin`,
  `ProjectIcpPin`). Forced by the import guard: the launches are inside `clue_api.arv2` and may not
  import `clue_api.brand_knowledge_context`, while `brand_knowledge_context` may import the lane.
  `version`/`path` are joined off the document row rather than copied into the pin.
- **Written in the gate-approval transaction** (`chat/router.py`), immediately after
  `confirm_icp_document`; a replay/double-approve finds its document already pinned and writes
  nothing, so the receipt stays the first approval's.
- **`load_or_create_knowledge_pin` now takes `project_id`** and unions the project's pinned
  document into the turn's set (dedupe by document id). `confirmed_icp_for_project` is pin-driven
  (`pinned_document_id=`), not a `confirmed_for_project_id` front-matter scan.
- **New `workspace_paths()` helper (decision the brief did not settle).** Two versions of one path
  can now ride one turn (the pin plus a newer proposal), and
  `AgentResourceMaterializer` hard-refuses duplicate seed paths. Rule adopted: the *pinned* version
  keeps the natural name (`audience/icp-gi.md`); any other version on that path materializes beside
  it as `audience/icp-gi.v<N>.md`, and the index card's `workspace_path` uses the same map, so every
  card line names a file that really exists. Worth a founder confirmation.
- **Both launches resolve from the pin.** Account launch refuses `project_icp_not_pinned` /
  `icp_artifact_not_project_pin`; person launch refuses `project_icp_not_pinned` and the
  `_CONFIRMED_ICP_FOR_BRAND` (brand-newest) query is deleted. `_ICP_ROW` (by artifact key) is
  replaced by `_PINNED_ICP_ROW` (by document id). Side effect worth knowing: a launch naming a
  non-existent project now refuses `project_icp_not_pinned` before `project_not_found`.
- **Re-synthesis retires only `ready`/`proposed`** (`onboarding_synthesis_wiring.RETIRABLE_STATUSES`);
  `SERVABLE_STATUSES` still governs reads.

Verification: `tests/db/test_arv2_project_icp_pin_migration.py` (4), `tests/api/test_project_icp_pin_db.py`
(6), and the touched suites — brand-knowledge context, ICP artifact gate, O6 chat gate answers, O6
conversation composition, production-context S3, onboarding synthesis wiring, ARV2 launch — 66 passed
together. `tests/arv2` 886 passed / 4 skipped. Full `uv run mypy`: the only 4 errors are pre-existing
in files this task never touched. `tests/db/test_db_migrations.py` passes on a fresh throwaway DB; on
the shared `clue_o6_head` it fails the downgrade-to-base trio because accumulated `run_event` rows
trip the deliberate "decide their fate explicitly" guard — a DB-state artifact, not the migration.

## 2026-09-10 — founder rulings applied before the merge (Tasks 9b–9e)

Rulings (all founder, 2026-09-10): (1) `CLUE_ENTITY_RESEARCH_RUNTIME_ENABLED` is off everywhere; the old research lane is legacy. (2) v44 drops the five old-lane launch/read tools and `account-deep-steering@v8`; a steering skill on the ARV2 tools is a follow-up before O7. (3) `launch_arv2_person_research@1` is granted to the Head of ABM: people named on the current turn as contact refs. (4) No mechanical eval gates or lint anywhere; the prompt and skills carry the behaviour. (5) The exit-gate walk runs with committee cap 5, one account, four worker processes at three slots each. (6) Target accounts are seeded by domain before the walk (the workspace held only the seller). (7) A project pins ONE confirmed ICP version by document id and nothing moves it on its own; a brand-level re-synthesis or another project's confirmation never repoints an existing project. Project-local ICP variants (full documents with `derived_from`), the ICP authoring tool, the personas-only onboarding mode, and per-role persona overrides are the next slice, as are `abm-craft`, `copy-voice` and `campaign-ideation` from `head-of-abm-agent-refinements/` (which v21 had never drawn on — corrected in 9e).

Landed on the lane (all reviewed first-hand): rebase onto the R3 head with alembic join `fcb4a7b0b465`; `CLUE_FLEET_WORKER_CONCURRENCY` (N drain slots per process, `drive_run` serialised, lease fence unreachable across slots while `fleet_task_stale_after_s` > `fleet_lease_ttl_s`); `project_icp_pin` (migration `71e80c777cf6`, written in the ICP-gate approval transaction, read by the index card, the knowledge pin and both launches; re-synthesis retires only `ready`/`proposed`; a pinned version keeps the plain file name, a newer sibling materialises as `<stem>.v<N>.md`); v44 = prompt v8 + stage0-interview v21 + 14 tools; skill v21 rewritten: read silently, open from first principles (outcome, last three closed-won, list math, channels tried, follow-up ownership, day-90 failure; the qualification floor stated once), the ICP as the agent's view first, gates, recording, account launch, named-people launch. Whole-lane offline gate 1389/1403 with the four pre-existing reds only.
