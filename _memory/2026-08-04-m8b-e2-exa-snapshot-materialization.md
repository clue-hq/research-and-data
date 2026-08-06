# 2026-08-04 — M8B E2 Exa snapshot materialization

## Scope completed

- Added offline-only Exa Deep ready-snapshot materialization with exact workspace, project-run,
  canonical-account and confirmed-directive lineage.
- Revalidates the immutable request, response, normalization, provider request id, reported cost,
  all-null disposition, result URL, and result artifact before constructing grounded fields.
- Materialized claims carry immutable provider-neutral operation, snapshot and request references;
  provider spend remains owned by the E1 receipt and field claims cost zero.
- Added task-local resolver overrides for both mechanical profiling and the governed account agent.
  No resolver/materializer path can dispatch HTTP or read a credential.
- Bound the same exact effective field-source plan into the coverage tool and pre-spend gate.
  Unbound higher-priority sources do not consume fictional budget; already-settled snapshot reads
  remain available with zero remaining account budget.
- Added the healthcare workspace/ICP override helper: Sumble Jobs or deliberately capable Sumble
  Technology, then the configured official-page source, then Exa Deep; no Parallel Task.
- Corrected the deep-orchestrator composition seam found by combined A1/E2 acceptance: a confirmed
  directive pin is accepted by both mechanical and agent profilers, and `AccountSpec.field_keys`
  now narrows the ICP passed to the account unit.
- Alembic `2e6920101a1b` adds all-or-none immutable external-acquisition lineage to `claim`.

## Verification

- Ruff passed for all changed Python files.
- Mypy passed for the modified production composition/materialization files.
- Six combined E2 + A1 DB-backed acceptance tests passed.
- 102 A0-A2/E0-E2, coverage, resolver-scope and durable-orchestrator regression tests passed.
- `alembic heads` returned one head: `2e6920101a1b`.
- Clean disposable DB `clue_e2_smoke_20260804b` passed head -> base -> head and was removed.

## Explicitly authorized live canary

- Exactly one request reached `https://api.exa.ai/search`.
- The provider returned HTTP 401 for the configured credential.
- Durable operation `51586418-8e20-46eb-afbd-c13033bb232e` ended
  `failed_terminal` / `not_charged`, failure code `hard`.
- One attempt was marked dispatched; no retry and no ready snapshot were created.
- This proves the definitive credential-failure boundary only. A successful paid V1
  request/snapshot/materialization/replay canary remains open until a valid Exa credential is
  configured.

## Close-out

E2 is mechanically complete. Do not claim successful live Exa acquisition from this run. The next
serial work is the remaining O2 launch/full-unit composition; rerun the one-account live canary
first when a valid `CLUE_EXA_API_KEY` is available.
