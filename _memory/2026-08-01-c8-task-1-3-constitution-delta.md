# 2026-08-01 — PC-C8 task 1.3: `AgentConstitution` delta + `ProjectLayerSource` rewrite

Branch `platform/c8-context-card`, base `4c5d918`. Implements spec §10 (the frozen-contract delta
and every touch point), plus the 1.2-review follow-up that `brand_id`/`client_entity_id` are
project authority, not model input. ACs 5, 8, 9 covered; AC-1's ceiling re-asserted end to end.

## The contract delta

`AgentConstitution` (`platform/agents/clue_agents/contracts.py`):
`stage_snapshot_ref` + `readiness_snapshot_ref` → **`project_card_ref: ArtifactRef`** (required);
`budget_envelope_ref` untouched (spend authority, §2.1); new optional
**`client_entity_id: StableId | None`**; validator now checks card/budget/manifest.
New schema digests pinned in `tests/agents/test_contracts.py`:
`AgentConstitution c7efb228…`, `AgentTurnRequest d3dde9c4…`.

`ProjectLayerSource` (`context.py`) is exactly two required L3 candidates — card + budget — and
**dropped its `cards.read("project")` call** (the card subsumes the compiled project row) along
with its now-unused `cards` constructor argument.

## The A-decision: `brand_id`/`client_entity_id` are constitution authority (global, name-keyed)

Investigated first: `product_id` is **not** in `MODEL_FORBIDDEN_AUTHORITY_KEYS` and never was —
only `project_id` (of the Stage-0 scope ids) is engine-served. `_trusted_authority` maps a
forbidden *name* to a constitution value for every tool that declares it; 1.2's `TRUSTED_TURN_FIELD`
is the per-model variant for authority that is not stable for an execution.

Both new keys went into the **global** set, not a per-model marker, because every tool in the
toolbelt that declares them means the same thing: this execution's brand / this execution's client
account (`brand_id` on 4 tools, `client_entity_id` on 7). Narrowing to `record_interview_answer`
would have left `start_recon`/`submit_onboarding_input`/`evaluate_stage0_readiness`/`synthesize_icps`
letting the model author the same authority — the same defect, one tool over. `client_entity_id`
had no trusted home, so it became a constitution field (optional: only Stage-0-shaped surfaces
have one; the account-research and specialist roots pass `None`/inherit). A required tool field
with no constitution value fails its own validator — fail-closed, same rule as `operation_id`.

**No catalog bump was forced, and none was taken.** `_schema_sha256` hashes the *full* input model;
`MODEL_FORBIDDEN_AUTHORITY_KEYS` is applied at runtime by `_with_trusted_runtime`, so stripping a
field does not move `input_schema_sha256`. Verified: all six Stage-0 tool digests are byte-identical
to the ones profile `head-of-abm@v8` / skill `stage0-interview@v6` pin. Field `description` text was
therefore left alone (it *is* in the schema hash, and the model never sees a stripped field), with
an explicit source comment at `stage0_tools.py` handing the rewording to **task 1.4's** one
coordinated bump. **1.4's reword list, enumerated (an earlier draft of this note said "all
four/seven inputs" — three of them have no description at all):** `brand_id` on
`submit_onboarding_input`, `start_recon`, `record_interview_answer`, `evaluate_stage0_readiness`
(4/4 carry descriptions); `client_entity_id` on `submit_onboarding_input`,
`record_interview_answer`, `evaluate_stage0_readiness`, `start_confirmed_project_run` (4 of the 7
declaring tools). `confirm_icp`, `import_accounts` and `synthesize_icps` declare `client_entity_id`
with **no** description — nothing to reword there, and adding one now would move their pinned
digests for no model-visible gain.

## The F-finding: journal role labels

`agent_artifact_ref.ref_role` is a **table CHECK** (`agent_artifact_ref_role`, migration
`7e9269ed8a81`), *not* a Postgres enum. No reader matches on the strings: `DbAgentReplayReader`
and `clue_projections.agents` both select every role and only `ORDER BY` it. So the flip is one
label (`project_card`) plus one constraint swap.

New migration **`933c7b604f1c`** (head; chains off `6a7f8eed5b23`) swaps the CHECK. It does **not**
delete the 152 legacy `stage_snapshot`/`readiness_snapshot` rows: the table carries an
`execution_reject_append_only_mutation` trigger, so a DELETE is refused by the schema. The new
constraint is added **`NOT VALID`** — new writes are checked, historical audit rows stay readable.
`downgrade()` restores the prior vocabulary.

## Other touch points

- `stage0_trial.py`: new `Stage0Trial._project_card_ref()` compiles via
  `compile_stage0_project_card` + `ArtifactStatementEvidenceReader`, passing
  `proposals_pending`/`proposals_stale` from `_read_icp_proposals()` and **`readiness_spec_version`
  explicitly** from `ensure_readiness_spec(DEFAULT_STAGE0_POLICY.readiness)` — the revision the
  engine actually evaluates against, never the compiler's `max(version)` default (1.1 review F3).
  Persisted content-addressed as `application/vnd.clue.stage0-project-card+json`.
