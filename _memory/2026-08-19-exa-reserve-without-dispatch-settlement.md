# Exa reserve-without-dispatch — root cause and settlement repair (2026-08-19)

Follows `2026-08-19-comprehensive-research-integrity-settlement-repair.md` (commit `03a69712`).

## The live defect

Run `b3ad33b7-94d7-5524-8bee-e5350ecc41d4`, account "The Permanente Medical Group, Inc."
(`15baba9c-…`), job `04162ed5-…` (still `queued`).

One `research_account_deep` tool request (`05b7753c-…`) compiled four Exa Deep bundles. All four
were reserved through `bind_before_dispatch`, all four were really dispatched (the external ledger
has `external_research_attempt.dispatched_at` for each), three returned `ready`, and the fourth
(`31b13c06-…`, fields `account.resonance.buying_culture|culture|employee_sentiment`) came back
`spend_outcome_unknown`: Exa answered 200 with **truncated structured-output alias keys**, so
`validate_exa_deep_exchange` refused the exchange.

`ExaAccountSemanticResearchAction.execute` then raised its all-or-nothing
`len(ready) != len(acquired)` integrity error. Because the entity-research provider ledger only
learns about dispatch on the *success* path (the post-acquisition re-projection with
`include_dispatch=True` inside the tool layer's `observe`), all four
`entity_research_provider_operation` rows stayed `dispatched_at IS NULL` with zero results and zero
settlement folds — the exact state execution closure counts as "no attempt". The raise is
deterministic on replay, so the account could never settle.

## Fixes (all in `platform/api/clue_api/`)

- `entity_research_tools.py` — new `EntityResearchProviderCausationStore.settle_terminal`
  (`observe` → stamps the real dispatch time → append-only zero-cost fold); the
  `EntityResearchProviderAction.execute` protocol gains a `settle_terminal` callback; the tool
  layer records the settled field keys, admits a partition of `covered ∪ settled`, and converts an
  all-unproductive call into a governed rejection instead of an integrity crash.
- `exa_entity_research_tools.py` — `_settle_unproductive_bundles`: a `FAILED_TERMINAL` /
  `SPEND_OUTCOME_UNKNOWN` bundle is settled terminally and the ready bundles still persist. The
  contact action settles only when *every* bundle is unproductive (its bundles all project the
  same request field set, so a mixed batch has no honest partition).
- `sumble_entity_research_tools.py` — both `FAILED_TERMINAL` paths now settle through the new seam
  instead of the bare fold, so the dispatch stamp lands too.
- `account_entity_research.py` — (F1, **reverted per the coordinator ruling 2026-08-19**) the
  terminal-attempt predicate stays `dispatched_at IS NOT NULL AND (result OR fold)`. The
  relaxation is unnecessary because `settle_terminal` stamps the provider's true dispatch time
  before folding, so every fold over a real exchange counts; and it was harmful, because it let a
  sibling-cancelled member's pending-release fold settle fields nothing was ever sent for.
  (F2) a non-acquisition field
  with no derived source (`core.account_name`) closes as an honest gap instead of blocking assess
  and accept forever — this revives the `canonical_identity_missing_evidence` disposition.
- `entity_research_parallel.py` — **unmodified in the end.** F6 originally wrote a zero-cost fold
  in `failed()`; that was removed (see the mechanism note below). Its budget-release behaviour is
  untouched.
- `account_entity_research.py` — new module-level `pending_provider_operations_sql(job_expression)`
  is the **single** definition of "provider work this job still waits on", read by both spec-§5.4
  enforcement points: `AccountResearchStateStore._pending_refs` (assessment) and the
  `pending_operations` count inside `AccountResearchFinalizationEngine.accept`'s query. They can
  no longer drift. It adds one clause to the pre-existing result/fold tests: an operation with
  `dispatched_at IS NULL` whose causing batch member carries a durable `failed`
  `entity_research_tool_batch_event` is released. A *dispatched* operation from a failed member is
  deliberately not released — that outcome belongs to the provider's attempt ledger.
- `entity_research_provider_wiring.py` — `_UnavailableProviderAction` signature.
- `entity_research_tools.py` — a requested field with **no** authorized source now refuses as the
  repairable `EntityResearchGovernedRejection` (`field_source_authority_mismatch`) instead of the
  suspending authority error. With the Sumble lane's F3, a comprehensive field can legitimately
  carry an empty authority (`core.company_linkedin_url`), and a model naming it must be able to
  drop it rather than kill the job. The tool layer now converts a governed rejection out of
  `requests.record` too.
- `account_entity_research.py` — the reader's satisfaction test now calls the shared
  `CurrentValue.evidence_backed` (`clue_core/handoff.py`) instead of a fourth inline copy.

## Tests

`tests/api/test_comprehensive_account_execution_db.py` (+5 total in file, 3 new cases):
- `test_an_unsettleable_exa_bundle_settles_terminally_instead_of_stranding_the_account` — the live
  shape, via `_TruncatingExaTransport`. Verified to FAIL with the old branch restored.
- `test_a_reserved_but_undispatched_operation_is_not_a_terminal_attempt` (slice-5 case 8, plus the
  case-15 invariant: nothing anywhere is folded or marked attempted).
- `test_a_dispatched_but_pending_operation_is_not_a_terminal_attempt` (case 9).
Also patched the `execute` doubles/callers in 6 other test modules for the protocol change.

## Residuals / open decisions

- **SETTLED 2026-08-19 — a fold means settlement and nothing else; release is a read.** Two
  rulings landed. (1) The frozen contract wins over F1: the terminal-attempt predicate keeps
  `dispatched_at IS NOT NULL`, so neither "never dispatched" nor "cancelled by a sibling" can
  settle a field. (2) The pending-release moved off the settlement-fold table entirely, into
  `pending_provider_operations_sql`. This killed a production break: Exa's `request_fingerprint`
  is job-scoped (`observation_window=f"entity-research-account:{job_id}"`,
  `entity_research_provider_wiring.py:310`), so a retry re-dispatches the *same* operation ref;
  a zero-cost pending-release fold would then make `_fold_settled_spend`
  (`entity_research_tools.py:1732`) raise `provider settlement replay differs from its immutable
  first fold` on success — suspending the job and losing the spend. It also removed the wrinkle
  where a stale fold plus a fresh dispatch stamp read as terminal before any result landed.
  `test_a_cancelled_members_pending_release_is_not_an_attempt` covers all of it; its bare
  (no `ON CONFLICT`) retry-settlement INSERT is the regression guard against reintroducing a
  pending-release fold.
- **`failed()`'s own call path is still not driven end to end by a test** — the R9 harness seeds
  no tool-request/provider-operation rows, so the test writes the durable batch/member/`failed`
  event rows itself against a real tool request.
- **The contact lane's `_pending_refs` (`contact_entity_research.py:~880`) was left alone.** It
  keeps the result/fold-only predicate, so a contact member cancelled before dispatch still
  blocks — pre-existing behaviour, out of scope, worth its own task.
- **Unknown spend is folded at zero cost.** `spend_outcome_unknown` means the provider may have
  charged; the fold marks settlement but adds nothing to the job/run spend counters.
- **Upstream cause not fixed.** Exa truncated the hex field aliases (~80 chars). Shortening the
  alias scheme would change every request fingerprint and was out of scope.
- No commit, no live-DB mutation, no service restart. All DB tests ran on the throwaway
  `clue_exa_diag_checks`.
