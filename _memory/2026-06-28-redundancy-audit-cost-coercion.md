# 2026-06-28 — Redundancy audit cleanup: cost coercion (#18, a latent budget bug)

Continuing the `.context/redundancy-audit-report.md` sweep. #18 is the one entry that fixes a
**real latent correctness bug**, not just churn — prioritized accordingly.

## The bug (durable/graph.py `_to_cost`)
`graph.py`'s `_to_cost` had drifted *loose* (no finite/non-negative guard): it coerced a
**worker-supplied** (least-trusted) `estimated_cost_cents` straight into the facet spawn-budget
path (`_grant_facets` → `SpawnGuard.may_spawn`). Confirmed downstream effects:
- **negative** estimate → `may_spawn` allows it, then `remaining -= estimated` *increases* the
  envelope → silent per-entity-cap evasion.
- **NaN** estimate → `cost > remaining_budget_cents` signals `decimal.InvalidOperation` (verified:
  ordering comparison on a quiet NaN raises under the default context) → crashes the durable phase
  (not "silently allowed" as the audit text loosely said — but equally bad).
- It also violated its own return type (`CostCents = Annotated[Decimal, Ge(0)]`).

The strict sibling in `durable/campaign.py` (client-cap parse) *did* guard — they had just drifted
apart. A third strict copy was inline at `discovery_scoring/tiering/results.py::from_decision`, and
a fourth defensive variant in `resolvers/grounded.py::dollars_to_cost_cents`.

## Fix (committed)
One canonical strict parser `core.parse_cost_cents(value) -> CostCents | None` in
`core/factories.py` (next to `decode_jsonb` — same "defensively coerce untrusted input" flavour;
factories.py already imported `CostCents`/`Decimal`). Returns `None` for absent / unparseable /
non-finite (NaN/±Inf) / negative; `is_finite()` before `>= 0` so a bare `NaN >= 0` can't signal.
Exported from `core/__init__.py`.

All four sites route through it:
- `durable/graph.py` — deleted loose `_to_cost`; `estimated = parse_cost_cents(...)`. Malformed →
  `None` → treated as `Decimal(0)` (free), consistent with the existing "no estimate → free" rule.
  No inflation, no crash.
- `durable/campaign.py` — deleted strict `_to_cost`; `cap_in = parse_cost_cents(...)`.
- `discovery_scoring/tiering/results.py` — replaced the 12-line inline block; dropped now-unused
  `from decimal import Decimal, InvalidOperation`. (`CostCents` still used by other fields → kept.)
- `resolvers/grounded.py` — `dollars_to_cost_cents` now `parse_cost_cents(dollars)` then `×100`
  (0-default on `None`). Same semantics, drops its own try/except+guard.

Net **−13 lines** in src.

## Tests
- `tests/test_core_helpers.py` — `parse_cost_cents` happy path (exact Decimal, no float-rounding) +
  rejects None/NaN/Inf/-inf/-5/"notanumber"/list/bool → None.
- `tests/durable/test_account_recursion.py::test_malformed_facet_estimate_cannot_inflate_or_crash_budget`
  — regression at the actual bug site: a `-1000` and a `NaN` facet estimate (envelope 100) each
  grant free without moving `remaining`, so a real 150-cent follow-up facet is still denied; run
  completes (no crash). With the old loose coercion: `-1000` → facet.calls==2 (evasion), `NaN` →
  crash. The existing campaign-level `test_malformed_budget_cap_does_not_crash_or_persist` already
  guards the cap path and still passes.

## Verification
`make check` green: ruff (format+lint), mypy strict, import-linter **11/11 kept**, pytest
**1110 passed / 782 skipped** (skips are DB-gated; this change has zero DB surface).

## Audit backlog status (see also [[2026-06-28-redundancy-audit-connfactory]])
- **#8, #60** ConnFactory family: DONE (commits `45f42bc`, `5e3ca85`, `eee1b4c`).
- **#18** cost coercion: DONE this session.
- Not started: `core`-primitives batch (#1–6, contract-delta — biggest dedup; jsonb decoders,
  [0,1] clamp, utc_now, host-normalization), #32 dead `config.ScoringRubric/SourceProfile`, etc.