- `snapshot()` lost its `current_turn` parameter and the `current_turn_input` key: turn identity's
  only owner is now L7/the binder (kills the 1.2-review double-naming). `snapshot()` itself stays —
  it is the human `/status`/`report.json` surface.
- `NO_ROUTING_RECEIPT` reworded: it no longer tells the model to call `record_interview_answer`
  "for this turn's onboarding_input_id".
- `account_research_turn_wiring.py`: its two small snapshots merged into one
  `application/vnd.clue.account-research-card+json` (`ACCOUNT_RESEARCH_CARD_MEDIA_TYPE`), same
  fields, one payload, passed as `project_card_ref`.
- `specialist_wiring.py`: child inherits `project_card_ref` and `client_entity_id`; child budget
  path untouched.
- **Binder consolidation (item I) — done.** `build_agent_context_assembler` and
  `build_head_of_abm_stage0_execution` both take an optional `captured_turns: CapturedTurnBinder`;
  the trial builds one and passes it to both, so a turn is resolved and cached once. The
  independent-instance comments are gone. `get_onboarding_input_for_artifact`'s docstring now
  records that `project_id` is required while the column is nullable, so a capture surface that
  omits it writes an **unbindable** turn (fail-closed, deliberate).

## Deviation surfaced: the trial `instruction` prose is gone, not reworded

The 717-byte `stage_snapshot.instruction` lived inside the artifact §10 deletes, and the card model
is `extra="forbid"` with no slot for surface prose. Re-homing it is spec §8's table, whose owners
are the **trial profile variant / surface policy — task 1.4**. Inventing a new L3 slot for it in 1.3
would have recreated the very defect this slice removes, so it was deleted with its artifact.
**Interim gap until 1.4 lands: the trial no longer tells the model "manual-conversation-only, do not
call start_recon/synthesize_icps".** `registered_client_claim_fields` survives (it is card data);
the routing-receipt guard still enforces the routing half at finalize.

## Tests

Flipped in `tests/api/test_c8_slice0_evidence.py` (helper `_required_l3_artifacts` collapsed to the
production card path; the `_required_l3_artifacts` tripwire retired):
- `test_the_required_l3_bundle_now_fits_its_hard_budget_at_the_same_interview_length`
- `test_the_readiness_ledger_is_serialized_exactly_once_into_required_l3`
- `test_required_l3_bytes_stop_growing_with_the_readiness_ledger` (new `_seed_ledger_only` helper:
  8 pure-ledger turns move required L3 by ≤8 B; 8 material turns grow far under the retired
  900 B/turn floor and stay under the 24,000 B card ceiling)
- `test_record_interview_answer_no_longer_lets_the_model_author_the_answer_or_trusted_ids` extended:
  the model-facing schema is now exactly `{product_id, statements}`.
