# 2026-08-19 — Slice D exit gate: full `make check` failure baseline, A/B-proven pre-existing

**Branch:** `platform/comprehensive-account-contact-research-v2` at D5 (`tests/api/test_committee_agent_inference_acceptance_db.py` present, uncommitted at run time; D1–D4 = `48c5c250..a9036d65`).
**Run posture (the numbers below are posture-dependent — read this first):** `make check` from the
branch worktree with the workspace `.env` **sourced and exported** (every `CLUE_*` var ambient,
including `CLUE_PRODUCT_PATH=integration_pilot` and real `CLUE_AUTH_*`), and
`CLUE_DATABASE_URL` pointed at **`clue_task_d1`** — the per-branch throwaway DB that many
committing suites had already written into across the D1–D5 sessions (dirty shared state).

## Headline result

`make check` = lint ✅ + typecheck ✅ (727 files) + contracts ✅ (26 kept) + pytest:
**68 failed, 5149 passed, 11 skipped in 9:00**. Every lane-D surface passed inside the same run
(profiling/committee, r5, r11 bridge, fresh-skip, r3/r4/authority, frontend-read contacts, the new
D5 acceptance).

## The controlling verdict: byte-identical A/B at the pre-lane-D base

Re-ran the exact 31-file failure set in a detached worktree at **`df1aaf21`** (Slice-A head, before
any lane-D commit) with the **same env posture and same `clue_task_d1` DB**, then the same subset on
HEAD, serialized:

- base: `65 failed, 236 passed` · HEAD: `65 failed, 236 passed`
- `comm` on the FAILED test-id lists: **HEAD-only = ∅, base-only = ∅**
- `diff` on the full `FAILED <id> - <error>` lines (error text included): **empty**

**Lane D (D1–D5) causes zero of these failures and fixes zero.** (First base pass showed 67 vs 68
before the runs were serialized/normalized — that ±2 is run-order flake inside the same set, not a
delta between base and HEAD; the controlled same-command comparison is the byte-identical one.)

## 68 = 65 + 3: the order-dependent trio

Three tests fail **only under full-suite ordering** and pass in isolation on HEAD (11/11 green when
their two files run alone): `tests/durable/test_account_run_db.py::test_compute_gap_fields_detects_missing_and_filled`,
`…::test_graph_end_to_end_on_db_store_and_postgres_checkpointer`,
`tests/fleet/test_b4_composed_run_db.py::test_composed_worker_drives_to_human_checkpoint_then_deep_quarantines`.
Cross-suite state pollution (same class as the `tests/api` DB-pollution defect recorded in the
Part-II D4b note).

## Decomposition pipeline (all measured on HEAD, same 31-file subset)

| posture | failed | delta explained |
|---|---|---|
| `.env` exported + dirty `clue_task_d1` | **65** | reference |
| all `CLUE_*` env vars stripped (only DB URL), same dirty DB | **41** | **24 ambient-env artifacts** — tests asserting auth/webhook/settings posture broken by exported real config: `RuntimeError: authenticated-principal projections mode requires CLUE_AUTH_ENABLED=true` (projections_app, c7_production_readers, extractor_composition, lane_d_b1_join, official_site_crawl_wiring), `'/v1/webhooks/exa-websets' not in paths` (exa_websets_wiring — ambient webhook secret mounts the route), `test_config_settings` clerk parties/environment, `test_merge_policy` strict-default, o3-adjacent env reads |
| + freshly migrated DB (`clue_ab_fresh`) | **18** | **23 dirty-shared-DB artifacts** — committed leftovers in `clue_task_d1`: `SourceManifestRedefinitionError: source 'apollo'/'crm'/'clay'/'official_site' already registered … with a different definition` (waterfall ×7, adapters ×1, +), `tests/discovery_scoring` count asserts against pre-existing rows (`assert 7 == 0`, `assert 10 == 3`, `assert 89 == 2`; tier_checkpoint ×9, phase ×2, coverage ×2), `tests/db/test_db_migrations` up/down/base against a shared schema ×3, `tests/integration/test_fi2_slice1_read_layer` ×9 (asyncpg DBAPIError class), r11_lane_f flag-off compose ×2, frontend_bulk_actions ×2 |
| + `CLUE_PRODUCT_PATH=default` (pilot overlay off) | **14** | **4 pilot-posture-sensitive** — the `.env` **file**'s `integration_pilot` line (verification off) flips merge/service behavior for tests that read the real `.env`: `tests/claimstore/test_merge.py::test_empty_when_no_eligible_claim`, `tests/compliance/test_governance_e2e.py::test_supported_tier4_synthesis_is_promoted_to_current_value` (unverified tier-4 served under pilot → CurrentValue not empty/promoted-differently), `tests/integration/test_fi2_slice3_economics.py` (the D3-session-recorded stale-neutral-claim merge-selection debt — now root-caused to the pilot merge policy serving a different claim), `tests/api/test_frontend_bulk_actions.py::test_contact_batch…` (email capability differs under overlay) |

