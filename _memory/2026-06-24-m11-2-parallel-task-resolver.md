# 2026-06-24 — M11.2 Parallel Task tier-4 grounded-synthesis resolver

## Goal
Implement **M11.2** (Parallel Task) on `m11/tier4-synthesis`, on top of the committed M11.1 (Exa
Deep, commit `a2c2063`). A second, independent tier-4 synthesis provider behind the SAME
`GroundedSynthesisResolver` seam — the concrete proof the tier-4 seam is provider-agnostic. **Zero
migrations** (the `parallel_task` manifest + synthesis field rows were seeded pre-flight).

## What M11.2 added / changed
- **`resolvers/parallel/__init__.py`** (NEW) — Parallel-only pure pieces, mirroring `exa/`:
  `ParallelTaskConfig` (endpoint / `processor` / timeout / retries / `min_confidence` /
  categorical-confidence bands / `default_cost_cents`); `build_parallel_request` (entity-bound
  `input` via the shared `entity_query`, `x-api-key`, basis enabled); `normalize_parallel_response`;
  `_coerce_confidence` (categorical `high/medium/low`→bands OR numeric via shared `coerce_confidence`);
  `_cost_cents`; `make_backend`; `register_parallel_task_resolver`. Own key `CLUE_PARALLEL_API_KEY`,
  NOT the OpenRouter gateway. No SDK (shared generic HTTP).
- **`resolvers/grounded.py`** generalized to serve BOTH providers (DRY):
  - `SynthesisResult.reasoning: tuple[str,...]` — a provider's rationale, surfaced ONLY on the
    `synthesis.<source_key>` trace span (capped 2000c), **structurally barred** from an evidence
    span (`_build_claims` reads only `SynthesizedField.evidence_span`, never `result.reasoning`).
  - extracted `entity_query`/`field_intent`/`_FIELD_INTENT` (from `exa/`), `as_list`,
    `dollars_to_cost_cents` — Exa now imports them (1:1 parity; verified by diff + green Exa tests).
  - added a `confidence` span dim (max confidence of kept fields) — the M11.2 tracing AC lists it.
- **`api/synthesis_wiring.py`** — `register_synthesis_wiring()` binds Parallel Task too.
- **`resolvers/__init__.py`** — exports the `parallel` sub-package + symbols.
- **`tests/resolvers/test_static.py`** — allowlisted 2 new ≥24-char symbol names
  (`register_parallel_task_resolver`, `normalize_parallel_response`) for the opaque-token oracle.

## Key design decision — cited-excerpt-as-value (Model 2)
Parallel's claim **value ≡ evidence_span ≡ the cited excerpt** (real retrieved text), exactly like an
Exa highlight — NOT the LLM's synthesized narrative. This is the tightest reading of the core bet
(*the LLM may plan queries but may never be the source; no value without a backing passage*), keeps
Exa+Parallel semantically uniform (the grounded.py guards/dedup apply unchanged), and sidesteps the
by-value-dedup tension. The synthesized **reasoning** is relegated to the (un-promotable) trace.
Each citation excerpt → one grounded `SynthesizedField`; reasoning → `SynthesisResult.reasoning` →
trace; reasoning-only basis (no citation) → no field (dropped).

## Audit (the planned 4-lens adversarial Workflow FAILED — weekly subagent limit, resets Jun 28)
The Workflow audit could not run (4/5 agents died on the limit; `confirmed_count:0` is meaningless).
Did a **manual + deterministic** audit instead (main loop still available):
- **Deterministic gates (all green):** `lint-imports` 11/11 KEPT (parallel imports no sibling
  provider, no SDK, registry one-way); `ruff check .` clean; `mypy src` clean (211 files);
  resolver suite green incl. all 9 DB-gated e2e (Exa + Parallel) on a clean DB.
