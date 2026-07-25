# 2026-07-21 — BudgetTracker DRY consolidation (deferred from the 2026-07-03 survey)

Branch `platform/workspace-restructure`. NOT committed (per task instruction — report only).

## What
One shared `core.BudgetTracker` (dataclass, `libs/clue-core/clue_core/execution.py`, cost-governance
section next to the `BudgetEngine` seam; exported from `clue_core/__init__.py`): `envelope_cents`
(None = unbounded) + `spent_cents`, methods `spend(cost)`, `would_exceed(next)` (**strict** `>` —
exact fit allowed), properties `exhausted` (**inclusive** `>=`), `remaining_cents` (unclamped,
None when unbounded). The two boundaries are deliberately distinct (M7.5 convention) — each site
kept its exact pre-existing boundary.

## Sites rewritten (behavior identical; public signatures unchanged — envelope/cost_so_far params kept)
1. `sources/waterfall.py::resolve_field` — tracker seeded `spent_cents=cost_so_far`; per-step
   `would_exceed(manifest.cost_cents)`; result `total_cost_cents = spent - cost_so_far` (delta).
2. `sources/planner.py::plan_sources` — `would_exceed(source.cost_cents)` halt + `spend` on RUN.
3. `profiling/aspect_worker.py::research` — `exhausted` per-field cap (was `remaining <= 0`),
   `remaining_cents` handed to planner/waterfall, `spend(fill.cost_cents)`.
4. `stage0/client_kb.py::reverse_profile` — outer `exhausted` (was `spent >= cap`), threads
   `cost_so_far=budget.spent_cents` into the waterfall.
5. `durable/graph.py::_grant_facets` — reservation decrement only (`spend(estimated or 0)`,
   `remaining_cents` → `SpawnGuard.may_spawn`); the would-exceed CHECK stays in SpawnGuard (policy).
6./7. `discovery_scoring/discovery/stopping.py` + `profiling/committee/stopping.py` — the
   duplicated (cap, spent, `>=`) triple → tracker; window/yield logic untouched.

## Deliberately NOT collapsed
- `durable/budget.py` `BudgetEngine` — the M7.5 policy/ledger seam (verdicts, persisted ledger,
  clamped BurnDown.remaining). Tracker docstring states the distinction.
- `SpawnGuard.may_spawn` — the policy check itself.
- `sources/waterfall.py::resolve_fields` — pure accumulation threading through the public
  (envelope, cost_so_far) params; a tracker there gains nothing.
- `review/observability.py` — reads the clamped `BurnDown`, a different quantity.

## Tests
`tests/test_core_budget_tracker.py` — unbounded, exact-Decimal accumulate, strict would-exceed
boundary (exact fit allowed), inclusive exhausted-at-cap, cost_so_far seeding + delta, unclamped
negative remaining on overshoot, spend(0) reservation no-op.

## Verification (all exit 0)
ruff fix+format clean; `make check`: mypy "Success: no issues found in 281 source files",
import-linter "16 kept, 0 broken", pytest 1158 passed / 794 skipped. `make db-fresh` then full DB
suite on `clue`: pass; rerun without reset: pass ("1938 passed, 14 skipped in 30.97s").
