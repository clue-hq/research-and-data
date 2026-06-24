# 2026-06-24 — M12.2 (account_handoff assembler + provenance index) + 2 backlog items — plan

**Branch:** `m12/value-narrative` (pushed; upstream set). Base `1902210` (= `integration/phase3-preflight`),
M12.1 done at `eb972cf`, alembic head **`a3f352f32954`** (M12.1's `claim_support`+`positioning_policy`).
Spec: `docs/specs/M12-value-narrative-and-handoff.md` §M12.2. Pre-flight: `docs/specs/_phase3-preflight.md`.
Pause after M12.2 (per instruction).

## STATUS — implemented + green (audit running) 2026-06-24
Alembic head now **`9666e86a6e9a`** (chain `a3f352f32954` → `11299b862da3` answering_model →
`9666e86a6e9a` account_handoff). Gate green: ruff (src+tests), `ruff format --check`, **mypy 219 files**,
**import-linter 11/11** (narrative import-clean; core stays claimstore-free), **db-smoke** up→base→up single
head. Affected DB suites pass on rome DB (55030): narrative (incl. 13 new `test_handoff`), claimstore,
verification, identity, discovery_scoring, api, merge-policy. **Backlog A/B + M12.2 are DONE.**

NOTE on the full-suite run: `tests/db/test_db_migrations.py::test_no_domain_tables_at_m0_head` +
2 field_registry tests FAIL only when the WHOLE suite runs in one session against the shared rome DB —
LangGraph's `checkpoint*` tables (created at runtime by the M7/M8A durable tests, NOT alembic-managed)
linger and `test_no_domain_tables` sees them at the M0 head. **Pre-existing shared-DB pollution, NOT a
defect in this change** — drop the 4 `checkpoint*` tables + `alembic upgrade head` and all 17 pass.

Change surface (working tree): `core/equality.py`(new), `core/__init__`, `claimstore/{merge,claims,__init__}`,
`verification/{corroboration,faithfulness,__init__}`, `identity/review`, `narrative/{handoff,handoff_seams,
handoff_store,support,__init__}`(handoff* new), `api/narrative_wiring`, migration `b3b…` docstring,
2 new migrations, tests `{test_merge_policy, test_corroboration, test_faithfulness, narrative/test_handoff}`.

## Scope of THIS work (user instruction)
1. **M12.2** — the deterministic `account_handoff` assembler + provenance index.
2. **Backlog A** — `[M9.3×M12] faithfulness_verdict.answering_model` (M12.2 provenance cites the answering judge model).
3. **Backlog B** — `[M9.2×M1.2] merge conflict-equality` (M12.2 `field_conflicts` is mode-aware, not over-flagging).

### Cross-cutting note (surface to integration owner)
Pre-flight `_phase3-preflight.md` line 207 nominally deferred the **EqualityMode relocation** to a
"post-integration cleanup PR by the integration owner — NOT a feature branch", and WS-C (M12) ownership
says "must not touch `merge.py`". The user **explicitly** asked to implement both backlog items now (they
are the prerequisites the CLAUDE.md backlog says "must land before M12 consumes conflict signals / the
provenance"). Doing them on `m12/value-narrative` is collision-safe: **neither M10 nor M11 touches `core`
EqualityMode, `claimstore/merge.py`, `verification/corroboration.py`, or `faithfulness_verdict`**, and M12
integrates LAST (M11→M10→M12), so the merge is clean. Recorded here so the integration owner knows the m12
branch carries these M1.2/core cross-cutting changes.

## The contract (already frozen in `core` by PF-1 — DO NOT edit core/handoff.py)
`core.handoff.AccountHandoff` IS conventions §4 verbatim. M12.2 POPULATES it:
- `account_entity_id`
- `fit_score`, `intent_score` : `core.handoff.Score{value, components[ScoreComponent{name,weight,value,evidence_claim_ids}]}`
- `account_profile_claims[]` : `ProfileClaimView{claim_id, value_json, evidence_span, source_tier}` (account → no binding/use_class)
- `committee[]` : `CommitteeMember{contact_entity_id, persona, role_on_committee, profile_claims[ProfileClaimView{..,identity_binding,use_class}]}`
- `value_narrative[]` : `ValueNarrativeItem{claim_id, persona, argument, supporting{account_evidence_ids[], client_knowledge_ids[]}}`
- `provenance_index` : `dict[str(claim_id) -> ProvenanceRef{source_url, source_tier, evidence_span}]`
- PF-1 additive stamps M12.2 SETS: `icp_spec_version`, `campaign_run_id`, `assembled_at`, `coverage_confidence`, `field_conflicts{field_key -> (claim_id,...)}`.

## Substrate facts (verified by reading code)
- **Scores** live as tenant-private claims `account.scoring.fit` / `account.scoring.intent`
  (`discovery_scoring/scoring/engine.py` FIT_FIELD/INTENT_FIELD). `value_json` = `Score.model_dump(mode="json")`
  (`{value, components:[{name,weight,value,evidence_claim_ids}]}`) + extras `rubric_version, non_fit_flag,
  fit_floor, icp_key, icp_version` (intent has no fit_floor/non_fit_flag). Read via `current_value(...,scope)`;
  reconstruct `Score` from the dump; surface `non_fit_flag` (D6) — carry on a small M12.2 wrapper / the handoff
  (NOTE: `AccountHandoff` has no explicit non_fit slot; carry it via the fit-score claim being present + a
  field_conflicts-style note OR document it travels in the fit-score claim's value_json provenance. Decide in impl.)
- **Account profile claims (Output 2)** = verified `current_values` of `account.*` fields EXCLUDING
  `account.scoring.*` and `account.value_narrative`. Enumerate generically from the registered field set /
  ICP `field_keys` (no hardcode). `current_value` already excludes unverified-tier4 / rejected / weak-binding
  / superseded / tombstoned (post-M10.5) — so "verified-only" + "rejected excluded" (M13.1 AC) are FREE.
- **Committee (Output 3)** maps to `core.handoff.CommitteeMember` already (`profiling/committee/results.py
  ::as_committee_member`, `contact/results.py` builds `ProfileClaimView` with identity_binding+use_class).
  M8A.5 `api/deep/handoff_skeleton.build_handoff_skeleton(result)` JOINs them per-run. But M12.2 is a PURE
  STORE READ → committee + the per-claim M10 `use_decision` arrive via an **injected seam** (narrative can't
  import profiling/compliance). Production impl = api root (reads profiling committee/contact + M10 use_decision).
- **identity_binding/use_class** are columns on `core.Claim` (claim.py:120-121); outreach-eligibility =
  `core.is_outreach_promotable(claim, use_decision)` (STRONG binding AND `decision.usable_for_outreach`).
- **value_narrative (Output 4)** = live `account.value_narrative` claims (M12.1) + `claim_support` rows
  (`narrative/support.read_claim_support`). value_json carries `{persona, argument, angle_label, icp_spec_version}`.
- **provenance_index**: no batch-claims-by-id reader exists in claimstore today (`claims_for` is by
  entity+field). ADD a claimstore helper `claims_by_ids(conn, ids, *, scope)` (one `WHERE id IN :ids` over
  `_SELECT_COLUMNS`) → resolve any claim_id → ProvenanceRef. Build-fail if a value's claim_id can't resolve.
- **field_conflicts**: `current_value.conflict` + `.conflicting_claim_ids` (from `merge._conflict`). Backlog B
  makes these mode-aware.
- **coverage_confidence**: read M6.5 coverage estimate if present (claim/where?), else None; the M12.1
  thin-narrative coverage gap = a committee persona with no live narrative claim (derived in the assembler).

## M12.2 files (under `src/clue_research/narrative/`)
- `handoff_seams.py` — `HandoffCommitteeReader` Protocol → `committee_for_handoff(account_entity_id, tenant_id)
  -> tuple[HandoffCommitteeMember,...]` where each carries the `core.handoff.CommitteeMember` + a
  `dict[claim_id -> UseDecision]` (so the assembler marks outreach-eligibility / excludes weak+disallowed from
  the eligible set). In-memory fake for tests. (Reuse `narrative.seams` style.)
  - DECISION: keep separate from M12.1 `CommitteeReader` (that one returns use-cleared facet hooks for the
    PROMPT; this returns the FULL committee w/ all profile_claims + governance for the HANDOFF). One api-root
    class can implement both protocols.
- `handoff.py` — `HandoffAssembler` + `assemble(conn, account_entity_id, *, icp_spec_version, client_id,
  campaign_run_id=None, ...) -> AccountHandoff`. PURE deterministic, NO LLM, NO synthesis. Steps:
  1. scope = TenantScope.for_tenant(client_id).
  2. read fit/intent score claims (current_value) → Score + non_fit_flag.
  3. read account.* profile fields (registered set minus scoring/value_narrative) via current_values → ProfileClaimView[].
  4. committee via injected HandoffCommitteeReader → CommitteeMember[] w/ ProfileClaimView profile_claims;
     mark/segregate outreach-eligible via is_outreach_promotable.
  5. value_narrative: live account.value_narrative claims (filter value_json.icp_spec_version) + claim_support → ValueNarrativeItem[].
  6. provenance_index: union of every claim_id appearing anywhere (score component evidence_claim_ids, profile
     claim ids, committee profile claim ids, narrative claim ids, AND narrative supporting account_evidence_ids)
     → claims_by_ids → ProvenanceRef. Build-fail on unresolved.
  7. field_conflicts from the account-profile current_values that have `.conflict`.
  8. coverage_confidence (M6.5 if available else None). Stamp icp_spec_version/campaign_run_id/assembled_at.
- `handoff_store.py` — materialize-on-assembly: `account_handoff` table (JSONB payload + key cols
  account_entity_id, icp_spec_version, campaign_run_id, assembled_at, content_hash). `write_handoff` /
  `read_handoff`. Recompute on supersede = re-assemble + upsert (idempotent on (account, icp)). Postgres only.
- `__init__.py` exports; `api/narrative_wiring.py` constructs the assembler + the production
  HandoffCommitteeReader (deferred/integration where it needs profiling+M10; in-memory/store reader otherwise).

Migration `<hash>_m12_2_account_handoff_table.py` (down_revision = `a3f352f32954`): create `account_handoff`
(materialization), UNIQUE(account_entity_id, icp_spec_version) [campaign_run scope? — store icp+account as the
M12.2 scope key per spec; campaign_run_id is a stamp, not the key]. Reversible.

## Backlog A — faithfulness_verdict.answering_model
- Migration `<hash>_m9_3_answering_model.py` (down_revision = the M12.2 table migration OR a3f352f32954 — chain
  cleanly): `ALTER TABLE faithfulness_verdict ADD COLUMN answering_model text` (nullable — back-compat for
  existing rows; new rows fill it). downgrade DROP COLUMN.
- `verification/faithfulness.py`: `_compute_verdict` already has `completion` — return `completion.model`
  (the ANSWERING model) alongside parsed/cost/latency. Thread to `_persist` → `_insert_verdict` (new
  `answering_model` param) → INSERT the column. Keep `judge_model` (REQUESTED) as the cache key (unchanged).
  Optionally surface on the span. `JudgeResult` (frozen core) UNCHANGED — answering_model rides the row only.
  `_load_cached` may additionally SELECT answering_model (informational; not required for cache identity).
- M12.2 reads it: for each value_narrative claim, read its latest `faithfulness_verdict` row →
  `answering_model` (fallback `judge_model`) for the "judged faithful by <model>" provenance citation. Since
  narrative can't import verification, add a tiny reader: EITHER a `verification`-package public reader OR
  M12.2 reads `faithfulness_verdict` directly via SQL in `narrative/handoff.py` (it's a side table, like
  claim_support; reading it is not importing the verification PACKAGE). PREFER: M12.2 reads the row directly
  (a `read_faithfulness_citation(conn, claim_id)` in narrative) — consistent with how it reads claim_support.
  The ProvenanceRef for a narrative claim still carries source_url/tier/span; the judge-model citation goes in
  the narrative's provenance entry (ProvenanceRef has no model slot — core frozen). DECISION: carry the
  judged-by-model in the narrative ProvenanceRef.source_url? No. Put it where? `ProvenanceRef{source_url,
  source_tier, evidence_span}` only. So the judge-model citation can't live in ProvenanceRef without a core
  edit. OPTIONS: (a) accept that the provenance_index entry for a narrative claim cites source_url=
  clue://narrative/positioning + tier4 + span, and the answering_model is exposed via a SEPARATE M12.2 surface
  (the materialized handoff payload can carry a `narrative_judge_models` map keyed by claim_id — additive, not
  in the frozen AccountHandoff). RE-EXAMINE in impl: the spec says provenance entry has
  `extraction_method, observed_at, collected_at, corroborations, confidence` too — but core.ProvenanceRef is
  the SLIMMER frozen shape (source_url, source_tier, evidence_span). The richer per-claim provenance the spec
  lists is the `WinningProvenance`/claim row. So M12.2's provenance_index uses the frozen ProvenanceRef; the
  answering_model citation is an M12.2-materialized extra, NOT a core change. CONFIRM no core edit.

## Backlog B — merge conflict-equality (relocate EqualityMode + values_agree to core)
- NEW `core/equality.py`: `canonical_json(value)` (moved from claimstore.merge — the one canonical-equality
  primitive), `EqualityMode` StrEnum (exact/numeric_tol/semantic), tolerance default consts
  (DEFAULT_NUMERIC_REL_TOLERANCE=0.05, _ABS=0.0, DEFAULT_SEMANTIC_JACCARD=0.5), `values_agree(a, b, *, mode,
  numeric_rel_tolerance=.., numeric_abs_tolerance=.., semantic_jaccard_threshold=..)` (no CorroborationPolicy
  dep — explicit tolerances) + private `_as_number/_within_tolerance/_tokens`. Export from `core/__init__.py`.
  (Also re-export `EqualityMode` from `core` if put in enums; simpler: keep all in equality.py, export via core.)
- `claimstore/merge.py`: import `canonical_json, EqualityMode, values_agree` from core; DELETE local
  `canonical_json` def but KEEP re-exporting it (so `from clue_research.claimstore import canonical_json`
  still works). Add tolerance fields to `MergePolicy` (default from core consts). Thread `equality_mode` into
  `merge_claims(..., equality_mode=EqualityMode.EXACT)` like `freshness_ttl`; read it in `current_value` /
  `current_values` via a new `_equality_mode`/`_equality_modes` (or extend the freshness reads to one SELECT
  of `freshness_ttl, equality_mode`). `_conflict` groups contenders with `core.values_agree(..., mode=
  equality_mode, tolerances from policy)` instead of `canonical_json` exact. `provenance_index` (the merge
  one) unaffected.
- `verification/corroboration.py`: import `EqualityMode, values_agree, canonical_json` from core; DELETE local
  copies; update call sites to pass `policy.numeric_rel_tolerance` etc. Keep `from clue_research.verification
  import EqualityMode` working (re-export). `CorroborationPolicy` UNCHANGED (keeps its literals); add a
  no-DB drift guard test (MergePolicy tolerances == CorroborationPolicy == core consts), mirroring the
  existing `test_conflict_tier_threshold_aligns_across_policies`.
- `registry.get_corroboration_config` already reads `equality_mode` (string). The merge reads the same column.
- DB enum `equality_mode` parity: if a parity test exists vs verification.EqualityMode, repoint to core.
- Test: numeric_tol field with two authoritative tier≤2 sources that AGREE under tolerance (1000 vs 1024) →
  NO conflict (was over-flagged before); two that DISAGREE (1000 vs 2000) → conflict. Same for semantic.

## Migration chain (m12 branch, off a3f352f32954)
Pick ONE order; reversible each; single head; db-smoke. Likely:
`a3f352f32954` → `m12_2_account_handoff` → `m9_3_answering_model`. (Backlog B = NO migration — pure code
reading the existing `field_definition.equality_mode` column.)

## AC mapping (M12.2 spec)
AC1 validates+5 sections · AC2 every value→resolvable provenance (build-fail on dangling) · AC3 scores
decomposed w/ claim ids · AC4 committee carries identity_binding+use_class; weak/sensitive absent from
outreach-eligible · AC5 pure&deterministic (two assembles equal; no LLM) · AC6 conflict+low-coverage flags
propagate (planted tier≤2 conflict) · AC7 import non-fit flag travels w/ fit · AC8 re-assemble after supersede
reflects new truth + new assembled_at · AC9 (account,icp) scope → two ICPs = two handoffs.

## Gate
ruff/format, mypy, import-linter (narrative stays import-clean; core gains equality module; verification +
claimstore repoint to core — all allowed), pytest against Postgres (rome DB 55030 / the configured DSN).
db-smoke up→down→up single head. Then audit (multi-agent), fix, commit, PAUSE.
