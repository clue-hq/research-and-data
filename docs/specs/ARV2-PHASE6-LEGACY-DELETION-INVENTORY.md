# ARV2 Phase 6 — legacy-lane deletion inventory

**Status:** inventory only. **Nothing in this document has been deleted.** It is the plan input for
the Phase-6 PR, built from evidence collected on `track-d4b` @ `ceb82f841` against the worktree
database `postgresql://clue:clue@localhost:55060/clue` at head `7332ac974920` on 2026-09-09.

**Founder ruling this document serves (2026-09-09):** *ARV2's own rows are the only truth. Nothing
about the old research lane matters; it is deleted, never bridged.* D4-b removed the last read of
the old lane from the accounts/contacts screens (Tasks 1–6). What remains is the old lane's own
code and its own tables, which nothing on the ARV2 path reads any more.

**How the evidence was produced** (re-runnable):

```bash
psql postgresql://clue:clue@localhost:55060/clue -Atc "select tablename from pg_tables where schemaname='public' order by 1"   # 327 tables
python3 - <<'PY'   # table -> creating migration, from the raw CREATE TABLE statements
import re, pathlib
for p in sorted(pathlib.Path('alembic/versions').glob('*.py')):
    for m in re.finditer(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"?([a-z_0-9]+)"?', p.read_text(), re.I):
        print(m.group(1), p.name)
PY
grep -rl -E '\b<table>\b' --include='*.py' --include='*.sql' platform libs subsystems scripts   # readers/writers
```

Raw sweeps kept out of git under `.artifacts/`: `d4b-rowcounts.txt`, `d4b-table-migration.txt`,
`d4b-table-refs.txt`, `d4b-legacy-table-owners.txt`, `d4b-module-importers.txt`.

---

## 0. Headline

| | count |
|---|---|
| Tables in the database | **327** (323 created by an in-repo migration; `alembic_version` + the 3 LangGraph `checkpoint*` tables are not) |
| Tables the ARV2 path (`clue_api/arv2` + `clue_api/frontend_read`) actually touches | **38** (41 name hits, 3 of them docstring-only prose about the old lane) — the survive list in §4 |
| **Tier A — old-research-lane tables, delete with the code** | **83** (44 M8D + 13 C7 + 13 M8A/B/C + 7 committee/selection + 6 Stage-0/ICP) |
| Tier B — shared substrate the old lane also uses. **RULED 2026-09-09 (§1.2):** 72 drop with the lane, 20 keep (5 compliance + 7 claim-store ring + 8 misfiled platform tables) | **92 → 72 drop / 20 keep** |
| Tier C — must survive | the rest (§4) |
| **Tier A modules named for the lane (`*entity_research*` / `*research_view*`)** | **40 files, 29,778 LOC** |
| Tier A modules behind the M8D R1 quarantine (`clue_api/deep/` + the named trees) | **+ ~8,500 LOC** |
| Legacy-only test files (`*entity_research*`, `*research_view*`, `*fi2*`) | **19,419 LOC** across 17 files |

---

## 1. Tables

### 1.1 Tier A — the old research lane's own tables (83)

Nothing under `platform/api/clue_api/arv2` or `platform/api/clue_api/frontend_read` references any
row in this section (verified by `\b<table>\b` grep over both roots; the three apparent hits —
`account_run`, `account_research_directive`, `icp_spec` — are **docstring prose** in
`frontend_read/project_run_context.py:8` and `arv2/account_research_launch.py:18`, not SQL).

`prod` = files under `platform|libs|subsystems|scripts` naming the table; `tests` = files under
`tests/`. Row counts are the worktree DB at head.

#### (a) M8D entity-research runtime — 44 tables, 1,044 rows

