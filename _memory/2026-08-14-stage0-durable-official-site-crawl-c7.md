# 2026-08-14 — Stage-0 durable official-site crawl C7

## Outcome

C7 is implemented and verified. Immutable fast/background corpus checkpoints now feed bounded,
category-based concurrent OpenRouter extraction and ordinary append-only Client-KB claims with
provider-neutral `source_key=official_site`. The rollout remains default-off and allowlisted;
C8–C10 retain progress, operator recovery, adversarial, browser, and production cutover gates.

## Implementation

- Added `official_site/materialization.py`: exact checkpoint/artifact reader, frozen HTML/text
  normalization, four deterministic extraction categories, Luna/Terra model routing, strict
  snapshot/URL/verbatim-span validation, independent DB transactions, partial-field outcomes, and
  privacy-safe logs.
- Added migration `a57463ec42ea` with durable extraction operations, requested/answering models,
  prompt/schema/corpus/input identity, response artifact/hash, usage/cost, claim refs, terminal
  failures, and workspace/run/checkpoint/entity/artifact FKs.
- Model egress commits `dispatched` first; raw response is content-addressed before parsing;
  retained response replays persistence only; ambiguous/stale calls quarantine as `spend_unknown`
  and never auto-call again.
- Authoritative C6 composition now injects the materializer and process-wide model gateway.
  Shadow still writes no semantic claims; authoritative startup fails without a gateway.
- The per-operation corpus cap is code-frozen under `official-site-corpus-v1`, not runtime config.
- New claims use `official_site`, trusted snapshot/fetch/artifact references, tier 2, tenant-private
  reuse, the existing Stage-0 run/entity, and the ordinary claim-store validation path.
- Full import-linter initially caught C7 importing `stage0.fields`. The materializer now owns only
  its C0-frozen contract keys, verifies that the committed field registry contains them, and does
  not import or seed a sibling worker package. Final import gate: 25 contracts kept, 0 broken.
- Global legacy Client-KB `tier_plan` remains unchanged until C9/C10 authoritative cutover. An
  initial C7 attempt changed it prematurely and 17 legacy Stage-0 tests failed because default-off
  onboarding could no longer reach its bound resolver. Reverting that global cutover restored all
  35 exact legacy regressions; C7 still emits provider-neutral claims on its own durable path.
- Added production-shaped retained canary `scripts/17_official_site_c7_live.py` and detailed C7
  contract/evidence documentation.

## Verification

- Pure C7 grounding/model tests: 5 passed.
- C7 DB concurrency/replay/fault tests: 2 passed.
- Complete C0–C7 official-site suite: 142 passed; final official-site + API composition rerun:
  146 passed on disposable `clue_c7_regression_20260814_final`.
- Combined C0–C7/API/legacy Stage-0/settings regression gate: 204 passed on the disposable final
  database; retained live evidence was not exposed to the broad suite.
- C7/API contract slice: 23 passed.
- Exact legacy Stage-0 regression files: 35 passed; settings tests: 23 passed.
- Root Ruff: 1,384 files formatted/green; mypy: 656 source files, zero issues; import contracts:
  25 kept, zero broken.
- Migration `a57463ec42ea`: fresh upgrade and downgrade/upgrade green; one Alembic head.
- `git diff --check` green before final verification.

## Retained live Firecrawl + OpenRouter evidence

- Database: `clue_c7_official_site_20260814_v2`.
- Artifact root: `/private/tmp/clue-c7-official-site-20260814-live-artifacts`.
- Target: `https://insighthealth.ai/`.
- Crawl run: `be78aa55-874f-4808-aadf-31f0df3252aa`.
- Requested/served model: `openai/gpt-5.6-luna`.
- 16 page nodes, 16 provider attempts, 15 snapshots; fast/background checkpoints contain 7/15
  snapshots.
- 22 extraction operations: 19 materialized, 2 exact-citation failures, 1 `GatewayError`
  `spend_unknown`; 22 provider-neutral claims; zero claims outside checkpoint provenance.
- Partial success held: the failed company-context value-proposition operations did not erase the
  product/value result; fast filled eight of nine fields and background filled all nine.
- Cold replay: 0 new provider attempts, 0 extraction operations, 0 claims; 0.020 seconds.

## Open operational finding / next handoff

The live run required pre-attempt page leases to expire/reclaim. Final background completion took
17 bounded handler invocations and 135.656 seconds. C7 correctly preserved fences, performed no
completed-page/model refetch, and never hid the pending state, but the ≤40-second release target is
not proven. C8 should make this recoverable state visible and provide operator commands; C10 must
measure/fix or type the live fast-release exception before cutover.

Keep the C7 live database and artifact root untouched until evidence review. No secrets, receipts,
raw page/model bytes, tokens, email addresses, or claim values are recorded in this note.