**Slice-A hermeticity gap exposed:** Slice A stripped `CLUE_PRODUCT_PATH` from the *env* in
`tests/api/conftest.py`, but `Settings(env_file=".env")` still reads the workspace `.env` *file*, so
any machine with the pilot line in `.env` fails the 4 pilot-sensitive tests (and `make check` run
with `.env` exported fails ~50). Owner: the next hermeticity pass; not lane-D.

## The 14 irreducible pre-existing debts (fresh DB, clean env, default path)

Exact signatures, one line each:

1. `tests/agents/test_o3_account_deep_behavior.py::test_scripted_o3_conversations_cover_the_non_linear_gate` — `AgentCatalogError: skill 'skill:account-deep-steering@v4' is not disclosed by this profile` (`clue_agents/registry.py:235`). Already recorded pre-existing + reproduced at BASE in the Slice-A close-out.
2. `tests/api/test_p36_leg_resilience_db.py::test_a_gate_answer_queued_behind_a_leg_opening_still_reaches_head_of_abm` — `TypeError: insert_gate_answer() missing 1 required keyword-only argument: 'expected_subject_sha256'` (test not updated for the unified-gate API; Part-III merge fallout).
3-5. `tests/api/test_production_context_s3_db.py::{test_kb_pin_receipt_and_missing_or_foreign_context_fail_closed, test_post_recon_projects_share_client_card_and_isolate_stage0, test_pre_recon_composes_real_l2_and_honest_empty_l3}` — `ValidationError: 1 validation error for AgentTurnSubmissionRow — previous_turn_outcome Field required` at `test_production_context_s3_db.py:165` (the test builds the row dict by hand; schema gained `previous_turn_outcome` after the S-series merge).
6. `tests/api/test_production_context_s31_fleet_db.py::test_real_fleet_chain_keeps_original_pin_through_checkpoint_finalization_and_replay` — `ArtifactNotFound: no artifact stored under 'production-context-s3-…/f9ec…'` (FileNotFoundError under pytest tmp; references the s3 tests' workspace hash — intra-file cross-test artifact dependency).
7. `tests/api/test_toolbelt_wiring.py::test_out_of_order_matrix` — `ValidationError: 2 validation errors for DraftAccountResearchDirectiveInputV3 — directive Field required; body Extra inputs are not permitted` (`clue_toolbelt/runner.py:144`; matrix fixture still sends the pre-V3 `body` shape).
8. `tests/db/test_unified_agent_gate_migration.py::test_discovery_configuration_is_the_only_head_after_the_explicit_gate_merge` — `assert ['a1c5b9842f0e'] == ['064ad0f43519']` (expects the pre-Part-III head; already recorded pre-existing in the Slice-A close-out).
9. `tests/integration/test_lane_e_e1_acceptance.py::test_a_completed_job_produces_one_verified_evidence_backed_summary` — `assert 'rejected' == 'verified'` (`:650`).
10. `tests/integration/test_lane_e_e2_acceptance.py::test_a_completed_contact_job_produces_one_verified_served_overview` — `assert 'rejected' == 'verified'` (`:516`).
11-14. `tests/integration/test_lane_e_e3_acceptance.py::{test_a_completed_job_produces_one_verified_narrative_per_committee_persona (:712 'rejected'=='verified'), test_a_second_delivery_replays_instead_of_re_positioning (:824 assert 2 == 1), test_an_unresolvable_client_context_refuses_without_a_failure_metric (:791 assert None is not None), test_with_the_flag_off_the_step_never_offers_the_job (:954 assert 6 == (1 + 2))}` — the lane-E acceptance suite's faithfulness-judge expectations (`rejected` where it expects `verified`) plus follow-on count drift; the judge verdict path changed after lane E's freeze (suspect: judge-model/entailment behavior drift or the merged unified gate) — **needs its own triage; not lane-D** (all 6 lane-E failures byte-identical at `df1aaf21`).

## Where this leaves the Slice-D exit gate

- Lint/typecheck/contracts: green. Every lane-D-owned suite green inside the full run.
- The 68 pytest failures: **all pre-existing at the pre-lane-D base under identical conditions**
  (byte-identical A/B), decomposing into 24 ambient-env + 23 dirty-shared-DB + 3 test-ordering +
  4 pilot-posture-sensitive + 14 genuine test/code debts inherited from the Part-III/S-series merge
  and prior slices, of which o3 (#1), the migration-head pin (#8), and the economics debt were
  already on record in `_memory` before this gate.
- Follow-up owners (not lane-D): a hermeticity pass for the `.env`-file leak; a dedicated triage of
  the lane-E acceptance drift (#9-14); the s3/s31/toolbelt/p36 fixture updates (#2-7) belong to the
  respective surface owners at the next integration.

**Raw evidence:** produced under `/tmp` during the 2026-08-19 session (`head_full.txt`,
`base_full.txt`, `head_cleanenv.txt`, `head_freshdb.txt`, `head_nopilot.txt`, plus the `make check`
task output); `/tmp` is ephemeral — this note is the durable record and reproduces every command
posture needed to regenerate them. A/B worktree `/tmp/tunis-base-ab` at `df1aaf21`; throwaway DBs
`clue_ab_fresh` (fresh-baseline) and `clue_task_d1` (dirty branch DB).