| table | rows | created by | prod | tests |
|---|---|---|---|---|
| `entity_research_run` | 37 | `022b1154b3aa_m8d_r2_entity_research_jobs.py` | 20 | 17 |
| `entity_research_job` | 37 | `022b1154b3aa` | 25 | 26 |
| `entity_research_job_event` | 158 | `022b1154b3aa` | 2 | 2 |
| `entity_research_job_finalization` | 10 | `022b1154b3aa` | 1 | 1 |
| `entity_research_job_wait` | 10 | `022b1154b3aa` | 1 | 1 |
| `entity_research_agent_turn` | 86 | `ac980e12eb5e_m8d_r3_entity_research_agent_journal.py` | 4 | 6 |
| `entity_research_agent_event` | 229 | `ac980e12eb5e` | 4 | 6 |
| `entity_research_result` | 0 | `f643425d0be4_m8d_r4_governed_research_tools.py` | 7 | 7 |
| `entity_research_result_field` | 0 | `f643425d0be4` | 6 | 1 |
| `entity_research_result_evidence` | 0 | `f643425d0be4` | 6 | 1 |
| `entity_research_tool_request` | 0 | `f643425d0be4` | 10 | 8 |
| `entity_research_provider_observation` | 0 | `f643425d0be4` | 6 | 7 |
| `entity_research_provider_operation` | 0 | `5764311c620d_harden_m8d_r0_r4_authority_and_state.py` | 3 | 13 |
| `entity_research_account_coverage` | **1** | `85595185f793_m8d_r5_account_research_agent_state.py` | 4 | 12 |
| `entity_research_account_committee_scope` | 0 | `85595185f793` | 3 | 3 |
| `entity_research_account_finalization_intent` | 0 | `85595185f793` | 1 | 2 |
| `entity_research_account_review_item` | 0 | `85595185f793` | 2 | 2 |
| `entity_research_provider_settlement_fold` | 0 | `85595185f793` | 3 | 3 |
| `entity_research_sumble_projection` | 0 | `85595185f793` | 2 | 2 |
| `entity_research_account_fleet` | **1** | `4ff507129dd5_m8d_r6_account_research_fleet_control.py` | 8 | 6 |
| `entity_research_account_fleet_control_event` | 0 | `4ff507129dd5` | 1 | 1 |
| `entity_research_account_fleet_job_control` | 0 | `4ff507129dd5` | 6 | 1 |
| `entity_research_account_fleet_return` | 0 | `4ff507129dd5` | 1 | 0 |
| `entity_research_contact_job_authority` | 0 | `02e552db75da_m8d_r7_contact_selection_and_.py` | 6 | 2 |
| `entity_research_contact_launch` | 0 | `02e552db75da` | 4 | 2 |
| `entity_research_contact_coverage` | 0 | `7bb3178d7580_m8d_r8_contact_research_agent_state.py` | 2 | 1 |
| `entity_research_contact_channel_causation` | 0 | `7bb3178d7580` | 4 | 1 |
| `entity_research_contact_channel_cost_fold` | 0 | `7bb3178d7580` | 2 | 1 |
| `entity_research_contact_facet_event` | 0 | `7bb3178d7580` | 2 | 1 |
| `entity_research_contact_finalization_intent` | 0 | `7bb3178d7580` | 1 | 1 |
| `entity_research_contact_fleet_return` | 0 | `7bb3178d7580` | 1 | 0 |
| `entity_research_contact_identity_lock` | 0 | `7bb3178d7580` | 1 | 1 |
| `entity_research_contact_review_item` | 0 | `7bb3178d7580` | 2 | 0 |
| `entity_research_budget_reservation` | 36 | `0070930672a4_m8d_r9_parallel_admission_and_wait_.py` | 1 | 2 |
| `entity_research_budget_reservation_release` | 36 | `0070930672a4` | 1 | 2 |
| `entity_research_provider_permit` | 46 | `0070930672a4` | 1 | 1 |
| `entity_research_provider_permit_release` | 46 | `0070930672a4` | 1 | 1 |
| `entity_research_tool_batch` | 63 | `0070930672a4` | 2 | 3 |
| `entity_research_tool_batch_event` | 76 | `0070930672a4` | 3 | 2 |
| `entity_research_tool_batch_member` | 86 | `0070930672a4` | 2 | 2 |
| `entity_research_tool_batch_result_subject` | 66 | `0070930672a4` | 2 | 1 |
| `entity_research_tool_batch_wait` | 10 | `0070930672a4` | 1 | 0 |
| `entity_research_tool_batch_wait_member` | 10 | `0070930672a4` | 1 | 0 |
| `entity_research_account_committee_unavailable` | 0 | `612428f3731f_committee_axis_provider_unavailable.py` | 2 | 1 |

**Note — the only ARV2-adjacent name collision:** `provider_call_ledger` (an **ARV2** table) has a
column called `entity_research_job_id`, inherited from the old lane's naming. That column holds an
`arv2_research_job.job_id`. It is the one documented substring allowance in
`tests/api/test_frontend_read_arv2_only_guard.py`. **Do not rename or drop it as part of the table
sweep** — rename it only in a separate, deliberate ARV2 migration if the name is worth fixing.

**Note — D4-b removed the last ARV2 writer.** Before Task 6 the D1 answer-key loader seeded
`entity_research_run` / `_account_fleet` / `_job` / `_account_coverage` as a database fixture. It no
longer does (commit `ceb82f841`); the two rows still in `entity_research_account_coverage` /
`_account_fleet` and the 37 in `_run`/`_job` are pre-D4-b leftovers of the real M8D runs the
worktree DB carries. So the drop has **no remaining ARV2 writer to wait on**.

#### (b) C7 research view — 13 tables, 39 rows

| table | rows | created by | prod | tests |
|---|---|---|---|---|
| `research_view_snapshot` | 0 | `a69a1769d4bc_c7_4_reference_only_research_view_.py` | 6 | 3 |
| `research_view_snapshot_section` | 0 | `a69a1769d4bc` | 5 | 0 |
| `research_view_snapshot_item` | 0 | `a69a1769d4bc` | 5 | 1 |
| `research_view_snapshot_subject` | 0 | `a69a1769d4bc` | 1 | 1 |
| `research_view_snapshot_support` | 0 | `a69a1769d4bc` | 2 | 0 |
| `research_view_snapshot_evidence_action` | 0 | `a69a1769d4bc` | 3 | 1 |
| `research_view_change_report` | 0 | `9df19defc755_c7_5_governed_research_view_recheck.py` | 2 | 1 |
| `research_view_change_operation` | 0 | `9df19defc755` | 1 | 0 |
| `research_view_change_item` | 0 | `9df19defc755` | 1 | 1 |
| `research_view_event` | 0 | `9df19defc755` | 1 | 1 |
| `research_view_section_staleness` | 0 | `9df19defc755` | 2 | 1 |
| `research_view_field_route` | **39** | `6a7f8eed5b23_c7_9_production_research_view_readers.py` | 3 | 0 |
| `research_subject_activity` | 0 | `6a7f8eed5b23` | 2 | 0 |

`research_view_event` + `account_run` were the two tables behind the E6 activity route that D4-b
Task 5 deleted (`frontend_read/account_activity.py`, 314 LOC). E2's `activity[]` is composed by
`v1_shared.activity_for` over the ARV2 `account_activity_event` table instead.

