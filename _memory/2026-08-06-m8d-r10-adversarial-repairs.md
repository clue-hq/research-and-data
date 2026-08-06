# 2026-08-06 — M8D R10 adversarial review and repairs (CLOSED — offline acceptance green)

**Final state:** every test directory passes against its own freshly migrated disposable
Postgres (36/36, `/tmp/m8d_per_dir_run.sh` pattern; `tests/db` migration smoke 3/3 on its own
throwaway DB); repo mypy 568 files clean; import-linter 24/24; ruff clean on every touched file.
One late conversion: `tests/fleet/test_b4_composed_run_db.py` — broken at committed HEAD since
the R1 quarantine (never run; DB-gated, outside the curated battery) — now
`test_composed_worker_drives_to_human_checkpoint_then_deep_quarantines`: drives to the human
tier checkpoint, then proves the re-driven DEEP phase fails loudly (`drive_run` task `failed`,
run parked `deep/active`, ledger grew by exactly the checkpoint-resume finalize, no
deep/verification/handoff finalize). The live Exa/Sumble canary remains the only open R10 gate
and stays frozen pending explicit human spend authorization.

## Scope

Adversarial review of the uncommitted R10 live-probe fixes (the Codex defect ledger), a live
verification of the Sumble wire contract, and the structured repair execution. Fable owned all
review/planning/debugging and the critical fixes; Opus 4.8 subagents did scoped implementation.

## Review verdict on the pre-existing uncommitted fixes

