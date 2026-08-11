# Stage-0 and project-chat hardening

Date: 2026-08-11
Branch: `platform/stage0-project-hardening`
Base: Singapore head `8949058f46ddfbcefede85abacfc503fb60dc61c`

## Scope and evidence

- The current worktree was already clean, on the requested branch, and at the
  exact current Singapore head. Singapore's unrelated `.env.example` edit was
  left untouched.
- Primary defect evidence: `.context/defect-log.md` and
  `_memory/2026-08-11-lane-f-browser-e2e.md`.
- Fixture procedure: the supplied attachment describing the replay-safe
  Insight Health/Aura AI fixture from commit `227d1fa3`.
- The browser probe reached real Stage-0 interview writes but found no
  `icp_spec`, no durable `agent_gate`, model-supplied zero readiness metrics,
  and a focused Slate editor that retained submitted text.

## Ratified implementation boundary

1. Governed synthesis persists draft, versioned `icp_spec` records and returns
   their durable refs.
2. ICP confirmation is a durable gate over an exact stored spec snapshot. The
   gate stores its permitted decisions and human addressee.
3. Structured gate answers verify the expected digest and decision before the
   immutable receipt is written; approval activates only that draft version.
4. Readiness is compiled from product-scoped Client-KB claims and labels its
   revision as a readiness-policy version.
5. Only supported, fetched durable gates render controls. Thin/model-only refs
   are notices.
6. The frontend also clears focused Slate state, repairs workspace sizing and
   overflow, collapses empty Gallery with a reopen affordance, displays the
   workspace name, and uses a durable derived/explicit project name.

## Verification plan

- Focused domain/tool/gate/auth/chat tests and migration up/down/up.
- Frontend model/repository/component regressions, design-system build, lint,
  tests, and webpack production build.
- Replay the supplied Insight Health fixture in a fresh paired DB/filesystem,
  then verify browser -> API -> Postgres for synthesis, gate answer, ICP status,
  readiness metrics, project title, and composer behavior.

## Open state

- The founder approved Slice 0 only. The contract amendment is ratified; Slices
  1-6 remain pending and must not be implemented without the next instruction.

## Slice 0 closeout — contract and test foundation

- Added unregistered strict contracts in
  `platform/api/clue_api/stage0_project_contracts.py` for
  `evaluate_stage0_readiness@2`, `synthesize_icps@2`, durable draft ICP refs,
  exact ICP-confirmation gates, and structured digest-bound answers. Historical
  `@1` contracts remain unchanged for replay.
- Added schema fingerprints and forbidden-old-shape tests. Model-authored
  readiness metrics/scope, transient synthesis outputs, `human_only` subjects,
  stale digests, and incomplete permitted decisions are rejected.
- Updated the active-skill materialization test to read the resolved Stage-0
  skill bundle's `materialized_path`; it no longer hard-codes v9 or v10.
- Repaired the durable-turn acceptance fixture by using the production
  `TurnLayerSource` for L7. L6 remains append-only conversation; the exact
  current user-message artifact is the sole required L7 instruction.
- Ratified and expanded the source-of-truth frontend project contract. No tool
  registration, migration, runtime behavior, or frontend control changed.

Verification on a dedicated migrated database
`copenhagen_stage0_slice0_20260811`:

- owning contract/registry/context/durable-turn suites: 49 passed;
- Ruff format/lint on changed Python: green;
- mypy on the new contract module: green;
- import-linter: 25 kept, 0 broken;
- `git diff --check`: green.

The first `make contracts` attempt was blocked by sandbox access to the existing
uv cache; the same command was rerun with approved access and passed.

The repository-wide `make check` completed Ruff, mypy (632 files), and all 25
import contracts, then was stopped after the pytest phase crossed known
out-of-scope red boundaries: 4 failed, 1,306 passed, and 1,081 skipped at the
stop point. Three pilot-budget tests hit the existing shared-database lifecycle
problem after `field_definition.research_scope` disappeared (LF-TEST-001), and
the root logging test crossed the excluded design subtree (LF-TEST-003). These
were already recorded in `.context/defect-log.md`; Slice 0 does not weaken or
repair those separate tests.