#### (c) M8A/M8B/M8C account lane + the handoff outbox — 13 tables, 0 rows

| table | rows | created by | prod | tests |
|---|---|---|---|---|
| `account_run` | 0 | `79d56a0f4425_account_run_table_m7_1_eng_131.py` | **51** | 28 |
| `account_deep_launch` | 0 | `a83e52bebc7c_account_deep_launch_o2.py` | 7 | 6 |
| `account_deep_launch_account` | 0 | `a83e52bebc7c` | 1 | 0 |
| `account_gap_operation` | 0 | `bd0b7e62a2b4_s1_sumble_account_gap_ledger.py` | 4 | 6 |
| `account_gap_snapshot` | 0 | `bd0b7e62a2b4` | 3 | 1 |
| `account_gap_field_result` | 0 | `bd0b7e62a2b4` | 1 | 1 |
| `account_handoff` | 0 | `9666e86a6e9a_m12_2_account_handoff_materialization.py` | 18 | 3 |
| `account_handoff_subject` | 0 | `a69a1769d4bc` | 2 | 1 |
| `account_research_directive` | 0 | `8f44b739674c_account_research_directive_a2.py` | 5 | 12 |
| `account_research_directive_event` | 0 | `8f44b739674c` | 1 | 1 |
| `account_research_directive_override` | 0 | `8f44b739674c` | 1 | 0 |
| `account_research_directive_account` | 0 | `5330703a78a3_harden_a2_research_directive.py` | 2 | 4 |
| `handoff_event` | 0 | `ebba8073cc2a_m12_3_handoff_event_outbox.py` | 5 | 2 |

`account_run` is the **highest-blast-radius Tier-A table** (51 production files). Its last consumer
on the ARV2 path is `account_research_turn_wiring.py` (§2.5) — a **write/read of the old lane's own
run row**, not a screen read.

#### (d) Committee / contact-selection ledgers — 7 tables, 0 rows

`committee_acquisition_attempt` / `_operation` / `_snapshot` (`f8a81c7e1563_s2b_…`),
`committee_eligibility_decision` (`a5e32cf0815d_s2d_…`), `contact_research_selection` +
`_approval` + `_cancellation` (`4d9b02f218dc_m8c_c6_…`, `d338ba5a8f7e_…`). 1–10 prod files each.

#### (e) Stage-0 recon / ICP / readiness — 6 tables, 67 rows

| table | rows | created by | prod | tests |
|---|---|---|---|---|
| `icp_spec` | 10 | `0010_icp_spec.py` | 19 | 20 |
| `recon_run` | 27 | `1b71451d48cd_phase_c4_governed_stage0_recipe0.py` | 9 | 8 |
| `readiness_decision` | 10 | `1b71451d48cd` | 10 | 6 |
| `readiness_override` | 10 | `1b71451d48cd` | 3 | 1 |
| `readiness_spec_revision` | 10 | `1b71451d48cd` | 3 | 0 |
| `stage0_icp_synthesis` | 0 | `2fb8e2479183_stage0_durable_icp_synthesis.py` | 2 | 1 |

ARV2 onboarding replaced this front edge entirely: the confirmed ICP is a
`brand_knowledge_document`, and the ARV2 research run pins an ICP **artifact** key/sha, not an
`icp_spec` row. `arv2/account_research_launch.py:18` says so in prose (`No icp_spec row, no
account_research_directive, no Stage-0 pin on the project run`).

**One open question for the Phase-6 plan:** the Stage-0 *tool/recipe* surface
(`stage0_project_tools.py` 1,772 LOC, `stage0_tools.py` 1,515, `stage0_trial.py` 1,513,
`projections/stage0.py` 1,457, `stage0_recipe.py` 665, `stage0_setup.py` 673, …) is bound to the
**Head-of-ABM production turn**, not to the accounts screens. Deleting the six tables above is safe
for the screens; deleting the Stage-0 *code* is a separate decision that belongs to whoever owns the
production turn. **Do not fold the two into one step.**

#### (f) Tables the answer-key loader used to seed

None remain. See §1.1(a) note.

### 1.2 Tier B — shared substrate the old lane also uses — RULED 2026-09-09

**Founder ruling (2026-09-09, per family, recorded verbatim in intent):** every family below is
either *dropped with the old lane in Phase 6* or *kept as substrate*. There is no open item left in
Tier B. The two checks the ruling asked for were run against the code (`grep -rl <table>` over
`platform/ subsystems/ tests/`, minus `alembic/`) and the worktree DB; their findings changed the
disposition of eight tables that this inventory had misfiled as old-lane singletons — they belong to
platform subsystems that never went through the old research lane.

