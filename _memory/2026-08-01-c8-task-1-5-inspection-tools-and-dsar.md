# 2026-08-01 — PC-C8 task 1.5: bounded inspection tools + card DSAR reverse bindings & erasure

Branch `platform/c8-task-1-5`, base `7d0397e` (`platform/c8-context-card`), implemented in an
isolated worktree. Spec `docs/specs/PC-C8-stage0-context-card.md` v2.2 §7 + §9, §11 task 1.5,
§12 ACs 3 and 11.

## What landed

**`platform/api/clue_api/stage0_inspection_tools.py`** (new) — the two §7 contracts:

- `inspect_statement_history@1` — `(project_id, statement_id | route_key, cursor?)`. Every route
  kind, superseded rows included, newest-first. `statement_id` returns that statement's whole
  correction lineage (walked both directions over `correction_of_id`, cycle-guarded); supplying
  both selectors is `statement_selector_ambiguous`. Quotes resolve through the SHARED reader
  (`StatementEvidenceReader` port → `ArtifactStatementEvidenceReader` →
  `resolve_statement_quotes`); an unreadable quote comes back as a row with `quoted_text: null` +
  `quote_excluded_reason: "artifact_missing"`, never fabricated and never dropped.
- `inspect_readiness_history@1` — `(project_id, gate?, cursor?)`. Ledger newest-first, override
  annotated via the SHARED `readiness_override_refs` / `effective_readiness_verdict`.

Both: `effect_class=READ`, `ReplayPolicy.EFFECT_FREE`, recipe-safe typed outputs
(`StatementHistoryOutput` / `ReadinessHistoryOutput` in `tool_outputs.py`); page hard-bounded at
`MAX_INSPECTION_PAGE = 20` (**not** an input); cursors are card cursors
(`encode_card_cursor`/`decode_card_cursor`); workspace/project scoping is fail-closed via
`get_project` + a `ctx.workspace_id` check → `stage0_project_not_found`, WARNING-logged
(`stage0_inspection.project_scope_refused`), identical for a foreign and an absent project.

**`platform/api/clue_api/stage0_card_dsar.py`** (new) — the §9 surface:
`stage0_card_subject_bindings(card=…, base=…)` (per-statement `derived` bindings appended to the
existing client-level `context` binding), `card_artifacts_quoting_statement(...)` (the reverse
query, served by the existing `agent_artifact_subject_lookup` index), and
`Stage0StatementEraser.erase_statement(...)` + `Stage0StatementNotFound`.

**`agent_turn_wiring.py`** — extracted `AgentPrivacyService.erase_artifacts(...)` from
`erase_subject`, which now resolves keys from the subject bindings and delegates. The affected-turn
query moved from a subject-join to `r.artifact_key = ANY(:keys)` (identical set for
`erase_subject`; correct for a caller-supplied closure). No new erasure semantics.

**`clue_projections/stage0.py`** — `_bounded_gate_evidence` → public `bounded_gate_evidence` (with
a `STAGE0_CARD_POLICY_V1` default) + `__all__`, so the ledger tool bounds a paged row exactly the
way the card bounds a gate row. One caller updated; behaviour unchanged.

