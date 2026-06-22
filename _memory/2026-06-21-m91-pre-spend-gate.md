# 2026-06-21 — M9.1 Pre-spend schema/identity gate (ENG-130)

## State: DONE (impl + review + fixes), awaiting user review on branch `m9/verification-layer`
Branch `m9/verification-layer` forks the **updated** `beat0/contract-freeze` @ `703bd37` (which now
carries the M9 contract delta — `FreshnessState.EXPIRED` + the `verification.pre_spend_gate` /
`verification.freshness` spans, merged via PR #10). Migration base: single head `82831d3fa4c5`
(ENG-165 reuse_scope). M9 is the first of 6 issues (M9.1–M9.6).

## Contract delta (already merged into beat0 before M9.1)
Surgical additive change PR'd into `beat0/contract-freeze` so all four worktrees share one base:
`core.enums.FreshnessState.EXPIRED` (M9.5 retention age-out) + 2 span constants
(`SPAN_VERIFICATION_PRE_SPEND_GATE`, `SPAN_VERIFICATION_FRESHNESS`) + obs `__all__`. Commit
`95f6948` on `m9/contract-delta` → merged `703bd37`. No protocol/value-type/migration churn.

## What M9.1 shipped
- **`verification/pre_spend.py`** — `PreSpendGateImpl` (the Beat-0 `core.verification.PreSpendGate`
  impl): schema gate (field registered + requested tier sanctioned by the field's `tier_plan` via a
  `source_manifest` tier lookup + `value_json` validates against `value_schema`), identity gate
  (entity resolves to a `candidate`/`active` row carrying a strong key; `merged`/unresolved/free-text
  rejected), in-flight-lock check (reject only when a *different* run holds the entity lock), and the
  `gate_decision` audit write. Plus `assemble_target_lock` (canonical-domain `site:` + no-drift
  instruction; contacts excluded raw email), `PreSpendPolicy`/`GateSpec` policy-as-data,
  `parse_gate_spec` (per-field override in `field_definition.gate`), `load_pre_spend_policy`
  (per-ICP → per-client → global → built-in default), `run_lock_token`, the
  `verification.pre_spend_gate` span + `research.verification.prespend.{decisions,blocked}` metrics.
- **Migration `8aefd82b6d59`** (down_revision `82831d3fa4c5`): `pre_spend_policy` config table +
  append-only `gate_decision` audit table + `pre_spend_verdict` pg enum (mirrors
  `core.PreSpendVerdict`). **No `claim`/`field_definition` ALTER** (the `gate_spec` rides the
  existing `field_definition.gate` text column).
- **`tests/verification/`** — conftest (migrated DB + rollback isolation, seeds core pack + source
  manifests) + `test_prespend_gate.py` (21 tests: 7 pure-unit incl. protocol-conformance, 14
  DB-gated covering every §M9.1 acceptance criterion + enum parity + metric emission).

## Key decisions / mechanics
- **Conn/redis injection.** The frozen `PreSpendGate.check(request)` takes no `conn`, so the impl
  holds a `conn_factory` (default `db.transaction` — one committed txn per check, reads + the audit
  row) and an optional structural `_LockReader` (a Redis client). Tests inject a rollback-bound
  factory + a fake lock reader → DB tests skip cleanly without a DB.
- **In-flight lock semantics (documented choice).** The gate rejects ONLY when the lock is held by a
  *different* run (token ≠ `run_lock_token(run_id)` = `str(run_id)`). Absent / held-by-this-run →
  pass. This is the anti-double-spend guard and matches the acceptance criterion; it does NOT require
  the run to already hold the lock (would over-couple gate ordering). The token convention is a pure
  shared function so the locker (M7/M8) and checker (M9.1) agree without importing each other.
- **Tier check.** `tier_plan` holds source *keys*; sanctioned tiers are resolved from
  `source_manifest`. Fail-soft on the tier sub-check when no plan source is registered (covered set
  empty) — the schema-existence + identity + lock checks still apply.
- **`gate_decision` append-only by use** (like `source_yield`) — no trigger, no mutation path;
  "claims blocked pre-spend" = COUNT(*).
- **`pre_spend_policy` is its own table + loader** (matches the M4 `source_profile` precedent), not
  the M0.4 `ConfigOverlay` — `PreSpendRequest` carries no client_id, so the resolved policy is
  injected at construction (api composition root); `load_pre_spend_policy` is the per-scope reader.

## Deferred (NOT defects — out of M9-isolation scope)
- **Acceptance criterion 6** ("every claim-producing call routes through `PreSpendGate.check`,
  enforced by a lint/integration test"): the callers (M4 waterfall is built; M8/M11 not yet) live in
  other packages M9 cannot wire without breaking independence. The gate + the run-keyed
  `gate_decision` audit are the substrate; the enforcement test is added when M4/M8/M11 are wired to
  the gate at the **api composition root** (integration-time). Flag for M8 integration.
- The `verify()` umbrella and the `VERIFICATION` `PhaseHandler` are built incrementally across
  M9.2–M9.x; their api registration is integration-time.

## Verification performed
- `make check` (no DB) green: ruff + ruff-format + mypy (109 src files) + import-linter **10 kept /
  0 broken** + pytest **389 passed / 317 skipped**.
- DB suite on an **isolated** throwaway DB `clue_m9` (created on the host-reachable localhost:5432
  server alongside the siblings' `clue_m5`/`clue_m6`/`clue_m7` — NOT the shared `clue`): all **21**
  verification tests pass; full repo suite green with DB (no regressions).
- `make db-smoke` (up → down → up) reversible through `8aefd82b6d59`; `alembic heads` single
  (`8aefd82b6d59`).

## Gotchas for the next M9 issues
- **Shared-DB hazard is real**: host `localhost:5432` is NOT the `clue-postgres` container you can
  `docker exec` into — it's a separate server. Create per-branch throwaway DBs via a *host* asyncpg
  connection (`CREATE DATABASE clue_m9`), set `CLUE_DATABASE_URL` to it, never migrate the shared
  `clue`.
- `claim.verification_status` / `corroborations` are ALREADY trigger-mutable (0002 allowlist) → M9.2
  needs no trigger change to promote claims. `identity_binding` IS immutable (0004) → M9.4 sets it
  pre-insert / via supersession, never in-place.
- Each next issue: own hash-id migration off the current M9 head; one `verification/<topic>.py`
  module; `tests/verification/test_<topic>.py`; update Linear (In Progress → comment → In Review).
