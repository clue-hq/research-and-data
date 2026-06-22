# 2026-06-20 — M0.4 LLMGateway (OpenRouter) — built first for M4 (ENG-120)

## State: DONE, on branch `akeshri516/eng-120-m04-llm-gateway` (off `integration/m4` off `main`)
First step of the M4 build (decision #4: build the gateway FIRST, against the real gateway, not
stub-and-defer). `make check` green: ruff + mypy --strict + **7/7** import contracts + 287 passed /
157 skipped. Two commits: `80454b0` (impl), `74495f3` (adversarial-review fixes).

## What shipped
- **`core/gateway.py`** — `LLMGateway` Protocol + value types (`Message`/`Role`/`Completion`/
  `TokenUsage`/`EmbeddingResult`/`Vector`). The shared contract every call site binds to; the model
  analogue of `core.Resolver`. `complete -> Completion`, `embed -> EmbeddingResult` (both carry
  usage + cost_cents — a bare `str`/`list[Vector]` can't satisfy the per-call cost AC).
- **`config/gateway.py`** — `GatewayConfig` (policy-as-data: base_url, per-call-site model ids
  judge/planner/synthesis/embedding, timeout/retry, fallback_model, `stub` flag, per-model
  `prices` table with `cost_cents()` Decimal math). Folded into the layered `Config`/`ConfigOverlay`
  + loader `_merge`. `openrouter_api_key` added to `Secrets` (env `CLUE_OPENROUTER_API_KEY`).
- **`gateway/` (NEW top-level package)** — `OpenRouterGateway` (live; the ONLY place `openai` is
  imported; injectable `client_factory` seam for hermetic logic tests; fallback-model retry +
  `GatewayError` on empty choices), `StubGateway` (deterministic offline — the CI path),
  `TracingGateway` (emits `llm.gateway_call`), `build_gateway(config, api_key)` factory
  (stub when `stub=True` OR no key → hermetic CI).
- **obs** — `SPAN_LLM_GATEWAY_CALL` + model/token attrs; new `apply_attributes(span, attrs)` seam
  (post-hoc redacted attribute setter). **Fix:** `safe_attributes` now trusts the curated
  `STANDARD_ATTRIBUTES` allowlist fully (dropped the redundant `is_secret_name` gate that masked
  `*_tokens` on the "token" substring).
- **pyproject** — `openai>=1.40` dep; **import-linter Rule 4b** ("LLM-vendor SDK lives only behind
  gateway/"); mypy override treats `openai` as Any (decouples from SDK stub drift).
- **tests/gateway/test_gateway.py** — 28 tests. `gateway` registered in test_package_layout RESERVED.

## KEY DECISION (structural, made by me — not a spec deviation)
Spec says M0.4 "owns" the gateway, but the gateway must emit the `llm.gateway_call` span (obs/), and
the import-linter layering is **`obs → config → core`** — so `config`/`core` may NOT import `obs`.
Resolution mirroring `core.Resolver` ↔ `resolvers/`: **protocol+types in `core`, config in `config`,
client in a NEW top-level `gateway/` package** (unconstrained by the layering → may import all three).
This is why the gateway is not physically inside `config/`.

## Adversarial self-review (find→verify workflow): 1 real defect, 7 judgment, 5 false-pos
FIXED: (1) §4 doc said `embed -> list[Vector]` (code is right → fixed the doc); (2) empty-`choices`
HTTP-200 → typed `GatewayError` + fallback (verified reachable vs real openai SDK 2.43.0); (3) chain
primary exception on all-fail; (4) `apply_attributes` seam removes the dup attribute path in
`TracingGateway`. NOT fixed (verifier: not a bug, reverting regresses): the `safe_attributes`
allowlist change.

## DEFERRED / BACKLOG (surfaced by review, intentionally not fixed in M0.4)
- **safe_attributes forward-looking:** the curated allowlist is now the sole redaction trust
  boundary. Safe today (every standard key is a typed id/enum/number/public model id; `source_key`
  is regex-constrained). IF a future milestone adds a **free-text** standard span dimension (e.g. a
  resonance/personal-hook value surfaced as an attr), add type-gated value-shape redaction for
  str-typed standard values (must NOT re-mask UUID strings — that's the bug the allowlist fixed).
- **GatewayConfig.prices footgun:** documented in code — overlay does whole-subtree replace (M0
  policy, same as BudgetCaps), so a model-id-only overlay drops the inherited price table → costs
  read 0. Mitigation if it bites: move `prices` to its own config surface beside BudgetCaps.
- **DB-DSN dual read path** (pre-existing, out of M0.4 scope): `db/engine.py` reads `os.environ`
  directly while `Secrets.database_url` is unconsumed; `secrets.py` docstring's "nothing reads
  os.environ ad hoc" is slightly untrue. Cosmetic; harmonize at leisure.

## NEXT (M4 build order): M4.2 Source Registry (ENG-111) — first M4 submodule. The gateway is ready
for M4.6's planner to code against (decision #4 satisfied). See [[2026-06-19-m4-kickoff-handoff]].
