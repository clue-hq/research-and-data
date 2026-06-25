# 2026-06-25 — M11.3 synthesis judge-gating glue (the `synthesis/` package)

## Goal
Implement **M11.3** (the wiring that makes the tier-4 resolvers safe to ship — the governed,
judge-gated layer) on `m11/tier4-synthesis`, after M11.1 (`a2c2063`) / M11.2 (`789e7f2` + audit
`ff61fd8`). **Zero migrations.**

## The decisive constraint (drove the whole shape)
`synthesis/` is a milestone worker under the **"workers are independent"** import contract: it may
import `core`/`config`/`obs` + the M1–M4 services (`claimstore`/`sources`/`icp`/`identity`), but
**NOT** `verification/` (judge), `resolvers/` (Exa/Parallel), `durable/`, or `profiling/`. So the
*runtime* judge-gating pipeline (`pre_spend → resolve → corroboration → faithfulness → promote`)
cannot live in `synthesis/` — it is composed at the `api` root (exempt). Same deferral pattern as
M9.1 AC-6 / M9.4 / M9.5.

## What I found on the base (most of M11.3's substrate already exists — verified via 3 Explore agents)
- Synthesis **field rows** seeded (PF-6, frozen `claimstore/packs.py`): `account.operational_pain`,
  `account.strategic_moves`, `account.resonance.culture` — `pass=DEEP`, `tier_plan=(exa_deep,
  parallel_task)`, `gate="deep-pass"`, TTL 90/60d. In the **in-memory `CORE_PACK`** (so tests need no DB).
- **Merge judge-gating already enforced**: `claimstore/merge.py` `MergePolicy.require_verified_tier4=True`
  → `_is_eligible` excludes a tier-4 claim whose `verification_status != VERIFIED` from `current_value`.
- `core.can_be_promoted` blocks tier-4-without-span. Faithfulness judge = `verification/faithfulness.py`
  (M9.3). The M8 `profiling/AspectProfilingWorker` (mode M2) already resolves the synthesis fields via
  the waterfall. `VERIFICATION_GATE_ORDER` (…→faithfulness→…) in `api/composition.py` (PF-7).
- `obs.record_verification_health` emits the tier-4 pass-rate **aggregate** (METRIC_TIER4_TOTAL/PASSED,
  no field dim). `signal_class` is **not** on the field rows — it's ICP-declared at M3 compile time
  (`icp/compiler.py`).

→ So M11.3 adds **no** redundant worker and does **not** re-implement the merge gate. It ships the
*policy* + the *per-field metric* + tests, and documents the deferred api-root wiring.

## What shipped (this commit), all import-safe + hermetic tests
- **`synthesis/gating.py`** — policy as testable core-typed code: `SYNTHESIS_SOURCE_KEYS`
  (`exa_deep`/`parallel_task`), `ACCOUNT_SYNTHESIS_CLASSES`, `PASS_B_MODE=ACCOUNT_PROFILING`;
  predicates `is_synthesis_field`/`is_account_synthesis_field`/`is_governed_synthesis_claim`;
  guards `guard_account_only` (personal-data firewall), `guard_pass_b`, `guard_synthesis_resolution`
  (combined, the api-root defense-in-depth call), `assert_pass_b_claim`; `synthesis_claim_is_promotable`
  (restates the M1.2 gate). `SynthesisGateError`.
- **`synthesis/health.py`** — `record_synthesis_health(claims, sink)`: per-field tier-4 pass-rate (Doc C
  §6), dimensions obs's METRIC_TIER4_TOTAL/PASSED with `{field_key}` (sum over field_key = aggregate;
  do NOT also call the aggregate over the same claims — double-count).
- **`synthesis/__init__.py`** — exports.
- **`tests/synthesis/test_gating.py` + `test_health.py`** (22 tests, no DB): field-row shape, firewall,
  Pass-B-only, resonance open class, the **judge-gate via merge** (unverified/rejected tier-4 excluded
  from `current_value`, verified promoted), no-span-no-promote, per-field metric + sum-to-aggregate.

## Decisions (confirmed by product owner before coding)
1. Defer the api-root `VERIFICATION`-phase integration (M9's phase; risks parallel-worktree conflicts).
2. `strategic_moves` tier-4-last (tier-3 news short-circuit) = **PF-6-superseded / N/A** (frozen
   tier_plan is tier-4-only); don't re-add a tier-3 news source.
3. Assert the actual base `gate="deep-pass"` (spec's committee-gated/tier>=1 simplified by PF-6).

## Deferred to integration (documented in the plan doc)
- `CampaignPhase.VERIFICATION` handler (corroboration+judge+promote pass) — the live call site for
  `guard_synthesis_resolution` + `record_synthesis_health`.
- api-root `PreSpendGate.check` tier-4 routing (M9.1 AC-6).
- **M9.6 golden-set rows** for the synthesis fields (live in `verification/golden.py` — M11 can't
  import/edit; add at M9.6/worktree integration).

## Verification
- `tests/synthesis/`: 22 passed (hermetic). ruff + mypy clean. import-linter **11/11 KEPT** (synthesis
  stays independent — imports only `core`/`obs`).
- DRY note: `ACCOUNT_SYNTHESIS_CLASSES` duplicates the resolver's `_ACCOUNT_SYNTHESIS_CLASSES` (the two
  packages can't import each other); one-shared-constant-in-`core` is a post-integration cleanup, like
  `normalize_host`.

## Files (M11.3 change set)
NEW: `synthesis/gating.py`, `synthesis/health.py`, `tests/synthesis/__init__.py`,
`tests/synthesis/test_gating.py`, `tests/synthesis/test_health.py`.
MODIFIED: `synthesis/__init__.py`, `docs/specs/_m11-tier4-synthesis-plan.md`.
