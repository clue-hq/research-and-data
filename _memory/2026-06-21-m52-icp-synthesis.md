# 2026-06-21 — M5.2 ICP synthesis & proposal (ENG-107, branch `m5/stage0-front-edge`)

M5.1 pushed to origin (`c3b44a6`, branch tracks `origin/m5/stage0-front-edge`). Now building M5.2.
Discipline: build → adversarial review → fix → pause. Keep ENG-107 in sync.

## Verified contracts (read from the real code, not assumed)
- **ICPSpec keyed `(client_id, icp_key, version)` — there is NO `icp_id`.** The spec's
  `ICPSpecRef{icp_id, icp_version}` maps to `ICPSpecRef{client_id, icp_key, icp_version}` here.
- **M3 compiler is importable from stage0.** import-linter: each milestone pkg may import the M1–M4
  services (`claimstore/identity/icp/sources`) freely; ban is only worker→sibling-worker. So
  `stage0` imports `clue_research.icp` (create_icp_spec, compile_field_plan, diff_icp, rubric +
  source_profile helpers, catalog/packs). It must NOT import gateway/resolvers/adapters/openai or
  any sibling milestone (M6/M7/M8/M9/...).
- **LLMGateway is the injected `core` protocol** (like M5.1's judge). stage0 imports
  `core.LLMGateway/Message/Role/Completion`, never the concrete `clue_research.gateway`.
  `gateway.complete(*, model, messages, **opts) -> Completion` is **sync** (not async). `embed` sync.
- **CampaignPhase.ICP_CONFIRMED = "icp_confirmed"** exists (Beat-0). PhaseContext carries
  `icp_key` + `icp_version`. PhaseHandler is the same frozen seam M5.1 used.
- **core.Estimate** (in core.execution) is the pre-run cost projection value type:
  {discovered_count, projected_deep_count, estimated_cost_cents, cost_per_account_cents, confidence}.
- **create_icp_spec(...)** validates field_keys against registry + enabled_packs against catalog;
  append-only (each call → next version; `activate=True` archives prior active). `created_from`
  must be `ICPCreatedFrom.SYNTHESIS`.
- **compile_field_plan(conn, spec)** → FieldPlan (scoring_fields/deep_fields/public/tenant_private,
  plan_hash). Deterministic per spec version → same plan_hash (reproducibility AC).
- **serve_source_profile(spec)** (M4.6) derives the runtime source profile from `spec.enabled_packs`
  (+ overrides) — NOT from `source_profile_ref` slot. So enabled_packs is the authoritative source
  seam; `source_profile_ref` is provenance/reference metadata only.
- **ScoringRubric** (fit/intent SubRubric of RubricEntry; tier_cutoffs) → `rubric_to_slot()` →
  `scoring_rubric` slot. `validate_rubric(rubric, field_plan)`: every fit+intent entry must be a
  Pass-A **scoring** field in the plan (a deep field as an intent input is rejected).
- **Starter packs**: `frontier_ai` (frontier_ai.arxiv_activity SCORING + account.resonance.research_prestige),
  `healthcare_practice` (healthcare.npi SCORING), `data_infra` (data_infra.migration_signal DEEP).
  Core scoring fields: core.employee_count/primary_domain/work_email/primary_tech_stack,
  account.recent_funding, account.crm_relationship_status. Deep: account.hiring_velocity_eng,
  operational_pain, strategic_moves, resonance.culture, contact.facet.recent_post.
- `list_fields(conn, pass_kind=..., field_class=..., pack=...)` enumerates registry (bounds synthesis).
- `read_client_kb` returns {field_key: value} version-scoped; need claim ids for justifying — add
  `read_client_kb_claims` returning {field_key: Claim/ClaimId} for the pinned version.

## Design (files under src/clue_research/stage0/)
- `icp_fields.py` — `icp.confirm_diff` PACK field (reuse_scope=TENANT_PRIVATE; PACK needs explicit
  scope) + `load_icp_feedback_pack`. Diff persisted **claim-native** on the client entity (no new
  table — Beat-0). `reuse.py` gains `ICP_REUSE_POLICY` (DEFAULT + `icp.` prefix).
- `icp_types.py` — ICPProposal (6 elements, each w/ justifying_claim_ids), ICPProposalEdits,
  ICPProposalDiff, ICPSpecRef{client_id,icp_key,icp_version}, ICPConfirmation{ref,diff,estimate}.
- `icp_synthesis.py` — `synthesize_icps(conn, client_kb_ref, *, client_id, gateway=None, model=...)`
  → list[ICPProposal]. LLM proposes structure bounded to offered packs + registered field keys;
  justifying_claim_ids attached deterministically from the client claims each element drew on
  (LLM never invents claim ids). Deterministic floor when gateway=None / bad JSON (always ≥1
  proposal, all six elements). Robust JSON parse w/ brace-slice fallback.
- `icp_estimate.py` — `estimate_campaign(inputs=DEFAULT) -> core.Estimate` from config priors
  (pre-discovery; confidence low). Placeholder for the injected M7 BudgetEngine.estimate.
- `icp_confirm.py` — `confirm_icp(conn, proposal, edits, *, client_id, ...) -> ICPConfirmation`:
  apply edits → confirmed proposal; diff(proposal, confirmed); pre-validate via in-memory ICPSpec
  + compile_field_plan + validate_rubric; `create_icp_spec(created_from=SYNTHESIS, activate=True)`;
  persist diff claim; estimate. Compiler does field/tier/source mechanics — not authored inline.
- `icp_handler.py` — `IcpConfirmedHandler` (phase=ICP_CONFIRMED) + `icp_confirmed_run_id`. The
  PHASE is a **checkpoint over an already-confirmed spec** (reads pinned (client,icp_key,version),
  compiles, estimates, emits artifact). Pure reads → idempotent, no writes. No spec → FAILED.

## Build status (BUILT, green; under adversarial review)
- New files: `icp_types.py`, `icp_synthesis.py`, `icp_confirm.py`, `icp_estimate.py`,
  `icp_handler.py`, `icp_fields.py`; edits to `client_kb.py` (added `read_client_kb_claims` +
  `_pinned_marker`/`_pinned_field_claims` refactor — DRY), `reuse.py` (`ICP_REUSE_POLICY`),
  `__init__.py` (exports). Tests: `test_icp_synthesis.py`, `test_icp_confirm.py`,
  `test_icp_handler.py`, `test_icp_static.py`; `_fakes.py` (+FakeGateway, +build_client_kb);
  conftest seeds starter packs + icp feedback pack.
- **Verification:** `make check` green (ruff/format/mypy 119 src files/contracts **10/0**/pytest
  **398 passed, 336 skipped** no-DB). Independence contract HOLDS — stage0 imports no sibling
  milestone, never the concrete gateway (injects `core.LLMGateway`). **50/50 stage0 DB tests pass**
  on `clue_m5` (M5.1's 29 + M5.2's 21).
- Design notes that mattered: `serve_source_profile` reads `enabled_packs` (authoritative runtime
  seam), `source_profile_ref` is provenance-only; confirm pre-validates via an in-memory ICPSpec
  (compile + validate_rubric) BEFORE `create_icp_spec` so an invalid spec is never persisted
  (append-only). The `icp_confirmed` PHASE is pure-read (idempotent); the interactive `confirm_icp`
  does the spec+diff writes. Estimate reuses the frozen `core.Estimate`.

## Adversarial review (6 lenses, 14 agents, every finding verified): 8 candidates → 5 confirmed → FIXED
- **MAJOR `_evidence_str` empty-string leak** (icp_synthesis): the list branch returned `value[0]`
  even when `""` (inconsistent with the str branch). An empty `industries:[""]` would pollute the
  spec's `discovery_strategy.firmographic`. Fix: added `and value[0]`.
- **idempotency cluster (3 findings) — confirm_icp now content-idempotent**: a double-clicked /
  retried identical confirm previously appended a duplicate spec version + diff claim, and the
  optional `run_id` param implied an idempotency it didn't deliver. Fix: removed the misleading
  `run_id` param; build the full would-be `draft` ICPSpec (all 5 slots) once; if the **active** spec
  for `(client_id, icp_key)` equals it (`_same_selection` — 5-slot compare; JSON round-trip is
  identity) → return it and **write nothing**. A genuinely *edited* re-confirm differs → appends a
  new version (intended append-only). Added `test_confirm_is_idempotent_on_identical_reconfirm`
  (identical → v1 reused, 1 diff claim; edited → v2). The durable `ICP_CONFIRMED` *phase* was already
  pure-read idempotent (the reviewer slightly conflated the two).
- **atomicity finding (major) — by convention, not a new defect**: confirm's spec-write + diff-write
  rely on the caller's transaction — exactly like `reverse_profile` and `create_icp_spec` itself
  (both docstring'd "Run inside a transaction"). Kept consistent (documented; no one-off
  `in_transaction` assert) — the idempotency check re-reads the committed active spec on retry, so no
  partial-write masking. **No code change** beyond the docstring.
- **Dismissed (3, correctly)**: negative rubric weights ARE caught by `RubricEntry.Weight`
  (`Ge(0.0)`); `icp.confirm_diff` schema `additionalProperties` is fine; "missing idempotency test"
  argued the spec doesn't mandate confirm-idempotency (true — added it anyway as good hygiene).

## Open follow-ups
- M5.4 (seeds) trails M5.2; confirm consumes seeds from the proposal (which the client/M5.4 fill).
  M5.2 accepts seed account_entity_ids in the proposal; it does not run discovery.
- Pre-run estimate is a config-prior placeholder until M7's BudgetEngine is injected.
