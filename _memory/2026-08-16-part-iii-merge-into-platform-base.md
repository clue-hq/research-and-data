# 2026-08-16 — merge `integration/frontend-design-part-iii` → `integration/august-platform-base`

One merge commit brings the design Part-II/Part-III lineage (design substrate, the design
deepagent's leg lifecycle, the D8 run-event outbox consolidation) onto the platform base so
Part-IV editor-mounting work can proceed here while account/contact research work continues on a
parallel branch. 34 conflicted files; every resolution below is deliberate.

## Version-number collisions (same disease as the old Alembic 0005–0007 collision)
- **`head-of-abm` profile:** both branches minted a `v24`. Ours (base chain → v35) kept; theirs'
  v24 (= v23 + `open_design_leg@1`) re-versioned as **v36 = our v35 + the open_design_leg tool
  block** (digests carried verbatim from theirs — P3.5's revised schema). Active version pins
  (`C6_ACTIVE_PROFILE_VERSIONS`, `PROJECT_CONVERSATION_AGENT_PROFILE_ID`) → `v36`. New aggregate
  manifest digest pinned in `tests/api/test_agent_registry_wiring.py`:
  `a2a1a950ce87…3986ef`.
- **Recipe #0:** both minted a `v7`. Ours (→ v15) kept; theirs' v7 (= v6 + `open_design_leg@1`
  in the interaction slot) re-versioned as **v16 = our v15 + open_design_leg@1** (4 insertion
  sites). `CONVERSATION_RECIPE_VERSION = 16`; registered in `recipe_wiring.py`.

## run_events move (theirs' D8) × our recon constants
Theirs deleted `clue_research.durable.run_events` (DAL → `clue_execution.run_events`, shapes →
`clue_core.run_event`). Our branch had added `RECON_TRANSITION_KIND` / `RECON_FIELD_PROGRESS_KIND`
there. Ported both constants to `clue_core/run_event.py` (+ `clue_core` exports) and repointed all
our importers: `stage0_tools`, `stage0_setup`, `stage0_field_events`, `official_site_progress`,
`tests/stage0/test_stage0_static.py`, `tests/api/test_stage0_field_events_db.py`,
`stage0/types.py` docstring.

## Other notable resolutions
- `agent_turn_fleet_wiring.py`: kept both the S3.1 `scope_pin` read and theirs' design-leg routing
  reads (open-leg → gate-answer override → closed-by-turn re-entry). The design-leg branch now
  pins/loads the same S3.1 scope receipt (`load_or_create_agent_turn_scope_pin`) and builds its
  card via ours' **v2 envelope** signature (availability flags default False — the leg composes no
  Client-KB artifacts) instead of theirs' retired v1 card shape with client_kb fields.
- `toolbelt_wiring.py`: kept both tool registrations (prose/value-narrative + design/design-leg).
  Dropped theirs' now-dead `build_high_tier_resolver` import (Lane F had replaced that consumer
  with `build_entity_research_account_resolver`; ours' removal won the auto-merge).
- `chat/schemas.py`: both branches renamed the same status alias differently — kept ours
  (`ConversationStatus`, matches the frontend vocabulary); theirs' `ThreadStatusValue` dropped.
- Keep-both everywhere both sides appended: fleet enums (`DESIGN_JOB` beside `STAGE0_RECON` /
  `OFFICIAL_SITE_CRAWL`), `fleet_wiring` optional handlers, settings blocks (stage0 crawl/budget +
  design retention sweeps), `recipe_contracts` certified list, `stage0_recipe` pin resolution,
  `_memory/README.md` index.
- `uv.lock`: took ours then regenerated with `uv lock` off the auto-merged pyproject.
- **Alembic:** two heads (`44dc4ba7ca63` ours × `36936027bc96` theirs) joined per convention with
  merge revision **`a1c5b9842f0e`** — single head confirmed.

## Merged-count arithmetic (test pins refreshed in-commit, the sanctioned ritual)
- `C6_AGENT_TOOL_AUTHORITY`: ours 63 + 49 design grants + open/finish_design_leg = **114**.
- Registry names 114; address inventory **129**; head capability disclosures **129**.
- Frozen contract digests (`tests/agents/test_contracts.py`): AgentConstitution/AgentTurnRequest/
  AgentPlan re-pinned to the merged union (S3 shape × P3.1 'design' role); AgentPlan's merged
  digest exactly equals theirs' pin (sanity cross-check).

## Pre-existing reds (NOT merge-introduced; each verified failing on pre-merge HEAD via worktree)
- `tests/agents/test_o3_account_deep_behavior.py::test_scripted_o3_conversations_cover_the_non_linear_gate`
  — opens `skill:account-deep-steering@v4` but the active profile pins v6. Left failing.
- `tests/api/test_pilot_budget_controls.py` — 3 failures (gate-row amount / stale-digest /
  stale-amount), DB-gated, red on HEAD too. Left failing.
- `tests/db/test_unified_agent_gate_migration.py::test_discovery_configuration_is_the_only_head_after_the_explicit_gate_merge`
  — head-pin test already stale on HEAD (and the merge legitimately added head `a1c5b9842f0e`).
  Left failing; whoever owns the gate-migration test should re-pin.
- `tests/api/test_toolbelt_wiring.py::test_build_toolbelt_registers_the_full_set` was already red
  on HEAD (stale counts/directive-version pins from our own @3 promotion); the merge fixed its
  stale pins to the merged reality, so it is now green (greener than HEAD).

## Verification
`make lint` ✓ (after `make format` on merge-touched files), `make typecheck` ✓ (mypy 725 files),
`make contracts` ✓ (26/26), `alembic heads` single ✓. Full `uv run pytest`: 2815+ passed /
2380 skipped (DB-gated suites without a local DB) / **5 failed — all five in the pre-existing
list above**; zero merge-introduced failures remain.

## Incident, for honesty
Mid-verification an accidental `git stash` (in a diagnostic command) swept the fully-resolved
index+worktree and aborted the merge state. Recovered losslessly: re-ran
`git merge --no-commit`, restored the byte-identical tree with `git checkout stash@{0} -- .`,
re-applied the 15 deletions, verified `git diff stash@{0}` empty. Lesson: never run `git stash`
while a merge is in progress.