| family | tables | ruling | why |
|---|---|---|---|
| **Verification / eval** | `faithfulness_verdict`, `entailment_verdict`, `conflict_flag`, `identity_binding_eval`, `golden_fixture`, `eval_run`, `judge_policy`, `binding_policy`, `cadence_policy`, `re_research_candidate` | **DROP** | Master plan §2: judgment annotates, never vetoes. D1 replaced this with the marker flags on the claim (`write_markers`). A future fuzzy-verbatim check is a marker, not these tables. |
| **Coverage** | `coverage_attempt`, `coverage_decision`, `coverage_evaluator_advice` | **DROP** | R2 keeps its own finalization JSON on `arv2_research_job`. |
| **Economics / governance** | `gate_decision`, `pre_spend_policy`, `cost_estimate`, `budget_event`, `adjustment_journal`, `millicredit_rate`, `source_yield`, `source_call_observation`, `effective_field_source_plan`, `positioning_policy`, `config_revision` | **DROP** | ARV2's money truth is `provider_call_ledger` plus the run/job cost columns; caps only record. |
| **Compliance** | `dsar_tombstone`, `use_decision`, `lawful_basis_record`, `outreach_objected`, `evidence_access_audit` | **KEEP** (Tier C) | The DSAR floor (D10) applies to ARV2's claims. Already on the §4 survive list. |
| **Claim-store rings** | `claim_support`, `claim_derivation`, `field_definition_revision`, `disposition`, `disposition_provenance`, `identity_disposition`, `identity_review_task` | **KEEP** (Tier C) | Part of the claim store / identity substrate, not the lane. |
| **Discovery lane** | the 17 `discovery_*` tables (0 rows) | **DROP** | Webset/batch/seal-shaped schema for the old Exa-websets import. R4 (signal-first search, qualifier probe, cohort approval, fan-out) defines its own rows on the R2 pattern; it must not bridge to these. |
| **Official-site crawler** | the 10 `official_site_*` tables (378 rows) | **DROP** | Stage-0's own-site scrape lane; onboarding (R1) stores company knowledge as `brand_knowledge_document` markdown. Same fate as §1.1(e). |
| **External research / targeted enrichment / contact channels** | `external_research_*` (9), `targeted_enrichment_*` (5), `contact_channel_artifact`, `contact_channel_operation`, `contact_channel_operation_stop`, `contact_channel_reuse` | **DROP** | Old-lane enrichment and channel operations. `contact_channel_suppression` is **excluded** — the ARV2 email lookup reads it (Tier C, §4). |
| **Stage-0 / discovery singletons** | `volunteered_statement`, `project_run_discovery_configuration`, `workspace_client_kb_readiness_policy` | **DROP** | Stage-0 interview statements (readers: `stage0_*`, `statement_evidence.py`, `stage0_card_dsar.py`), the old recipe's discovery configuration (`discovery_configuration.py`, `recipe_wiring.py`), and the Stage-0 readiness policy (`stage0/readiness_policy.py`, `stage0/governed.py`). All go with the Stage-0 lane in §1.1(e). `compliance/workspace_erasure.py` names the readiness-policy table — that one reference is unwound in the same step. |

**The two checks the ruling asked for, and what they found:**

| table(s) | check | finding | ruling |
|---|---|---|---|
| `tool_invocation` | "may be the toolbelt's own audit table (platform, keep if so)" | It is. Created by `49911e6aac37_tool_invocation_a9_idempotency_b4_slice_.py`; the only writer is `platform/toolbelt/clue_toolbelt/idempotency.py` (the A9 scoped-idempotency ledger every toolbelt invocation goes through), and the design subsystem's toolbelt (`lumen_api/toolbelt/wiring.py`, `lumen_api/main.py`) depends on it too. 0 rows here only because this worktree never ran a toolbelt turn. | **KEEP** — platform toolbelt. Moved to §4. |
| `review_session`, `review_action` | "the M2.4 identity-review surface the audit note said to leave for an owner" | Confirmed, with a correction: they are the **M13.1 review surface** (`c48ebe0a1e62_m13_1_review_surface_review_session_.py`), owned by `clue_research/review/*` and `clue_api/review/*`, wired at `clue_api/__init__` (`disposition_wiring`, `review_feedback_wiring`) and `fleet_wiring.build_reviewed_phase_handler`. The M2.4 identity review is the sibling `identity_review_task`/`identity_disposition` pair in the claim-store ring. The 2026-08-07 audit note says this machinery is *awaiting an owner, not superseded*. | **KEEP for now, unowned** — not dropped in Phase 6. But it is **coupled to Tier-A/Tier-B drops** (see couplings below), so the Phase-6 plan must unwind two of its reads. |

**Eight tables the inventory had misfiled as old-lane singletons — platform substrate, KEEP:**

- `ingestion_job`, `ingestion_segment` — the platform ingestion engine (`clue_research/ingestion/*`),
  driven today by **brand-kit ingestion in onboarding** (`onboarding_routes.py`, `stage0_setup.py`,
  `projections_app.py` → `brand_kit_ingestion.py`) and the toolbelt's `SubmitIngestionTool` /
  `RetryIngestionTool`. Not the old research lane.
- `supervisor_diagnosis`, `supervisor_observation` — the fleet execution supervisor
  (`platform/execution/clue_execution/{supervisor,controls,views}.py`). Platform execution substrate.
- `account_entity_embedding` (22 rows) — the identity-resolution embedding index
  (`clue_research/identity/{embedding,resolve,review}.py`); `identity.resolve` queries it to match
  accounts. Identity resolution is claim-store substrate and R4's import/dedup will need it.
- `tool_invocation`, `review_session`, `review_action` — per the two checks above.

**Couplings the Phase-6 plan must unwind (Tier-C code that reads a table ruled DROP):**