- Test 5 (identity duplication, Slice 2's evidence) untouched.

New `tests/api/test_c8_project_card_wiring.py` (5): AC-5 assembled-L3 shape (the L3 materialization
round-trips through `Stage0ProjectCard` and carries none of 8 `to_jsonb` column names); the
`project_card` journal role plus a live refusal of `stage_snapshot` by the CHECK; content-addressed
re-persist (AC-9 mechanism); **subprocess determinism (AC-8)** — a self-contained script seeds a
fully deterministic project (fixed scope ids, uuid5 input/decision ids, no client entity because
`account_entity.id` is DB-generated) in a rollback transaction, compiles, and prints
`content_sha256`; run in two interpreters with `PYTHONHASHSEED` 0 and 424242, the shas match; a
`snapshot()` signature guard.

**Fixture gotcha found the hard way:** the first flip dropped test 1's trailing
`run_async(_scenario(...))`, so the body was defined and never executed — it "passed" in 0.0s. If a
DB-backed test in this file is suspiciously fast, check that its scenario is actually invoked. Also:
`assemble` journals a context receipt FK'd to `agent_turn`→`execution`, so an assembling fixture
must insert an `execution` row and call `DbAgentTurnJournal.create` first.

## Verification

`tests/api tests/clue_trial tests/agents tests/stage0 tests/projections` — 700 passed, 1 failed:
the pre-existing `test_agent_runtime_wiring_db.py::test_delegation_is_durable_before_fresh_child_
wake_and_rolls_up_reference_result` (hand-built registry pinning a stale
`evaluate_stage0_readiness` sha; fails on a clean tree). `mypy` clean (456 files),
`lint-imports` 24/24, `ruff check`/`format` clean on all 25 touched files. The structural guards
(`test_package_layout`/`structure_guards`/`dependency_contracts`/`seams`/`beat0_contracts`/
`project_rename_guard`) pass. `alembic heads` = one head, `933c7b604f1c`.

Pre-existing failures NOT caused here (reproduced with the work stashed): `tests/sources`,
`tests/discovery_scoring`, `tests/execution/test_recipes*`, `tests/memory/test_memory_offline`,
`tests/resolvers/test_static`, `tests/icp`, `tests/fleet` — the shared dev DB has a conflicting
`source_manifest`/promoted-recipe state and those suites ERROR at setup on a clean tree too.
`tests/db/test_db_migrations.py` deliberately not run (needs a clean throwaway DB).

## Review fix round (NEEDS-FIX-ROUND → second commit)

Reviewed against spec v2.2 (`0cf1a52`, which added the §8 owner row this round's blocker exposed).

1. **B1 (blocker) — the model could no longer learn the client entity id.** 1.3 closed *both*
   channels (the tool field became engine-injected; the stage snapshot that said "use the supplied
   client entity id" was deleted), while `InterviewStatement._route_shape` still refuses a `claim`
   route without `entity_id` — so every claim-route statement would either fail into the
   `NO_ROUTING_RECEIPT` loop or carry an invented UUID that `_write_claim` accepts unchecked.
   **Layer 1 shipped here:** `Stage0CardProject.client_entity_id`, threaded from the compiler's
   existing `client_entity_id` parameter (the same id the Client-KB read is scoped to, so the card
   cannot advertise an entity its claims section was not compiled against). ~40 B.
   **Layer 2 — engine-defaulting `entity_id` + an existence check — is 1.4's, per spec v2.2.**
   `Stage0ProjectCard` gained a written `schema_version` policy: it stays `"1"` while the card only
   *grows* fields (nothing reads it by version; the sole consumers are the L3 assembler and this
   module), and bumps on a removal/rename/meaning change.
2. **M2 (medium) — account research silently lost its project row.** "The card subsumes it" holds
   only for the Stage-0 card. Extracted `account_research_card_payload(...)` (pure, exported,
   testable without a project run) and added a `project` block (id/name/status/workspace/brand/
   product).
3. **Minor — the `MODEL_FORBIDDEN_AUTHORITY_KEYS` docstring over-claimed.** The strip is
   **top-level only**; three granted tools expose a forbidden name one level down —
   `propose_field`/`propose_source` (`scope.brand_id`, `scope.project_id`) and `submit_ingestion`
   (`declared_context.*`). Documented, with the honest fence (proposal `preconditions` refuse an
   unknown scope; ingestion is fenced by composite workspace FKs — but a wrong-yet-existing sibling
   scope in the same workspace is reachable there). Recursion is 1.4's.
4. **Minor — fail-closed constitution test added**, and it records *what surfaces* the refusal
   today: a bare `ValidationError` at `executor.py:992`, not the typed model-visible plan issue
   `CapturedTurnUnavailable` gets. Same outcome, different legibility; flagged for the whole-branch
   review.
5. **Minor — `evaluate_stage0_readiness` behaviour note.** Injection now always supplies
   `client_entity_id`, so the `compile_product_context` branch runs whenever `product_id` +
   `client_kb_version` are present, where a model that omitted the id previously fell through.
   Correct direction (a decision that could pin a product-context version and silently did not was
   under-evidenced), one extra compile+write per call; stated in the tool's own docstring.
6. **Minor — F8 gate comment block** added for the newly-stripped fields, mirroring 1.2's, and it
   names where the client entity id now comes from (the card, not a description).
7. **Minor — determinism subprocess workspace id** now carries a per-invocation uuid suffix passed
   via argv (same suffix to both processes of one comparison), so xdist/parallel branches cannot
   collide on `c8-determinism-ws`.

The card's bytes changed (one new `project` field), so every card sha moves — expected, and the
subprocess determinism test re-ran green, which is the property that actually matters. No tool
input digest moved (re-verified): still no catalog bump.

## Handoff to 1.4

1. Reword the `brand_id`/`client_entity_id` descriptions inside its bump (profile v9 / skill v7) —
   1.3 deliberately left them so no third bump was forced. Exact list above (8 fields across 5
   tools; 3 of the 7 `client_entity_id` declarations have no description to reword).
2. Re-home the deleted trial `instruction` prose per spec §8 (trial profile variant / surface
   policy). Until then the trial ships without that framing.
3. `docs/specs/PC-C6-platform-deepagent-and-skills.md:347–348` — **resolved by the coordinator in
   `0cf1a52`** (supersession notes added alongside spec v2.2).
4. **Layer 2 of the B1 fix (spec §8, v2.2):** default `InterviewStatement.entity_id` from the
   constitution's trusted `client_entity_id` when `entity_type=account`, and existence-check it,
   replacing today's accept-any-UUID behaviour in `_write_claim`. 1.3 shipped only layer 1 (the
   card shows the id).
5. **Recurse the top-level strip** (contracts.py note): `scope.brand_id`/`scope.project_id` on
   `propose_field`/`propose_source` and `declared_context.*` on `submit_ingestion` are one level
   down and therefore neither hidden nor injected.
