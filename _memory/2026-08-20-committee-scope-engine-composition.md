# The engine composes the committee buying-unit scope (2026-08-20)

Scope, by founder ruling: **`discover_buying_committee` and its `AccountBuyingUnitScope` only.**
A separate session sweeps the other tools. Findings elsewhere are noted, not fixed.

## The live failure

Run `dc86340f`: `discover_buying_committee` called 8× across 3 accounts; **7 died at the Pydantic
input boundary** — `{"location":["buying_unit_scope","evidence_refs"],"message":"Field required"}`
/ `semantic_tool_input_validation_failed`. No provider call, no operation row, no spend. Greater
Chicago (`2f54953b`) burned its whole 900s runtime budget on four of them. The 8th was well-formed
and hit a real Sumble 402 (credits, unrelated). Verified in the dev DB from
`entity_research_agent_event.payload_json`; both payloads are copied verbatim into the test module.

## What changed

1. **`AccountBuyingUnitScopeRequest`** (new, model-facing, every field optional) →
   **`AccountBuyingUnitScope`** (unchanged durable shape, now its *subclass*: complete scope IS a
   valid request, so a model that still sends everything keeps working). `DiscoverBuyingCommitteeInput.
   buying_unit_scope` is the request type with `default_factory`, so the whole object may be omitted.
   The durable field *set* is untouched — `scope_sha256` is over `model_dump(mode="json")`, so
   requiredness may relax but a new/renamed field would break every historical replay.
2. **`resolve_account_buying_unit_scope(conn, request, requested, workspace_id)`** in
   `sumble_entity_research_tools.py`, called at the top of the committee action's `execute`:
   - `scope_id` = `uuid5(ns, tool_call_id)` — **always engine-derived, a model-sent id is ignored**.
     Live, one invented uuid rode four attempts on one account; had two passed validation the second
     would have silently had no scope row (→ `committee_scope_missing_or_ambiguous`).
   - `account_entity_id` ← `request.target_entity_id` when omitted; a *declared* foreign id is
     preserved so both existing refusals still fire.
   - office ← the account's own `core.hq_location` current claim (`raw`/`city`/`region`/`country`),
     but only when the model declared **no** geography at all. `business_unit` is never filled (it is
     the one discriminator that still narrows admission).
   - `evidence_refs` ← the HQ claim (the office's lineage) + this job's persisted result refs, in
     creation order, deduped, capped 20 — only when the model sent none.
   - **Replay is durable-first**: a scope already stored for this `tool_request_id` is returned
     exactly as stored, so historical scopes replay byte-identically regardless of claim drift.
   - `_bounded_office` relaxed to `same_office_strict` only — under `company_wide` geography vetoes
     nobody, and an account with no evidenced location must not force the engine to invent one.
3. **`description=` on every field** of both models (shared constants so request/durable can't
   drift), plus a JSON-schema guard test that fails the build on an undescribed field.
4. **Refusals carry the repair.** `semantic_validation_error(error, schema=...)` adds a
   `correction` per detail when the schema exposes `validation_correction(loc)` (registration, not a
   tool-name special case). `evidence_refs` uniqueness/format moved to a *field* validator so the
   location names the field. Two `_persist_scope` model-input raises re-typed from the suspending
   `EntityResearchResultIntegrityError` to a recoverable `EntityResearchGovernedRejection`
   (`committee_scope_evidence_outside_job`), and a malformed ref can no longer crash `UUID(...)`.
5. `AccountResearchExecutionGuard.authorize_tool` admits an omitted/empty scope; a **declared**
   foreign account still refuses, and the message now names the account to use.
6. Manual `v3` committee section rewritten (call shape, scope-is-composed, new refusal codes).

## Decision: evidence_refs unavailable

No result and no current claim → `evidence_refs=()`, **persisted**. The empty list in `scope_json`
IS the audit trail (it rides `scope_sha256` into the job state digest) and a
`committee_scope_evidence_unavailable` warning is emitted. Not a refusal: an account whose every
field was borrowed still owes its committee attempt. Nothing is fabricated.

## Tests

`tests/api/test_committee_scope_engine_composition_db.py` (17). Red-proofs captured by reverting
production code: seven-failure payload → `ValidationError` at HEAD; passthrough resolver → 7 fail;
no replay adoption → both replay tests fail; reverted `semantic_validation_error` → both Change-3
tests fail; reverted guard → guard test fails; a description stripped → schema guard fails; the
foreign-ref raise re-typed to integrity → recoverability test fails.
Fixture updates: 5 existing committee scopes used non-uuid `research-evidence:` refs (which
`_persist_scope` would have crashed on) → real uuids; the R4 schema-feedback test now asserts the
`correction`. Green: r5_db, committee inference/floor, tests/agents, comprehensive execution.

## Noticed, NOT fixed (other tools — the sweep session)

- Every other provider tool still gets the bare `semantic_validation_error` (no corrections); the
  seam is now per-schema opt-in, so adding one is a `validation_correction` classmethod each.
- `AssessAccountCoverageInput` / `InspectAccountEvidenceInput` /
  `RecordCommitteeRoleInferencesInput` / `FinalizeAccountResearchInput` carry **no** field
  descriptions at all.
- `InspectAccountEvidenceInput.result_refs` and `FinalizeAccountResearchInput.coverage_ledger_ref`
  are plain `NonEmptyStr` with no format validation; their consumers parse uuids behind prefixes.