| Tier-C reader (kept) | reads a table ruled DROP | what the plan does |
|---|---|---|
| `clue_research/claimstore/merge.py` | `conflict_flag` | remove the conflict-flag read; the merge already carries `current_value.conflict` from its own tier comparison (CLAUDE.md [M9.2×M1.2]) |
| `clue_research/compliance/dsar.py` | `faithfulness_verdict` (rationale redaction on erase) | delete the redaction branch with the table — once the table is gone there is no rationale to redact |
| `clue_research/claimstore/faithfulness_attribution.py`, `claimstore/entailment_identity.py` | `faithfulness_verdict` / `entailment_verdict` | delete with the verification family (they exist only to key those verdicts) |
| `clue_api/review/composition.py` | `conflict_flag` (annotation) | drop the annotation; keep the `use_decision` one |
| `clue_research/review/disposition_store.py`, `review/repository.py`, `review/surface.py` | `account_handoff` (Tier A §1.1c) | the kept review surface loses its handoff join; resolve in step 2/3 (stub the read behind the existing seam or make it a typed refusal) — **the plan must state which** |
| `clue_research/narrative/support.py` | `faithfulness_verdict` (M12 citation) | goes with the narrative's C7 reads in step 3 |
| `clue_api/observability_wiring.py`, `clue_api/claim_entailment.py` | verification tables (metrics / entailment) | delete the metric sources with the family; `claim_entailment.py` is Stage-0-owned and goes with §1.1(e) |

Result: **Tier B = 72 tables dropped in Phase 6** (verification 10 + coverage 3 + economics 11 +
discovery 17 + official-site 10 + external/enrichment/channels 18 + Stage-0 singletons 3;
`contact_channel_suppression` is Tier C and never counted) **and 20 kept** (5 compliance + 7
claim-store ring + 8 misfiled platform, `review_session`/`review_action` among the 8). Step 7 of §3
is therefore folded into step 6: **one** reversible migration drops the 83 Tier-A tables **and** the
72 ruled Tier-B tables — 155 tables, leaving 172 of today's 327.

---

## 2. Modules

### 2.1 Named for the lane — 40 files, **29,778 LOC**

`find platform libs subsystems scripts \( -name '*entity_research*' -o -name '*research_view*' \)`

| file | LOC | prod importers | test importers |
|---|---|---|---|
| `platform/api/clue_api/entity_research_tools.py` | 3,040 | 13 | 20 |
| `platform/api/clue_api/account_entity_research.py` | 2,438 | 4 | 15 |
| `platform/api/clue_api/sumble_entity_research_tools.py` | 2,228 | 3 | 9 |
| `platform/fleet/clue_fleet/entity_research.py` | 1,651 | **35** | 45 |
| `platform/api/clue_api/entity_research_parallel.py` | 1,555 | 4 (incl. `fleet_main.py`) | 2 |
| `platform/api/clue_api/contact_entity_research.py` | 1,494 | 5 | 4 |
| `libs/clue-core/clue_core/entity_research.py` | 1,436 | **36** | 45 |
| `platform/agents/clue_agents/entity_research_runtime.py` | 1,299 | 12 | 15 |
| `platform/api/clue_api/exa_entity_research_tools.py` | 1,139 | 1 | 5 |
| `subsystems/research/clue_research/narrative/research_view_recheck.py` | 1,119 | 1 | 1 |
| `subsystems/research/clue_research/narrative/research_view_snapshots.py` | 936 | 2 | 0 |
| `libs/clue-core/clue_core/research_view.py` | 921 | 2 | 0 |
| `platform/api/clue_api/entity_research_launch_tools.py` | 789 | 3 (`fleet_main`, `toolbelt_wiring`, `transactional_account_launch`) | 3 |
| `subsystems/research/clue_research/narrative/research_views.py` | 779 | 3 | 0 |
| `platform/api/clue_api/entity_research_provider_wiring.py` | 743 | 2 (`fleet_main`) | 5 |
| `platform/api/clue_api/research_view_readers.py` | 736 | 3 | 1 |
| `platform/api/clue_api/research_view_api.py` | 672 | 1 (`projections_app`) | 1 |
| `platform/api/clue_api/research_view_governance.py` | 617 | 1 | 2 |
| `platform/api/clue_api/research_view_tools.py` | 551 | 1 (`toolbelt_wiring`) | 1 |
| `platform/api/clue_api/contact_entity_research_channels.py` | 549 | 1 | 2 |
| `platform/agents/clue_agents/account_entity_research.py` | 536 | 5 | 15 |
| `platform/agents/clue_agents/entity_research_contracts.py` | 464 | 11 | 15 |
| `platform/api/clue_api/contact_entity_research_facets.py` | 393 | 1 | 0 |
| `subsystems/research/clue_research/claimstore/research_view_queries.py` | 369 | 1 | 0 |
| `platform/api/clue_api/contact_entity_research_composition.py` | 360 | 2 | 1 |
| `platform/api/clue_api/account_entity_research_composition.py` | 353 | 3 | 11 |
| `platform/api/clue_api/entity_research_runtime_wiring.py` | 289 | 4 | 11 |
| `platform/api/clue_api/research_view_owner_refs.py` | 279 | 3 | 1 |
| `platform/api/clue_api/entity_research_deep_phase.py` | 249 | 1 (`run_composition`) | 6 |
| `platform/api/clue_api/research_view_wiring.py` | 235 | 1 | 2 |
| `platform/api/clue_api/entity_research_verification_resolver.py` | 210 | 2 (`toolbelt_wiring`, `run_composition`) | 2 |
| `platform/api/clue_api/entity_research_fleet_composition.py` | 198 | 1 | 2 |
| `platform/api/clue_api/research_view_runtime.py` | 196 | 5 (`fleet_main`, `projections_main`, `trial/spine`, …) | 5 |
| `subsystems/research/clue_research/claimstore/research_view_routes.py` | 189 | 3 | 0 |
| `platform/agents/clue_agents/contact_entity_research.py` | 168 | 6 | 4 |
| `platform/projections/clue_projections/research_views.py` | 155 | 3 | 0 |
| `platform/api/clue_api/entity_research_quarantine.py` | 143 | 3 | 5 |
| `scripts/07_research_view_trial.py` | 122 | 0 | 0 |
| `libs/clue-core/clue_core/research_view_species.py` | 108 | 2 | 0 |
| `platform/agents/clue_agents/entity_research_tools.py` | 70 | 14 | 20 |

