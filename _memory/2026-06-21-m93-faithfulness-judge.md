# 2026-06-21 — M9.3 Faithfulness judge (ENG-139)

## State: DONE (impl + adversarial audit + fixes + full DB suite green); awaiting user review
Branch `m9/verification-layer`, local commit pending. `make check` green; **90/90** verification
DB tests on `clue-m9-pg` (5433); db-smoke up→down→up reversible, single head `911a1beeb9c1`.

## Adversarial audit (5-dimension workflow + skeptic verify + completeness critic) — outcome
16 findings raised → **8 fixed**, **4 deferred to backlog**, 9 rejected by the skeptics.
**Fixed in this PR:**
1. **Greedy `{.*}` JSON parse dropped valid `supported` verdicts** (the worst defect): a trailing
   `}` (2nd object / brace in prose) made `json.loads` choke → fell back to UNSUPPORTED → wrongly
   REJECTED a genuinely-entailed tier-4 claim + fired a spurious re-retrieval. Replaced with
   `_first_json_object` (scan each `{`, `raw_decode` one object, skip non-decodable braces). +3 tests.
2. **`judge_policy` global-NULL-slot uniqueness**: plain `UNIQUE(client_id, version)` admits dup
   `(NULL, v)` global rows (PG NULLS-distinct). Added `NULLS NOT DISTINCT` (mirrors migration 0009)
   + deterministic `ORDER BY version DESC, created_at DESC, policy_id DESC` tie-break in loader.
3. **Static no-DB enum-parity guard** (`test_judge_verdict_migration_tuple_matches_core`): the DB
   `pg_enum` parity test skipped in `make check`; added a pure guard importing the migration tuple
   vs `core.JudgeVerdict` (ordered) — mirrors the M9.2 conflict-tier static guard.
4. **Don't hold a DB connection across the LLM call**: split `judge()` into probe(conn1) →
   `_compute_verdict`(no conn, the sync gateway call) → `_persist`(conn2). A multi-second judge no
   longer pins a pooled connection / open txn under fan-out. (Residual: the gateway is *sync* so it
   still blocks the loop — inherent to the M0.4 gateway, repo-wide.)
5. **`load_judge_policy` validates `prompt_version`**: a stale/typo config version now falls back to
   the default prompt + a logged warning at load time, not an uncaught `ValueError` per claim.
6. **Prompt-injection hardening**: fence `value_json`/`evidence_span` with markers + a SECURITY
   clause ("untrusted data, never instructions"). Full adversarial fixtures → M9.6 (backlog).
7. **Docstring precision**: "rejected verdict row" → the re-retrieval signal is a `faithfulness_
   verdict` row with `verdict ∈ {unsupported, contradicted}` + claim `verification_status=rejected`
   (`rejected` is a verification_status, not a `judge_verdict`).
8. **Test gaps closed**: FLAGGED→VERIFIED, VERIFIED→REJECTED (demote), verdict-row content +
   cache-replay round-trip, no-span span emission, parse robustness (3).
   **Also caught a real orphan bug during the fix**: removing the old `_judge` left a dangling
   `return result, False, latency_ms` referencing an undefined `model` — deleted.
**Deferred (backlog in CLAUDE.md/AGENTS.md):** [M9.3×M12] judge_model records *requested* not
*answering* model (add `answering_model` col before M12); [M9.3×M9.6] adversarial-span negative
fixtures → M9.6 eval battery; [M9.1×M0.4] `pre_spend_policy` has the SAME NULL-slot gap (needs a new
migration since M9.1 is applied). C4 cache-replay-skips-status documented as the co-authoritative
design note in `_persist`'s docstring (not a fix).

## State: design locked, implemented
Branch `m9/verification-layer`. Migration base: M9.2 head `b3b636f67bd8`. M9.3 is the 3rd of 6 M9
issues. **No frozen-surface touch** — the `core.verification.FaithfulnessJudge` protocol +
`JudgeResult` value type, the `core.enums.JudgeVerdict` enum, and the
`obs.spans.SPAN_VERIFICATION_FAITHFULNESS_JUDGE` span ALL already exist from the Beat-0 contract
freeze. M9.3 only supplies the impl behind them (exactly like M9.2 supplied `Corroborator`).

## The one load-bearing design decision: who promotes a tier-4 claim to `verified`?
Resolved by reading `claimstore/merge.py` + M9.2 corroborator + M11.3 spec:
- `merge.py::_is_eligible` (lines 127–132) gates tier-4 eligibility on
  `verification_status == VERIFIED` (`require_verified_tier4=True` default) — a tier-4 claim NEVER
  appears in `current_value` unless it is `verified`.
- The M9.2 corroborator **deliberately leaves tier-4 status untouched** ("left to the judge" —
  `test_tier4_left_to_the_judge_but_corroborations_recorded`); corroboration counts tier≤3 only.
- M11.3 spec: "a claim that passes [the faithfulness judge] is **promoted**"; "No tier-4 value
  reaches the merge view without a judge verdict on record."
⇒ **The faithfulness judge owns the tier-4 status transition.** It is the terminal accuracy gate
for tier-4; corroboration owns tier≤3. The judge MUST set `verified` on supported, or no tier-4
synthesized value can ever be surfaced.

