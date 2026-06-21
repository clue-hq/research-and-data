# 2026-06-21 — ENG-138 / M6.3: Pass A scoring engine

## Goal
Output 1: a decomposed, explainable, provenance-backed fit + intent score for every admitted
account, computed cheaply + deterministically (tiers 1–3, no LLM). M6.3 is **orchestration over the
substrate** — the scoring math already exists as pure functions in `icp/rubric.py` (M3.4). Branch
`m6/discovery-and-pass-a-scoring`; per-branch DB `clue_m6` (host PG :5432, isolated from the parallel
worktrees' `clue_m5`/`clue_m9`/shared `clue` — separate DB *name*, same server).

## Files (src/clue_research/discovery_scoring/scoring/)
- `config.py` — `ScoringConfig(max_source_tier=3)` + `DEFAULT_SCORING_CONFIG`. The deterministic-first
  guard (config, so a stricter run needs no code change).
- `results.py` — `AccountScore` (account_id, rubric_version, fit/intent `core.Score`, non_fit_flag,
  evidence `{field_key -> claim_ids}`, fit/intent claim ids, cost), `SourceYieldRow`,
  `AccountScoringOutcome` (score + `written` (False=idempotent replay) + yield_steps).
- `engine.py` — the orchestration:
  - `admitted_account_ids(conn, *, run_id, scope)` — enumerate the campaign's admitted accounts via
    their `core.discovery_provenance` claim for the discovery `run_id` (account_entity rows are
    GLOBAL/cross-client, so scoring "all candidates" would be wrong — scope by the discovery run).
    Resolves survivors + dedups.
  - `pass_a_fill_fields(conn, field_plan, rubric, *, max_source_tier)` — the scoring proxies to fill:
    `rubric.field_keys ∩ scoring_fields`, tier-4 sources stripped (the no-LLM guarantee, enforced
    not hoped), outputs (`account.scoring.*`, empty tier_plan) excluded.
  - `score_account(conn, account_id, *, rubric, fill_fields, run_id, client_id, icp_key, icp_version,
    budget_envelope, thresholds)` — fill via `resolve_fields` (tier1-3, idempotent, reuse-stamped) →
    `score_entity` (pure scorer, tenant-scoped) → persist 2 score claims → return `AccountScoringOutcome`.
  - `aggregate_yield(rows)` — fold per-account yield → run's per-(source, field_class) rows.
- `phases.py` — `ScoringPhaseHandler` (phase=SCORING) mirroring `DiscoveryPhaseHandler`:
  load pinned spec (`get_icp_version`) → rubric (`rubric_from_slot`) → `compile_field_plan` →
  `validate_rubric` → `pass_a_fill_fields` → enumerate admitted → per-account `begin_nested` savepoint
  (fault isolation, commit OUTSIDE the try) → `record_source_yield` per source → `PhaseResult`.
  `_scoring_run_id(ctx)` = uuid5("clue:scoring-run:{campaign_run}:{icp_key}:{icp_version}") (distinct
  namespace from discovery).

## Score object persistence
2 FIELD_CLAIMs on the reserved (ENG-165 W4) tenant-private fields `account.scoring.fit` /
`account.scoring.intent` (NOT a new table — packs.py already registers them, value_schema requires a
top-level numeric `value`). `value_json` = `as_fit_score()/as_intent_score().model_dump()` (decomposed
`core.Score` with per-component `evidence_claim_ids`) + rubric_version + non_fit_flag + fit_floor +
icp_key/icp_version. Written at `source_tier=1, extraction_method=HUMAN` (a computed score has no
external URL and is NOT LLM; tier-4⟺llm_synthesis is enforced, so tier-1 + a non-URL method is the
honest fit — see follow-ups). `stamp_reuse(tenant_id=client_id)` before `insert_claim` (fail-closed).

## Idempotency
- `(account, field, tier)` — free from the waterfall (`resolve_fields(idempotent=True)`, keyed
  entity/field/source/run).
- `(account, rubric_version)` — M6.3-owned: dedup on the deterministic `scoring_run_id` (which encodes
  icp_version ⟺ rubric_version, since the rubric rides the icp_spec version). Same run → skip
  (written=False, identical score). New rubric version → new run → **supersede** the prior live score
  (one live winner; append-only history kept).

## Cross-package additive edits (no migration)
1. `icp/rubric.py`: `ScoringRubric.fit_floor: UnitInterval | None = None` — the ICP's Fit floor (D6
   non_fit_flag). Rides the scoring_rubric slot (versions with the rubric); `score()` does not read it
   (the flag is applied at Pass A). Additive, backward-compat.
2. `claimstore/claims.py`: `entities_with_field_claim(conn, field_key, *, run_id=None, scope)` — the
   set-shaped membership read (M6.3 enumeration; M6.5 admitted counts will reuse it). Exported.

## Adversarial review → fix applied
- **D5 multi-ICP supersede (data-loss):** `_write_score_object` supersede is now **ICP-scoped** (only
  supersedes a prior live score whose value_json `icp_key` matches) — scoring an account under a 2nd
  ICP no longer silently supersedes the 1st. (Full per-ICP *read* semantics on one field is still a
  follow-up — see below.)

## Verification (all green, on isolated clue_m6)
`make check`: ruff format+check, mypy (124 src files), import-linter (10/0). 12 M6.3 tests
(9 engine `test_scoring.py` incl. 1 pure `aggregate_yield`, 3 phase `test_scoring_phase.py`) + full
suite green. Single alembic head `82831d3fa4c5` (M6.3 adds NO migration). Each AC covered by a test:
decomposed+evidenced, tier1-3/zero-tier4 (+ tier-strip), missing→flagged-not-fabricated, idempotent
replay, non_fit_flag-not-excluded, new-version-supersedes-and-bumps, tenant-private, per-source yield.

## Follow-ups
- **D5 read semantics:** two ICPs of one client both write `account.scoring.fit`; supersede is now
  icp-scoped (no data loss) but `current_value` still returns one winner across ICPs. A clean
  multi-ICP read needs an icp_key-scoped score key (or per-ICP score fields). Deferred (M6.3 core is
  single-ICP; spec D5 = future).
- **extraction_method for a computed score = HUMAN** (no `COMPUTED`/`DERIVED` enum; can't touch frozen
  `core`). A `ExtractionMethod.COMPUTED` is a candidate contract-delta (re-freeze) for later.
- **Per-account budget:** handler passes `ctx.budget_cap_cents` as the per-account `budget_envelope`
  (the only budget signal pre-M7). Proper per-account/per-pass split awaits M7's BudgetEngine.
- **Batch read:** `score_account` uses `score_entity` per account (N current_values round-trips).
  `current_values` over the whole list (1 query) is a perf optimization for 1k-10k accounts.
- **api wiring:** `ScoringPhaseHandler` is exported; registration into `CampaignRun` is integration-
  time (M7), at the api composition root — not in this package.
- Next: ENG-146 (M6.4 — tiering + human checkpoint) reads the score object; ENG-150 (M6.5 — coverage).