**The two hubs** — `libs/clue-core/clue_core/entity_research.py` (36 prod importers) and
`platform/fleet/clue_fleet/entity_research.py` (35) — are the contract/protocol layer everything
else in this table imports. They go **last**, not first.

**The four bindings into live entrypoints** (these are the ones that make deletion a real change,
not a file removal):

| binder | binds what | flag |
|---|---|---|
| `fleet_main.py` | `entity_research_parallel`, `entity_research_provider_wiring`, `entity_research_launch_tools`, `research_view_runtime` | `entity_research_runtime_enabled` (default **False**) |
| `toolbelt_wiring.py` | `entity_research_launch_tools`, `entity_research_verification_resolver`, `research_view_tools`, `coverage_tools`, `independent_contact_research`, `entity_research_quarantine` | per-tool authority + the quarantine fence |
| `run_composition.py` | `entity_research_deep_phase` (the DEEP slot; Lane-F R11 bridge), `entity_research_verification_resolver`, `contact_eligibility` | — |
| `projections_app.py` / `projections_main.py` | `research_view_api` (11 routes), `research_view_owner_refs`, `research_view_runtime` | six `c7_*` flags, **all default False**; `c7_legacy_dossier_alias_enabled` gates the three `/dossier` aliases |

### 2.2 Behind the M8D R1 quarantine (~8,500 LOC in `platform/`)

Per `_memory/2026-08-07-dead-code-stale-endpoint-audit.md`: the quarantined inner tools are **still
fully constructed** at `toolbelt_wiring` with all their collaborators, then wrapped in a
never-delegating shell. *That construction is why these trees cannot be deleted piecemeal* — the
stub step in §3 exists precisely to break it.

| tree | LOC | prod importers |
|---|---|---|
| `platform/api/clue_api/deep/` (9 modules: `orchestrator`, `handler`, `composition`, `run_io`, `spend`, `committee_preparation`, `handoff_skeleton`, …) | 2,710 | via `entity_research_quarantine`, `toolbelt_wiring` |
| `platform/api/clue_api/contact_research_preparation.py` | 873 | 2 (`deep/orchestrator`, `independent_contact_research`) |
| `platform/api/clue_api/contact_eligibility.py` | 730 | 6 (`research_view_readers`, `value_narrative_tools`, `contact_content_handoff`, `run_composition`, `research_view_owner_refs`, `__init__`) |
| `platform/api/clue_api/account_research_turn_wiring.py` | 704 | 3 (`conversation_turns`, `onboarding_synthesis_wiring`, `__init__`) — **partially re-pointed, see §2.5** |
| `platform/api/clue_api/account_research_wiring.py` | 592 | 5 |
| `platform/api/clue_api/sumble_mcp_journal.py` | 535 | **0** |
| `platform/api/clue_api/committee_eligibility.py` | 511 | (M6A discovery — the audit's leave-alone list; **verify before touching**) |
| `platform/api/clue_api/coverage_tools.py` | 461 | 1 (`toolbelt_wiring`) |
| `platform/api/clue_api/sumble_committee_preparation.py` | 378 | 3 |
| `platform/api/clue_api/exa_deep_preparation.py` | 326 | **0** |
| `platform/api/clue_api/handoff_app.py` | 212 | 1 (`clue_api/__init__.py` re-export only — **no entrypoint builds it**; M12.3, fully orphaned since the 2026-08-07 audit) |
| `platform/api/clue_api/independent_contact_research.py` | 180 | 1 (`toolbelt_wiring`) |
| `platform/api/clue_api/sumble_committee_launch.py` | 75 | 1 |
| `platform/api/clue_api/sumble_committee_wake.py` | 52 | **0** |

Plus the `clue_research` M7/M8 account-axis cluster named in the audit note (~30 modules:
`profiling/account|aspect_worker|resonance`, `durable/graph|workers|scheduler|planning|recursion|spans`,
the coverage controller/judge + ledger writers) — **not re-measured here**; the audit note is the
inventory for that half and should be re-run at Phase-6 planning time, because `durable/` also owns
the project-run state machine, which is *not* obviously legacy.

### 2.3 The `/dossier` aliases

Three C7.7 deprecated alias routes in `research_view_api.py`, gated by
`c7_legacy_dossier_alias_enabled` (default **False**). They go with `research_view_api.py`. Other
`dossier` grep hits (`arv2/account_research_tools.py`, `arv2/exa_client.py`,
`arv2/structuring_client.py`) are **ARV2's own vocabulary**, unrelated — do not sweep by keyword.

### 2.4 Sumble lineage

`sumble_mcp_journal.py` (535, 0 importers) and `sumble_committee_wake.py` (52, 0 importers) are the
superseded MCP-era lineage — free deletions, no stub needed. `sumble_entity_research_tools.py`
(2,228) and `sumble_committee_preparation.py`/`_launch.py` are live-shaped code behind the
quarantine; they follow the §3 order. `sumble_account_gaps.py` / `sumble_committee_inputs.py` /
`sumble_committee_source.py` are on the audit's **leave-alone** list (M6A discovery) — re-verify
before including them.

### 2.5 `account_research_turn_wiring.py` — what D4-b changed and what remains

D4-b Task 5 re-pointed **one** thing: `DbCompiledContextCardReader` no longer serialises the FI-2
`ContactProfile` as the agent's context card; it now calls
`clue_api.arv2.display.gather.resolve_subject` and compiles a minimal typed card
(name/title/persona/account) — `account_research_turn_wiring.py:44`.

**What remains legacy in that file:** the whole account-research turn still reads and asserts against
the old lane's `account_run` row (`get_account_run` at line 74/661; `account_run.research_directive`,
`.status`, `.tier`, `.project_run_id`, `.entity_id` at 380/460/672–674; the turn id is
`uuid5(_TURN_NAMESPACE, str(account_run_id))` at 532). So the module is **not** an ARV2 module with a
legacy tail — it is a legacy module with one ARV2 call. Phase 6 must either delete it with the lane
or give the production turn an ARV2-native run row; that is a decision, not a mechanical edit.