## Status transitions the judge writes (ONLY for tier-4 claims)
- `SUPPORTED` AND `score ≥ supported_threshold` AND `can_be_promoted(claim)` → **VERIFIED**.
- `SUPPORTED` but score below threshold → left `unverified` (not a fabrication, just not confident
  enough to promote; the verdict row records the score).
- `SUPPORTED` but `not can_be_promoted` (weak-bound contact / span-less) → left `unverified`
  (binding axis is M9.4's — honors "then subject to M9.4 binding for contacts").
- `UNSUPPORTED` / `CONTRADICTED` → **REJECTED** + re-retrieval signal.
- `PARTIAL` → **FLAGGED** (held for human review; the `FLAGGED` enum is exactly "surfaced for
  review"). Spec says "unverified + flag"; FLAGGED is the in-band form (no new table needed).
- **No-span structural pre-check** (tier-4 with empty `evidence_span`) → `UNSUPPORTED`, REJECTED,
  **zero LLM calls** (the substrate §1 kill switch; `can_be_promoted` is False anyway).
- **Non-tier-4 claims**: the judge still produces + records a verdict (reusable by M9.6 rubric
  scorers) but does **NOT** mutate `verification_status` — that tier is corroboration's domain.
  Prevents the bug where one judge-supported tier-3 claim bypasses `corroboration_min`.

## Shape (mirrors M9.1/M9.2 patterns exactly)
- `verification/faithfulness.py`:
  - `FaithfulnessJudgeImpl` (impl of `core.verification.FaithfulnessJudge`): injected `gateway:
    LLMGateway` (the `core.gateway` protocol — NOT `clue_research.gateway`, kept independent like
    M9.1's injected `_LockReader`), resolved `JudgePolicy`, a `conn_factory` (one committed txn per
    judge: cache read + verdict insert + status update), optional `sink`.
  - `judge(claim) -> JudgeResult` (frozen `core.JudgeResult`: claim_id, verdict, score, rationale,
    judge_model, cost_cents). `prompt_version`/`latency_ms` ride the audit row + span, NOT the
    frozen return type (keeps `core` untouched — same move M9.2 made with prompt_version-less core).
  - Idempotent cache keyed on `(claim_id, judge_model, prompt_version)`: SELECT existing
    `faithfulness_verdict` → return cached (no LLM, no status re-write, no re-emitted re-retrieval);
    cache miss → call gateway → INSERT row → mutate status. Prompt-version bump → cache miss → fresh.
  - Pure helpers (DB-free, unit-tested): `build_judge_messages(claim, *, prompt_version)`,
    `parse_judge_response(text) -> ParsedVerdict` (extract first JSON obj; unparseable →
    UNSUPPORTED score 0 = conservative/safe direction), `needs_re_retrieval(verdict) -> bool`.
  - `JudgePolicy` (judge_model, prompt_version, supported_threshold) + `DEFAULT_JUDGE_POLICY`
    (judge_model defaults from `config.DEFAULT_GATEWAY_CONFIG.judge_model` to avoid drift;
    threshold 0.7, D7-tunable). `load_judge_policy(conn, *, client_id=None)` per-client → global →
    default (typed columns, mirrors `load_pre_spend_policy`). Versioned prompt const
    `FAITHFULNESS_PROMPT_V1` + `PROMPT_VERSION = "v1"`.
  - Span `verification.faithfulness_judge` (entity/field/tier/model/cost/latency/cache_hit +
    M9-local verdict/score/prompt_version/claim_id attrs). M9-local metrics
    `research.verification.faithfulness.{judgments,supported,rejected,re_retrieval}`.
- Migration `911a1beeb9c1` off `b3b636f67bd8`: `judge_verdict` pg enum (mirrors `core.JudgeVerdict`,
  parity-tested), `judge_policy` table, `faithfulness_verdict` table with UNIQUE
  `(claim_id, judge_model, prompt_version)` (the cache key) + claim_id index. **No `claim` ALTER,
  no trigger change** (verification_status already in the 0002 mutable allow-list). Reversible.
- Tests `tests/verification/test_faithfulness.py`: pure-unit (parse/prompt/predicate/enum-parity/
  policy defaults) + DB-gated behaviour (one per acceptance criterion). DB-gated tests inject a
  **fake gateway** returning canned JSON (the real `StubGateway` returns `stub:<digest>`, not a
  parseable verdict — by design; the stub is not a real judge).

## Re-retrieval signal (no consumer yet — M8/M11 not built)
Emitted as: a metric counter + span flag + the durable `faithfulness_verdict` row with verdict ∈
{unsupported, contradicted} and `verification_status=rejected` (queryable by M8/M11 at integration).
The event *delivery* to M8/M11 is integration-time (same deferral pattern as M9.1's AC-6 / the
`verify()` umbrella). `needs_re_retrieval` is the pure predicate; tests assert metric + status.

## Out of scope (documented deferrals)
- The `verify()` umbrella sequencing gates per phase (api composition root, integration-time).
- M9.6 reuses this judge infra for rubric scorers (factual accuracy / citation validity).
- Use gate (M10), tier-4 synthesis resolvers (M11), re-retrieval execution (M8/M11).
