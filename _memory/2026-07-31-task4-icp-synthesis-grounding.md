# Task 4 — ground ICP synthesis in the conversation + product gate + typed not-ready (2026-07-31)

Branch `platform/clue-trial`. Phase-B (Stage-0 honesty) item of the structured-output repair; the
failure chain is in `_memory/2026-07-31-stage0-structured-output-failure-chain.md`.

## What was wrong (re-verified before changing anything)

Behavioural probe against the pre-change tree (throwaway DB), zero-evidence client:

- `synthesize_icps` returned `list[ICPProposal]` — 1 proposal, `label="Primary ICP (synthesized)"`,
  `rationale="Deterministic floor proposal derived from the Client Knowledge Base."`,
  `justifying_claim_ids=()`. The generic floor was indistinguishable from a real proposal.
- No statement lineage existed on the proposal shapes at all.
- `Stage0Trial.synthesize_icp_proposals` neither checked the product gate nor read any statements,
  while `confirm_icp_proposal` did enforce the product gate.

## What changed

1. **Two evidence species at the synthesis seam.** New typed input `ProjectStatement`
   (`statement_id` + `route_key` + exact `quote`) flows through `synthesize_icps` /
   `synthesize_icps_with_proposals` / `_synthesize`. Quotes reach the bounded LLM prompt
   (`project_statements` in the user payload + a system-prompt rule that they are the client's own
   words and are equal-standing evidence) and the floor's pack matcher. Lineage stays
   **reference-only**: every element synthesis emits gained `justifying_statement_ids`
   (`FirmographicDimensions`, `TechnographicDimension`, `CandidateSignal`, `StartingSourceProfile`,
   `RubricWeight`, `ICPProposal`). `SeedAccount` deliberately did not — M5.4 derives seeds from
   claims only.
2. **Typed readiness.** `ICPSynthesisResult` gained `status: ICPSynthesisStatus`
   (`grounded | floor_only`) + `reason_codes` (`no_client_kb_claims`, `no_project_statements`).
   `floor_only` ⟺ *no evidence at all*; a floor proposal over a real KB is still `grounded`
   (status is about evidence, not about which generator ran). With no evidence the floor is
   explicitly labelled `Ungrounded baseline (no evidence)`. `synthesize_icps` now returns the
   result rather than a list — one API carrying readiness instead of a third entry point; all
   callers updated (`toolbelt_wiring`, `scripts/02`, the trial, three test modules).
3. **Durable statement reader.** `clue_research.stage0.governed.read_statements` +
   `VolunteeredStatementRow` (joins `onboarding_input` for the `artifact_key`). The table stores
   only offsets + `quote_sha256`, so `Stage0Trial._project_statements` reads the captured artifact
   body through the artifact store and **verifies the sliced span's sha256** before using it.
4. **Product gate + not-ready rendering in the trial.** `Stage0ProductNotConfirmed(ValueError)`
   ("run /confirm-product first: …") is raised by both `synthesize_icp_proposals` and
   `confirm_icp_proposal`. A `floor_only` synthesis writes `icp-proposals.json` with
   `proposals: []`, `status`, `reason_codes`, `project_statement_ids`, and the floor under
   `not_ready_floor` — so `/confirm-icp N` has nothing to confirm. Both CLIs render "Not ready:
   <reason codes>"; `scripts/00_stage0_trial.py` now dispatches commands through `_dispatch` inside
   a `try/except ValueError` so a refused gate doesn't kill the session. The HTTP coordinator
   returns `status`/`reason_codes` and an empty `proposals` list when not ready (ValueError → 422
   via the existing `trial_app._http_error`).

## Verification

- Focused: `tests/stage0` (110), `tests/api` — green on a throwaway Postgres
  (`clue-postgres-task4`, host port 5441). Full `pytest -q` green after a schema reset.
- `ruff check` / `ruff format` clean on changed files; bare `mypy` (the `make typecheck` gate)
  green. No migration needed — `volunteered_statement` already had everything.

## Caveats / follow-ups

- `SynthesizeIcpsOutput` (the agent-facing tool result) still exposes only `proposal_count`; adding
  `status` there is a pinned tool-contract change (`synthesize_icps@1`) and was left alone.
- `read_statements` defaults to `route_kind=project_state`; other route kinds are readable but
  unused today.
- DB test isolation: `tests/sources/test_waterfall.py` and `tests/toolbelt/test_runner.py` fail with
  `SourceManifestRedefinitionError` on a database that has accumulated committed source manifests
  from an earlier full-suite run. Reset the schema (`DROP SCHEMA public CASCADE; CREATE SCHEMA
  public;`) before a full run. Pre-existing harness behaviour, unrelated to this task.