**Held up (kept as-is):** tool_choice "any"→"required" normalization at the governed model
boundary; max_tokens→max_output_tokens translation; canonical-JSON span containment
(`_json_contains_text` ↔ `_json_member_span` are structurally consistent); independent-corroboration
`>1` threshold (verified against `verification/corroboration.py`: `claim.corroborations` counts
independent sources *including* the claim's own); committee evidence anchored to exact canonical
provider rows (fail-closed on ambiguity); wait-disposition CAUSED-while-waiting fix (the `caused`
flag is really set in before_dispatch); cold-resume scope upsert + full identity re-verify;
job-scoped NOT EXISTS pending-operation matching; provider-spend job authority (XOR
account/contact control rows); machine-visible `DiscoverBuyingCommitteeInput` constraints;
`_semantic_validation_error` feedback; error-ToolMessage rejection path in the runtime middleware.

**Defects found in the uncommitted diff:** `exa_contact_compiler.py` used `UUID` without import
(2 mypy errors — fixed); 4 stale tests (tool count 44→48, retired `launch_account_deep` surface,
skill pins v1/v3 → v2/v4); new launch tools had **no `model_description`** (model-facing approval
semantics regressed to a generic fallback — fixed with real spend-gate descriptions).

## Sumble contract decision (docs/specs/M8D-R10-sumble-contract-decision.md)

- docs.sumble.com **is v9** (Codex's "public docs describe v3" was a misreading of the jobs
  endpoint's `related_people.job_functions` select arrays). No migration.
- Advanced-query grammar: only `<dimension> EQ '<value>'` atoms joined by `AND`. No IN/OR/NOT.
- `/v9/teams` query dimensions exclude `job_level` entirely → explains 400 even on single-EQ probes.
- 400/402/422 are validated **zero-credit** rejections ("you still get a 400/402 up front").
- Live v9 OpenAPI sha `cd659dd5…` ≠ the S2A-pinned `8eac8f9b…` — contract drift to re-pin.

## Repairs landed (all offline-verified)

1. **R1 (Fable)** — deleted `_provider_filter` (`job_function IN`/`job_level IN` compiler) from
   `sumble_committee_inputs.py`; committee requests carry no advanced query; plan selectors gate
   locally. `SumbleAdvancedQuery` now enforces the documented grammar (`dimensions()` +
   `require_dimensions()`); `people_search_request`/`teams_search_request` enforce per-endpoint
   dimension allowlists (`PEOPLE_QUERY_DIMENSIONS`, `TEAMS_QUERY_DIMENSIONS`).
2. **R2 (Fable)** — `ProviderResponseError` carries `status_code` + bounded `body_excerpt` +
   `is_deterministic_rejection` (4xx only; malformed-2xx stays ambiguous); `get_json` threads the
   response body; committee coordinator gained `_mark_provider_rejected` (rejection-evidence
   artifact, attempt RESPONDED with failure_code `<src>_provider_rejected_http_<status>`,
   snapshot FAILED_TERMINAL/NOT_CHARGED, operation FAILED_TERMINAL) at all three dispatch sites.
3. **R3 (Fable)** — engine partial-failure policy: new `EntityResearchGovernedRejection`
   (code+detail, bounded render) converted to `ToolException` in `_provider_tool` with
   `handle_tool_error=True` → error ToolMessage (verified: langchain_core 1.5.1 sets
   status="error"), so the agent repairs/reroutes/finalizes instead of the job suspending.
   Converted: `_UnavailableProviderAction`, Sumble account field/source-authority mismatch,
   committee request-authority mismatch, committee eligibility rejection, committee-scope-vs-plan
   violation, and FAILED_TERMINAL outcomes of both Sumble actions (`provider_rejected`).
   SPEND_OUTCOME_UNKNOWN and post-persistence integrity still suspend. Channel reveal/validation
   fail-closed path deliberately untouched (§16 release criterion).
4. **R4 (Opus)** — committee plan (functions/levels/teams/personas/cap + confirmed questions)
   projected into `read_account_research_state` and the initial task instruction; engine
   validates `buying_unit_scope.target_functions` ⊆ plan functions (exact, case-insensitive;
   reclassified by Fable to governed rejection `committee_scope_outside_plan`).
5. **Finalize-once guard (Fable)** — middleware refuses every governed tool call after the
   finalize engine tool returns its proposal (`finalization_already_proposed` error ToolMessage,
   journaled `post_finalization_rejected`); prompt guidance alone had not stopped live looping.
6. **Value-only match haystacks (Fable)** — committee office/business-unit/function discriminators
   match provider-returned values only (`_match_haystack`, `_organization_names`), never
   serialized JSON schema keys; org-wide rule narrowed to provider-returned organization names.
7. **Item G resolved by analysis** — untargeted confirmed questions reach the agent via
   `authorization.effective_research_questions` (task context + Exa research_intent); the
   `exa_deep_preparation` target-field filter only affects the quarantined legacy prep path.
8. **Opus R5a (in flight at note time)** — account-gap deterministic-rejection classification,
   `CLUE_AGENT_WORKSPACE_ALLOWLIST` parse robustness, live-harness env isolation + contact resume.
9. **Opus R5b** — O3 behavior tests rebuilt over account-deep-steering@v2 / research-task@v4 /
   `launch_account_research`.

## Fable verification of the Opus lanes (post-landing)

- **R4** verified; scope-vs-plan mismatch reclassified to governed rejection
  (`committee_scope_outside_plan`) with tests updated. Its open questions resolved: nullable plan
  stays (historical/static seam); all confirmed questions project (no committee-only question
  model exists); only functions validated (scope carries no level/persona fields — future work).
- **R5a** verified by reading `_mark_provider_rejected` in `sumble_account_gaps.py` (correct
  catch ordering; spend recomputed from the snapshot ledger so partial settled charges survive;
  pending field results closed) and by running its DB-gated tests against `clue_m8d_r10a`
  (passed) plus the settings tests. Residual it flagged: `recipe1_workspace_allowlist` and
  `c7_workspace_canary_ids` share the tuple-decode fragility (out of scope, note kept).
- **R5b** verified; its finding (launch tools lacked `model_description`) fixed by Fable — both
  promoted launch tools now carry real spend-gate model descriptions, and the O3 descriptor
  assertions pin phrases of the real text.
- **Fable follow-ups after the lanes:** contact-side Exa clamp `min(target.exa_max_results, 20)`
  removed from the live harness (contact contract is 50 — same truncation class as defect #19);
  cutover test now pins both account and contact 50-caps robustly; stale surface matrices
  updated (`test_toolbelt_wiring` 44→48 names / 50→55 registrations, `test_c8_trial_surface`
  withheld set now `launch_account_research`/`launch_contact_research`/recon/onboarding/icps).

## First-ever whole-tree DB-enabled run (Fable end-to-end pass, per user instruction: no agents)

No DB-enabled run of the *entire* test tree had ever happened post-cutover (Codex's battery was a
curated 13-module subset; the R5a full run had no DB, skipping ~1,450 tests). Running it surfaced:

1. **Suite-hang bug (fixed):** `tests/api/test_exa_targeted_enrichment_e1.py::
   test_e1_real_db_import_cost_materialization_and_zero_call_replay` drove the R1-quarantined
   `enrich_selected_accounts@1` address as a background task and then bare-`await`ed
   `transport.import_entered.wait()`; the instant quarantine refusal left the event forever unset
   and parked the whole suite holding an idle transaction (the `spent_cents` ClientRead
   signature). Diagnosed via pytest `-o faulthandler_timeout` stack dump (py-spy needs root on
   macOS). Fixed by (a) exercising the preserved engine seam (`ExaTargetedEnrichmentStarter
   .start`) directly — create/join-in-flight/replay/DSAR coverage retained; the tool-address
   refusal stays pinned by the toolbelt matrix — and (b) racing the dispatch-entered event
   against the start task so early failures assert instead of hanging.
2. **Retired-flow acceptance tests converted to quarantine contracts:** A1
   full-production-entry (now `test_a1_full_production_entry_is_a_quarantined_fail_loud_address`
   — constructor refusal + zero durable side effects) and O2 launch-immutability (fresh
   `launch_account_deep` refuses `entity_research_agent_not_composed`, nothing enqueued/written;
   the preserved durable launch substrate exercised directly for replay/conflict).
3. **Approver name-default flip fallout:** `approve_contact_research_selection` default is now
   the R7 `@2` (request/approved_at shape); the M8C `@1` stays version-addressable. Updated the
   toolbelt matrix body + expected refusal (`entity_research_agent_not_composed` when not
   composed) and pinned `version="1"` in the M8C C6 selection acceptance.
4. **exa→exa_deep tier-plan pins:** field-registry and ICP-compiler tests updated to the
   promoted `("sumble_jobs","linkedin_jobs","exa_deep")` plan.
5. **Shared-DB contamination class (not regressions — two distinct sources):**
   (a) `tests/db/test_db_migrations.py` runs alembic down→up against `CLUE_DATABASE_URL` and must
   run on its own throwaway DB (repo convention; passes 3/3 there).
   (b) More fundamental: the M8D fleet/entity-research DB tests **commit durable rows by design**
   (queue/lease/wake semantics need real cross-connection commits — verified: 4
   `entity_research_job` rows, the full 21-manifest source registry, and 65 field definitions
   survive in the suite DB), while many older modules register minimal *fixture* manifests at
   the same `(source_key, version=1)` inside rollback transactions and hit
   `SourceManifestRedefinitionError` once the canonical registry is durably present
   (waterfall/discovery_scoring/durable/fleet/c6 clusters — every one passes standalone on a
   fresh DB). The whole tree therefore cannot share one database in a single invocation.
   **Adopted verification protocol:** per-top-level-directory isolation — each `tests/<dir>`
   runs against its own freshly migrated disposable DB (`/tmp/m8d_per_dir_run.sh` pattern);
   `tests/db` keeps its own throwaway DB.

## Still open / next

- R5a agent results to verify (its in-flight settings validator briefly broke JSON-array parsing
  during a migration attempt — re-run migrations after it lands).
- Full isolated-Postgres R10 battery (`clue_m8d_r10a` on localhost:5432, clue/clue) + repo mypy +
  ruff + import-linter; update `M8D-R10-cutover-and-live-acceptance.md` ledger.
- Live canary remains frozen: NO provider spend without explicit human authorization. Sequence
  per the contract note: Sumble no-filter probe → account fleet → committee → separate contact
  selection → contact fleet → zero-spend replay, spend checkpoint after each gate.
- Deferred (documented, not blocking): huge multi-team evidence spans cite the whole `"teams"`
  collection; `_select_row_evidence` hard-fails on a person with two distinct raw rows (routes to
  whole-snapshot failure — consider review-routing); reentrant account lock means parallel
  sibling tool calls of one job share the lease (R9 wave admission is the real guard); spend
  guard requires job.state='running' while committee inputs accept waiting_external — verify on
  the resume path during the live canary.

## R5a results (Opus, 2026-08-06) — landed, uncommitted

1. **Sumble account-gap deterministic rejection** (`platform/api/clue_api/sumble_account_gaps.py`).
   `start()` now catches `ProviderResponseError` before the blanket `except Exception`; a hard 4xx
   (`is_deterministic_rejection`) routes to the new `_mark_provider_rejected`, mirroring the
   committee coordinator: a `{"provider_rejection": {source_key, http_status, body_excerpt}}` JSON
   artifact is captured + bound (`<source>_provider_rejection` edge) and stamped as the failing
   snapshot's `response_artifact_key`; the DISPATCHING snapshot goes FAILED_TERMINAL /
   `not_charged` with failure code `<source_key>_provider_rejected_http_<status>`; pending field
   results go `failed_terminal`; the operation goes FAILED_TERMINAL with spend recomputed from the
   snapshot ledger (`not_charged` when nothing settled — so no `project_run.spent_cents` movement).
   No migration: the ledger already allows a response artifact + failure code on a failed snapshot.
   A `ProviderResponseError` with no status (malformed 2xx body) still takes the unknown path.
   Tests: `tests/api/test_sumble_account_gaps_s1.py` (+ a shared `_seed_selected_high_tier_account`
   helper) — DB-gated, they SKIP here (no Docker/Postgres reachable this session).
2. **`CLUE_AGENT_WORKSPACE_ALLOWLIST` robustness** (`libs/clue-config/clue_config/settings.py`).
   Root cause was *not* validation: pydantic-settings JSON-decodes complex fields inside the env
   source, so a bad value raised `SettingsError` while building **all** settings. Fix = annotate
   the field `Annotated[tuple[str, ...], NoDecode]` + a `mode="before"` validator accepting a JSON
   array *or* a comma-separated list, raising a ValueError naming the variable and both formats.
   JSON-array parsing is verified working (`tests/test_config_settings.py`, 5 new cases).
   Also flipped repo `.env` line 100 to the comma form: `set -a; source .env` strips the JSON
   quotes, leaving `[ws_fixture_insight_health_aura]`, which is what actually broke the canary.
3. **Live harness** (`scripts/13_m8d_r10_live_acceptance.py`). (a) `_settings()` now returns
   `(Settings, environment_report)`: it builds with `_env_file=None` **and** temporarily withholds
   every non-secret `CLUE_*` settings variable, so the composition under test is the pinned set +
   library defaults; the report classifies every `CLUE_*` var as secret / pinned / suppressed /
   ignored, is printed at startup and included in the output JSON under `environment`. Ambient env
   re-read by libraries (`default_gateway_config`) is documented as outside the seam.
   (b) New `--resume-contact-run <research_run_id>`: reads `entity_research_contact_launch`,
   requires the mapped account canary to be terminal, and replays the exact committed launch
   (same request_json/operation id/actor/confirmed_at) — no reseeding, no new selection approval,
   no new spend authorization — then drives contacts and runs the normal replay acceptance.
   Account/contact resume now share `_account_resume_context`; the launch request is built once
   and reused by the replay leg. Refusals kept: live-call ack, fresh-DB check (resume modes are
   mutually exclusive and reported in `database.resume_mode`).

Verified: `mypy` (repo, 568 files) clean; `ruff check`/`format` clean on touched files;
`lint-imports` 24/24; `pytest` 2165 passed / 1450 skipped / **4 pre-existing failures** owned by
the concurrent toolbelt work (`test_toolbelt_wiring::test_build_toolbelt_registers_the_full_set`
and 3 `test_c8_trial_surface` cases: `toolbelt_wiring.py` now registers `launch_*`/`read_*` entity
research tools that those matrices do not list yet). Not verified: every DB-gated test (no
Postgres/Docker in this session) and any live provider path.