### 2.6 Tests that cover only the lane

17 files, **19,419 LOC** (`find tests -name '*entity_research*' -o -name '*research_view*' -o -name '*fi2*'`):
`tests/api/test_account_entity_research_r5_db.py` (2,570), `test_entity_research_tools_r4_db.py`
(1,690), `tests/integration/test_fi2_slice3_economics.py` (1,465), `tests/agents/test_entity_research_runtime_r3.py`
(1,389), `tests/narrative/test_research_views.py` (1,201), `tests/api/test_account_entity_research_fresh_skip_db.py`
(1,149), `test_contact_entity_research_r8_db.py` (1,141), `test_entity_research_parallel_r9_db.py` (1,010),
`tests/narrative/test_research_view_recheck.py` (746), `tests/agents/test_entity_research_tools_r4.py` (671),
`tests/api/test_fi2_63_sumble_freshness_db.py` (657), `tests/unit/core/test_research_view_contracts.py` (596),
`tests/narrative/test_research_view_snapshots.py` (557), `tests/api/test_c7_research_view_serving.py` (505),
`test_entity_research_cutover_r10.py` (495), `tests/integration/test_fi2_slice0_two_projects.py` (484),
`tests/unit/core/test_research_view_fixtures.py` (458), plus `tests/fleet/test_entity_research_r2*`,
`tests/api/test_m8d_r1_entity_research_quarantine.py` (183), `tests/architecture/test_research_view_species.py` (168),
`tests/api/test_fi2_62_*` (813 across 3). Fixture trees: `tests/fixtures/entity_research/`,
`tests/fixtures/research_views/`.

Two of these are **already reported red on this branch and attributed as pre-existing**:
`tests/api/test_lane_d4_option_b_acceptance_db.py` ×2 (old-lane discovery-seal validation; reproduce
identically at the merged base). They are the strongest single argument for deleting the lane rather
than repairing it.

---

## 3. Proposed deletion order

Per the CLAUDE.md audit note's ruling ("replace the quarantined inner tools with descriptor-only
stubs at `toolbelt_wiring`, then delete the implementation trees") and the founder's trigger
condition, which **has now been met** (the design-integration branch is merged; the ARV2 runtime is
exercised in anger — the worktree DB carries a real ARV2 run/job).

Each step is its own commit; the gate after each step is `uv run mypy`, `uv run lint-imports`,
`uv run pytest tests/api tests/arv2 tests/claimstore tests/db`, and `apps/frontend` untouched.

| # | step | blast radius | gate |
|---|---|---|---|
| **0** | **Free deletions.** `sumble_mcp_journal.py`, `sumble_committee_wake.py`, `exa_deep_preparation.py`, `scripts/07_research_view_trial.py`, `handoff_app.py` + its `clue_api/__init__` re-export. | 0 prod importers each (handoff_app: re-export only) | import + mypy |
| **1** | **Stub the quarantined inner tools at `toolbelt_wiring`.** Replace each of the 9 replay-only tool addresses with a descriptor-only stub so the collaborator graph stops being constructed. Nothing else changes. | `toolbelt_wiring.py`, `entity_research_quarantine.py`, `deep/composition.py`, `agent_registry_wiring.py` | `tests/api/test_m8d_r1_entity_research_quarantine.py` must still prove replay-by-descriptor; `tests/agents` green |
| **2** | **Delete the now-unreachable implementation trees.** `clue_api/deep/` (2,710), `contact_research_preparation.py`, `independent_contact_research.py`, `coverage_tools.py`, `account_research_wiring.py`, `sumble_committee_preparation/_launch.py`, `exa_deep_materialization.py`, and the `clue_research` M7/M8 account-axis cluster from the audit note. | ~6 kLOC + ~30 clue_research modules | full `make check` minus the live suites |
| **3** | **Unbind and delete C7.** `projections_app`/`projections_main` stop registering `research_view_api`; delete `research_view_{api,readers,governance,owner_refs,runtime,tools,wiring}.py`, `clue_research/{claimstore/research_view_*,narrative/research_view*,narrative/research_views}.py`, `clue_projections/research_views.py`, `clue_core/research_view{,_species}.py`, the `/dossier` aliases, and retire the six `c7_*` flags from `settings.py` + `.env.example` (**env-parity rule**). `contact_eligibility.py` goes here (its importers are all C7). | ~6.5 kLOC; `projections_main` route table shrinks by 14 routes | `tests/api/test_c7_research_view_serving.py`, `tests/narrative/*research_view*`, `tests/unit/core/test_research_view_*` **deleted with it**; projections app boots |
| **4** | **Unbind and delete M8D.** `fleet_main` stops binding `entity_research_parallel` / `_provider_wiring` / `_launch_tools`; `run_composition` DEEP slot and `entity_research_verification_resolver` resolved (**decision required** — the Lane-F R11 bridge lives here; either delete the DEEP phase with the lane or leave the phase machine a typed refusal). Then delete the 40-file `*entity_research*` set, hubs last (`clue_fleet/entity_research.py`, `clue_core/entity_research.py`), and retire `entity_research_runtime_enabled` + the provider flags. | ~30 kLOC, 36+35 importers unwound from the leaves inward | `tests/fleet`, `tests/agents`, `tests/api` green; the 19.4 kLOC of legacy-only tests deleted in the same commit |
| **5** | **Decide `account_research_turn_wiring.py` / the production turn (§2.5).** Either delete with step 4, or give the turn an ARV2-native run row. **Blocks step 6** — this is the last `account_run` writer that is not itself legacy. | `conversation_turns.py`, `onboarding_synthesis_wiring.py` | the production-turn suites |
| **6** | **Drop the tables: ONE reversible migration** off the then-head. All 83 Tier-A tables in `1.1(a)–(e)`, dropped children-first, with a hand-written `downgrade()` that recreates every table, CHECK, index and enum (repo convention: hash revision id, single head, `make db-smoke` on a clean throwaway DB is the gate). Enums retired in the same migration. **Do not touch `provider_call_ledger.entity_research_job_id`.** | the DB | `alembic heads` = 1; `make db-smoke` up→down→up on a **clean** DB; `tests/db` green |
| **7** | ~~Tier B ruling + sweep — a separate PR~~ **RULED 2026-09-09 and folded into step 6:** the 72 Tier-B tables ruled DROP in §1.2 go in the same migration as the 83 Tier-A tables, and the §1.2 couplings table is unwound in steps 2–3 before the drop. No separate PR. | the DB | as step 6 |