- **Exa-refactor parity:** `git diff a2c2063 -- exa/__init__.py` shows every removed helper replaced
  by an identical shared one — no behavior drift (and Exa's tests still pass).
- **Manual spec-fidelity:** every M11.2 AC maps to a real test. Found ONE gap → FIXED: the tracing
  AC lists `confidence` as a span dim, which the shared span didn't emit. Added it (provider-neutral,
  max of kept fields; stored stringified like the sibling `n_retrieved`/`n_kept` dims) + tests.

## The two make-check failures observed on the M11.1 full run (both resolved)
1. `test_no_secret_shaped_strings…` — the redactor flags any `[A-Za-z0-9_-]{24,}`; new long symbol
   names tripped it → allowlist (the fix shipped in the M11.1 commit; M11.2 adds 2 more).
2. `test_no_domain_tables_at_m0_head` — **environmental**, NOT a regression (M11 adds zero
   migrations). The reused throwaway `clue-pg-m11` (:5433) had accumulated orphan state; the
   migration suite passes clean on a fresh DB (verified in isolation). Lesson: use a FRESH per-run DB.

## Verification
- Resolver suite (grounded + exa + parallel + static): green on `clue-pg-m11-fresh` (:5434),
  including all 9 DB-gated e2e (no skips when the DB is up). ruff/mypy/import-linter clean.
- Full `make check` on the clean DB launched after the audit fix — see session tail for the result.
- All clue-pg containers exited 255 simultaneously mid-session (a host Docker event, not test damage);
  `docker start clue-pg-m11-fresh` restored the migrated state and the e2e tests.

## Known / accepted (not defects)
- **Same excerpt from two different URLs → one claim.** The substrate dedups by distinct VALUE
  (M11.1 contract); byte-identical excerpts from different sources collapse to the first. Rare,
  consistent with Exa, and tier-4 convergence is a judge signal — NOT a tier-≤3 `corroborations`
  increment (M9.2 owns that). The resolver never dedups Exa-vs-Parallel.
- **Parallel request/response is the documented assumed contract** (recorded-fixture path; cost
  assumed `costDollars.total`). Finalized against live fixtures when creds land — isolated in
  `build_parallel_request`/`normalize_parallel_response`, never a seam change.
## Second audit pass (re-ran the 4-lens Workflow after the user reset the account limit)
The full audit ran (9 agents, 766k tokens) and confirmed **2 findings, both `nit`** (no functional
defect). Both fixed in a follow-up commit:
1. The tracing test didn't assert the `source_key` ("provider") / `cost_cents` span dims the M11.2
   AC names — the code set them, but a refactor dropping them wouldn't be caught. Added the asserts.
2. The `costDollars.total` reader was byte-identical in `exa/` and `parallel/` `_cost_cents` (only
   the dollars→cents math had been extracted). Promoted the full reader to
   `grounded.cost_cents_from_cost_dollars`; both providers now call it (no duplication). A provider
   whose live cost shape differs overrides with its own reader — `cost_cents_from_cost_dollars` then
   stays the shared default. (Earlier note's "`_cost_cents` intentionally per-provider" was the
   pre-fix state; superseded by this extraction.)

## Files (M11.2 change set, on top of a2c2063)
NEW: `resolvers/parallel/__init__.py`, `tests/resolvers/test_parallel_task.py`.
MODIFIED: `resolvers/grounded.py`, `resolvers/exa/__init__.py`, `resolvers/__init__.py`,
`api/synthesis_wiring.py`, `tests/resolvers/test_grounded.py`, `tests/resolvers/test_static.py`,
`docs/specs/_m11-tier4-synthesis-plan.md`.

## Follow-ups (deferred, unchanged)
- M11.3 (`synthesis/`): judge-gated synthesis workers, Pass-B-only guard, verification-health metric
  (Doc C §6), M9.6 golden-set rows. Field rows already seeded.
- Integration: wire `exa_deep`/`parallel_task` through `PreSpendGate.check` at the api root (M9.1 AC6).
- DRY backlog (post-integration): one shared `normalize_host` + one shared word-boundary name matcher
  (still local copies across resolvers/verification).