## Slice 1 closeout — trusted readiness and durable ICP synthesis

Implemented LF-STAGE0-004, LF-STAGE0-007, and LF-STAGE0-008:

- Registered `evaluate_stage0_readiness@2` and `synthesize_icps@2` while keeping
  `@1` historical. Active Recipe 0 is immutable v7; the project-conversation
  profile is `head-of-abm@v24` with `stage0-interview@v11`.
- Both v2 tools derive workspace/project/product/client/Client-KB scope from
  the governed execution. The model chooses only the readiness gate and cannot
  submit identity, metrics, policy, claims, or a verdict.
- Readiness reads the pinned product-scoped Client-KB claims and compiles
  available fields, verified claims, coverage, and required-field blocks over
  the substantive baseline plus tenant-required extensions. Empty extensions
  cannot erase the baseline; an empty effective field set fails explicitly.
- Synthesis revalidates a current backend-authored ready decision, uses the
  existing governed synthesis/compiler path, persists immutable draft
  `icp_spec` versions, and returns only durable composite references. The new
  append-only `stage0_icp_synthesis` ledger binds the operation to exact
  readiness/client/KB/product/project lineage and rejects update and delete.
- Assistant guidance and response regression coverage distinguish a
  readiness-policy version from an ICP version and say that no ICP exists until
  a durable `icp_spec` was written.

The authenticated Browser journey exposed a cross-platform defect not visible
in focused tests: strict tuple-valued tool outputs validated in Python, were
serialized as JSON arrays in the durable journal, and then failed strict
`model_validate` when the agent consumed the replayed document. The final fix
is systemic rather than Stage-0-specific: the toolbelt now owns one JSON-mode
output validator, used both by the inner runner and the agent result consumer.
Domain contracts retain precise tuple types; durable references are canonical
JSON. A generic first-execution plus idempotent-replay regression covers this
boundary for every future tool.

Browser/API/Postgres evidence on the isolated Insight Health runtime:

- project `prj_cae36664dfbf5ce086331eaeb56261f9`, thread
  `thr_4cf4367f423c5a58a58481cb116f90d9`, successful turn
  `14af4cc4-90c0-55b4-ab75-7c46fdacb05f`;
- journal receipts completed exact addresses
  `evaluate_stage0_readiness@2` and `synthesize_icps@2`;
- readiness decision `65e58a56-1c6b-5ff9-8170-f2c7c6771684` is ready under
  readiness-policy version 1 with backend authority, coverage `7/9`, zero
  verified official-site claims, and seven available field keys;
- durable draft `icp_spec` reference
  `ws_fixture_insight_health_browser / independent_neurosurgery_spine_practices / 1`
  carries exact product, client-entity, and Client-KB-v1 lineage;
- zero `project_run`, `discovery_plan`, and `entity_research_run` rows were
  created. The UI explicitly said the spec remained draft and no discovery or
  research started.

Verification:

- final expanded backend matrix: 125 tests passed on fresh migrated database
  `copenhagen_stage0_slice1_tests_20260812a`;
- frontend tests: 143 passed; ESLint and design-system token build passed;
- Ruff: 1,337 files formatted and clean; mypy: 634 files clean; import-linter:
  25 contracts kept;
- Alembic: exactly one head `2fb8e2479183`; downgrade to `5d7ab295742b` and
  re-upgrade passed;
- authenticated Browser UI, durable agent journal, and Postgres lineage were
  correlated end to end.

Browser observation retained for later slices: the focused Slate composer still
shows the submitted prompt after the turn. This is LF-COMPOSER-001 and was not
changed in Slice 1.

## Slice 2 closeout — durable ICP gate and immutable answer lifecycle

Implemented LF-STAGE0-005 and the backend portion of LF-STAGE0-006:

- Migration `70e67fc26a3f` adds `icp_confirmation` as a real `agent_gate` kind,
  persists a non-empty permitted-decision vocabulary, supports non-spend gates,
  and records the client-echoed digest plus typed decision payload on the
  immutable `agent_gate_answer` receipt. A conditional unique index permits
  only one gate over one exact project/draft/digest.