**Gates that must not move:** `tests/api/test_frontend_read_arv2_only_guard.py` (its allowlist is
now empty — it must stay empty), `tests/arv2/test_import_guard.py`, `uv run lint-imports` (26/0),
one Alembic head, and the Zafran walk `tests/api/test_frontend_read_v1_live_zafran_db.py`.

**Sequencing constraint:** steps 1→2→3→4 must be separate commits in that order. Deleting a tree
before stubbing its construction site produces an import error at composition, not a test failure —
the check gate will catch it, but the diff becomes unreviewable.

---

## 4. NOT legacy — the survive list

The tables below are the ones the ARV2 path (`clue_api/arv2` + `clue_api/frontend_read`) actually
touches (38 of them), plus the substrate they sit on. **None of them may be dropped in Phase 6.**

- **ARV2's own rows:** `arv2_research_run`, `arv2_research_job`, `arv2_claim_annotation`,
  `provider_call_ledger` (**including** its `entity_research_job_id` column).
- **The claim store (D1 / the core architectural bet):** `claim`, `claim_support`,
  `claim_derivation`, `field_definition`, `field_definition_revision`, `pack`,
  `workspace_field_definition`, `workspace_field_retirement`, `workspace_field_materialization`,
  `source_manifest`, `source_manifest_revision`, `source_profile`.
- **The display module (D1/D3):** `display_block`, `display_section_recipe`,
  `account_activity_event`.
- **The spine:** `workspace`, `workspace_membership`, `workspace_invitation`, `workspace_policy`,
  `workspace_client_binding`, `brand`, `product`, `product_catalog_lineage`,
  `product_context_version`, `project`, `project_account`, `project_product`, `project_run`,
  `project_phase_checkpoint`, `platform_user`, `auth_identity`, `account_entity`, `contact_entity`,
  `run_lineage`.
- **Onboarding (R1):** `onboarding_run`, `onboarding_step`, `onboarding_input`,
  `onboarding_product_lineage`, `brand_knowledge_document`, `self_serve_provisioning`.
- **The read surface's own tables:** `contact_email_lookup`, `contact_email_lookup_artifact`,
  `contact_email_lookup_provider`, `contact_channel_suppression`, `frontend_bulk_action_operation`,
  `frontend_bulk_action_item`.
- **Artifacts / storage:** `artifact`.
- **Platform substrate the Tier-B ruling confirmed (§1.2 checks):** `tool_invocation` (toolbelt A9
  ledger), `ingestion_job`, `ingestion_segment` (brand-kit ingestion), `supervisor_diagnosis`,
  `supervisor_observation` (execution supervisor), `account_entity_embedding` (identity resolution),
  `review_session`, `review_action` (M13.1 review surface — kept unowned), plus the claim-store ring
  `disposition`, `disposition_provenance`, `identity_disposition`, `identity_review_task`.
- **Compliance (DSAR-bearing):** `dsar_tombstone`, `use_decision`, `lawful_basis_record`,
  `outreach_objected`, `evidence_access_audit`,
  `workspace_dynamic_client_kb_erasure`, `workspace_dynamic_client_kb_claim_erasure`.
- **Shared platform runtime (design, agents, execution, fleet):** all `design_*` (33), all `agent_*`
  (38), all `execution*` (9), `memory*` (6), `recipe`/`recipe_revision`/`recipe_revision_event`,
  `run_event`, `run_control_event`, `work_lease`, `fleet_task`, `idempotency_ledger`,
  `stream_token`, `checkpoints` + `checkpoint_{blobs,writes,migrations}`, `alembic_version`.

**Also not legacy, and explicitly out of scope for a keyword sweep:** the word "dossier" inside the
ARV2 clients (§2.3), and the substring `entity_research_job_id` on `provider_call_ledger` (§1.1a).