**`stage0_trial.py`** — one call touched (`_project_card_ref`'s `persist_body`) plus one import.

**`toolbelt_wiring.py`** — registers the pair; builds `ArtifactStatementEvidenceReader` over
`DurableAgentArtifactStore(storage=…)` when a storage backend is wired, else passes `None` (the
statement tool then refuses `statement_evidence_not_configured` rather than serving quote-less
rows — "no reader" must not look like "the words were erased").

## GRANT DEFERRAL — read this before merging

**Both tools are granted on NO profile.** `C6_AGENT_TOOL_AUTHORITY` maps
`inspect_statement_history` and `inspect_readiness_history` to `()`; they are registered,
addressable, and structurally absent from every model surface. Task 1.4 is re-versioning
`head-of-abm` in parallel and a grant must ride that one coordinated catalog/profile bump — so the
grants land in a **post-merge commit** against the bumped profile version, never by editing an
already-reviewed profile in place. Recorded in three places:

1. the NOTE comment at the registration site, `toolbelt_wiring.py` (`build_toolbelt`, just above
   the `build_stage0_inspection_tools` loop);
2. the NOTE comment at the authority entries, `agent_registry_wiring.py`;
3. `tests/api/test_c8_inspection_tools.py::test_the_inspection_tools_are_registered_but_granted_to_no_role`
   — it fails the day a grant lands, which is the intended way to notice.

## How the erasure composes with the existing purge (file:line)

`Stage0StatementEraser.erase_statement` (`stage0_card_dsar.py:152`) resolves *which* keys an
erasure reaches and delegates the act:

1. `_evidence_key` — the statement's captured `onboarding_input.artifact_key`, workspace-scoped;
   absent or foreign → `Stage0StatementNotFound` (no existence leak).
2. `_statements_citing` — every statement whose words live in the **same captured body**. The
   captured artifact is the whole client turn, so erasing the bytes erases the siblings' words
   too; erasing less would leave a card quoting an erased turn.
3. `card_artifacts_quoting_statement` per sibling — the reverse-binding query.
4. `AgentPrivacyService.erase_artifacts` (`agent_turn_wiring.py:1511`) with
   `(evidence_key, *card_keys)` — the unchanged B2 path: `agent_artifact_tombstone` insert →
   `mark_erased` (`agent_turn_wiring.py:1590`) → `agent_privacy_event` → per-turn
   `PRIVACY_TOMBSTONED` event → `purge_erased_artifacts` in a **fresh** transaction
   (`agent_turn_wiring.py:1621`) → `workspaces.erase_for_privacy`.

Downstream, unchanged and relied on: the artifact ROW survives as audit; `DurableAgentArtifactStore
.read` raises `ArtifactNotFound` on an erased/purged/tombstoned row (`agent_turn_wiring.py:322`);
`DbAgentReplayReader.inspect` yields `blocker_codes=("artifact_erased:project_card",)` and
`replayable is False` (`agent_turn_wiring.py:1305`) — the B2 dangling-ref soft failure, not a new
mechanism; `persist_body` refuses a content-addressed re-persist of tombstoned bytes
(`agent_turn_wiring.py:222`).

## The binding shape recorded

`agent_artifact_subject(workspace_id, artifact_key, subject_entity_id, binding_kind)` — one row per
statement the card body quotes, `binding_kind='derived'` (one of the six the table CHECK admits;
`conversation` and `context` already mean other things), `subject_entity_id = statement_id`. The
column has no FK, so a statement id is a legal subject. The pre-existing client-level
`(client_entity_id, 'context')` binding is kept, so a client-wide DSAR still reaches the card.
Only `interview.current_effective_statements` are bound: only their words are in the bytes, and
binding a shed statement would claim a dependency that does not exist.

## AC-DSAR

`tests/api/test_c8_card_dsar.py::test_erasing_a_statement_purges_the_cards_that_quoted_it_and_nothing_recovers_it`
— **PASSED**. Asserts, in order: card quotes X + turn journaled → erasure reaches the card via the
binding query (not via the test) → old body `ArtifactNotFound` while the row is `erased`+`purged`
→ recompile omits X, names it nowhere in the new bytes, and surfaces
`excluded_statement_evidence_missing=1` → cold replay `artifact_erased:project_card`, not
replayable → re-persisting the identical bytes raises "cannot be resurrected".

## Tests

- `tests/api/test_c8_card_dsar.py` (4): reverse bindings (incl. the client binding surviving and a
  non-quoting id resolving empty), a no-DB binding-builder shape check, AC-DSAR, and fail-closed
  cross-workspace erasure refusal.
- `tests/api/test_c8_inspection_tools.py` (11): page bound + a cursor walk asserted to be an exact
  *partition* of the durable ledger; empty page; cursor past the end; stale cursor (resumes past
  the end, never restarts at page one); card-omission cursor resumes exactly at the card's
  boundary in the tool's own order; quote-exclusion honesty + the excluded-evidence view;
  correction lineage from both ends + `statement_selector_ambiguous`; ledger paging + gate filter +
  override annotation; fail-closed foreign/absent project (identical reason codes) and sibling-
  project isolation; cross-tool and malformed cursor refusals; no-evidence-reader refusal;
  writes-nothing (row counts before/after + descriptor claims); the grant-deferral guard; a no-DB
  composition check.
- Updated inventory counts: `test_toolbelt_wiring.py` (35→37 / 36→38 + two matrix rows),
  `test_tool_authority_audit.py` (35→37), `test_agent_registry_wiring.py` (36→38 + both tools
  asserted `ROLE_UNAVAILABLE`).

## Deviations surfaced

1. **`bounded_gate_evidence` was made public** (a task-1.1 file). The alternative was a second
   notion of "a bounded readiness row" in the tool; that is exactly how the card and the tool would
   start disagreeing about what was truncated.
2. **`erase_subject` was refactored, not just called.** Extracting `erase_artifacts` was needed
   because a statement's closure (evidence + dependent cards across siblings) is not expressible as
   one subject's bindings. The turn-detection query changed shape (subject-join → key-`ANY`);
   equivalent for `erase_subject`, correct for the new caller.
3. **The statement tool queries all six `StatementRoute` kinds** (six `read_statements` calls
   rather than one new SQL). History has to include `unmapped` and `claim` rows — a `statement_id`
   selector that could not find an unmapped statement would be a hole — and copying the
   supersession SQL would have forked the rule.
4. **Two cursor *views* on the statement tool**, `statements` and `excluded_statement_evidence`,
   because the card emits both kinds. The exclusion view scans in page-sized chunks with a
   `MAX_EXCLUSION_SCAN = 200` budget per call, so both the response and the evidence reads stay
   bounded when matches are sparse.
5. **`bind`/erase blast radius is per captured turn, not per statement** (deviation #2's cause) —
   documented at the module docstring and in the eraser.

## Fixture gotchas (cost real time)

- Inside one rolled-back transaction every row shares `now()`, so `(created_at, id)` order is **not**
  insertion order (the 1.1 note warns about this; it bit the cursor test). Any assertion about
  "which rows a page contains" must read the durable order first and speak in it.
- `_seed_material_turns` reuses the same quote span for every turn, so the card *de-duplicates*
  `(route_key, quote)` — a card row count is not `statements - 1` after one erasure, and a "the
  words are absent from the recompiled bytes" assertion is meaningless. Assert on statement ids.

## Verification

`tests/api tests/agents tests/stage0 tests/clue_trial tests/projections` — one failure, the
documented pre-existing `test_agent_runtime_wiring_db.py::test_delegation_is_durable_before_fresh_
child_wake_and_rolls_up_reference_result` (`AgentCatalogError: tool 'evaluate_stage0_readiness@1'
schema digest changed`; recorded as pre-existing in the 1.1 and 1.3 notes). Structural guards
(`test_{package_layout,structure_guards,dependency_contracts,seams,beat0_contracts,
project_rename_guard}`) green. `uv run mypy` clean (458 source files). `lint-imports` 24/24.
`ruff check`/`format` clean on every touched file (the repo-wide `ruff format --check` drift on
~18 untouched files is pre-existing and deliberately not fixed). `tests/db/test_db_migrations.py`
and the live trial deliberately not run. No migration was needed — the binding rides the existing
`agent_artifact_subject` table.

## Handoff

- **The grants.** Post-merge, against task 1.4's bumped `head-of-abm` profile: add both tools to
  the profile's pinned tool list and flip their `C6_AGENT_TOOL_AUTHORITY` entries to
  `(AgentRole.HEAD_OF_ABM,)`. `test_the_inspection_tools_are_registered_but_granted_to_no_role` and
  the `ROLE_UNAVAILABLE` assertions in `test_agent_registry_wiring.py` flip in the same commit.
- **AC-7's negative half** ("a profile advertising an omission-resolving tool it doesn't install is
  a failing contract test") is 1.4/1.6's, and becomes checkable once the grants exist.
- **Erasure has no HTTP/CLI entry point yet.** `Stage0StatementEraser` is composable and tested but
  nothing calls it in production; wiring it to a DSAR surface is out of 1.5's scope.