- The database answer trigger now enforces the stored decision vocabulary,
  exact digest, exact addressee, revision-payload shape, and the relationship
  between the answering submission and the gate's project/thread/addressee.
  Application checks are not the only authority boundary.
- `open_icp_confirmation_gate@1` resolves scope from the execution, binds the
  exact project synthesis ledger entry, canonicalizes the complete persisted
  draft `icp_spec`, calculates its SHA-256, derives one stable gate id, and
  derives the human addressee from the presenting turn. The model supplies only
  the durable ICP key/version.
- Structured Approve/Reject/Revise answers recheck tenant, project, thread,
  addressee, gate state, decision, revision, snapshot and digest before any
  write. Approve activates exactly the reviewed draft in the same transaction
  as the receipt. Reject leaves it draft. Revise stores one non-blank change
  request and leaves the snapshot immutable for a later synthesis version.
- The active project-conversation resources are Recipe 0 v8,
  `head-of-abm@v25`, and `stage0-interview@v12`. Historical recipes/profiles/
  skills remain replayable.
- The durable gate read and stream projection now carry stored decisions,
  nullable spend, subject identity and answer receipt. The frontend parses that
  authority but intentionally renders the ICP gate as a non-interactive
  `Human action required` notice until Slice 3 supplies the typed Revise form;
  Slice 2 does not merely enable incomplete buttons.

The authenticated browser journey caught two live composition defects that
focused tool tests missed:

1. the conversation worker still requested Recipe 0 v7 after v8 was seeded and
   promoted; `CONVERSATION_RECIPE_VERSION` now points at v8 and has a regression
   assertion;
2. the central Stage-0 pin provider derived trusted project scope for two
   hard-coded tool names, so the new gate reached plan review with only its ICP
   pin. Project-scoped input contracts now declare one reusable marker, and the
   provider derives the exact brand/project/product/Client-KB pins from the live
   descriptor. Future project-scoped Stage-0 tools inherit the boundary without
   another name-based exception.

Browser/API/Postgres evidence on the isolated Insight Health runtime:

- project `prj_cae36664dfbf5ce086331eaeb56261f9`, thread
  `thr_4cf4367f423c5a58a58481cb116f90d9`;
- `open_icp_confirmation_gate@1` completed through the real fleet worker and
  produced gate `6fae9039-bbaf-50ff-81bc-b0ba66155f6c`;
- the persisted subject is
  `icp-spec:ws_fixture_insight_health_browser:independent_neurosurgery_spine_practices:v1`,
  revision 1, digest
  `90f10d1e7105b20e53fabc4278dc2c10d70cf1588b791f00f8ca6ed44b7055b5`,
  decisions `approved,rejected,revised`, exact user addressee, no spend, zero
  answers and a still-draft ICP;
- the execution froze `brand`, `project`, `product`, `client_kb` and `icp` pins;
  the gate and explicit recovery notice survived a full browser reload, and
  Approve/Reject/Revise were all disabled as intended for the Slice-2 client.

Final verification:

- broad backend matrix: 154 passed on isolated migrated database
  `copenhagen_stage0_slice2_20260812a`;
- dedicated lifecycle acceptance: 10 passed, covering all three decisions,
  replay, exact activation, immutable receipts, stale/tampered/foreign answers,
  project synthesis binding and direct database bypass attempts;
- migration downgrade `70e67fc26a3f -> 2fb8e2479183` and re-upgrade passed;
- frontend: 144 passed; ESLint and design-system token build passed; the webpack
  production build had already passed after the Slice-2 frontend contract
  changes;
- Ruff/format: 33 changed Python files clean; mypy strict: 18 source files
  clean; import-linter: 25 kept, 0 broken; `git diff --check`: green.

The browser again reproduced LF-COMPOSER-001: Slate retained the prior submitted
text and concatenated the first retry. That remains intentionally deferred to
its composer slice; the final gate retry used select-all/replace solely as a
test workaround.
