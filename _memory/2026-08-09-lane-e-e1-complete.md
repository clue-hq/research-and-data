# 2026-08-09 — Lane E slice E1 COMPLETE (the synthesis seam + account.summary)

## Process
Per the founder's directive, E1 ran orchestrated: Fable planned (3 read-only Opus seam studies →
the brief at `.context/e1-implementation-brief.md`), two Opus agents implemented (WP-A the
synthesizer, WP-B the tool/step/composition), Fable adversarially reviewed each diff and re-ran
every gate before committing. Keep this shape for E2/E3.

## Commits
- `f35e811a` — **E0 defect fix** (found by WP-A's TDD): the `_PROSE_SCHEMA` `project_id`
  type-union `["string","null"]` crashed the claimstore validator (no union support —
  `registry._SCALAR_CHECKS` lookup on an unhashable list), making both prose fields unwritable by
  ANY payload. Fixed as `{"enum": [None]}` — which *enforces* §7-D2 "always null while neutral"
  at the substrate; the PROJECT_RELATIVE flip must edit that schema line (§6.4 pairing).
- `5891813e` — **WP-A**: `narrative/prose.py` `ProseSynthesizer` — merge-winner evidence read
  over the explicit `PROSE_ACCOUNT_FIELDS` allowlist (excludes PII / `account.scoring.*` /
  `crm_relationship_status`, documented in-module), `min_facts=3` refusal BEFORE any spend,
  fenced neutral `account_summary_v1` prompt (prose-local registry; no persona/angle/client-KB —
  the neutrality property), empty-beats-fabricated `parse_prose_response`, one-txn
  claim+`claim_support` write with unconditional `supersede_claims` over the
  `(entity, field, workspace, project_id=None)` key (`claims_for` + `project_supersedable` —
  public primitives, no forbidden-file edits), optional judge per FI-M12 §3-A (None ⇒
  born-unverified + `research.prose_synthesis.judge_skipped`), status re-read post-judge.
  13 TDD tests. Exports on `clue_research.narrative`.
- `13e10c60` — **WP-B**: governed `synthesize_entity_prose@1`
  (`platform/api/clue_api/prose_synthesis_tools.py`) — everything read off the durable
  `entity_research_job` row; typed refusals in order: `prose_synthesis_not_composed` /
  `invalid_field_key` / `field_not_composed` (contact.overview until E2) / `job_not_found`
  (cross-workspace ≡ absent, WARNING-logged) / `job_not_terminal` / `outcome_not_synthesizable`
  (§7-D1: only COMPLETED+NEEDS_REVIEW of the six outcomes) / `gateway_required`; registers in
  every composition for C6 authority-set parity; authority `()`. Fail-soft
  `ProseSynthesisStep` (`prose_synthesis_step.py`) after `reconcile`, OUTSIDE the suspend try,
  never raises; gates on `finalization_receipt_ref` (finalized-this-cycle) + outcome; A9 key =
  `operation_id_from_key("lane_e_prose", f"{job_id}:{field_key}")` on `ToolContext.operation_id`
  (**the invoker's `idempotency_key` param is dead — never use it**); `PreconditionFailed` →
  info log only; other exceptions → warning + `research.prose_synthesis.failed`. Threaded
  `prose_step: ... | None = None` through the three composition layers (None = byte-identical
  pre-Lane-E handler, pinned by test); `fleet_main` builds judge under the toggle, the
  synthesizer, binds the step post-invoker (deferred-bind — the fleet composes before the
  invoker exists). 61 TDD tests incl. 12 acceptance over the real
  handler→step→tool→invoker→DB path.

## Verification (Fable-re-run, throwaway DB :55060)
- New suites green under `CLUE_VERIFICATION_ENABLED` **true AND false** (49 + 12).
- `tests/api` + `tests/integration` + `tests/fleet` + `tests/claimstore` + `tests/narrative` +
  `tests/agents` + toolbelt wiring: green except two **pre-existing** failures:
  (a) `test_agent_registry_wiring::test_resolved_snapshot_materializes_through_c61_backend` —
  also failed at E0 baseline; now surfaces a stale stage0-interview skill pin (tree ships v10,
  test asserts v9) — NOT Lane E's; (b) `tests/fleet/test_b4_composed_run_db` — cross-suite
  ordering pollution, passes in isolation.
- `make typecheck` (587 files), `make contracts` (25/0), ruff/format clean on all touched files.

## Deviations ruled (Fable)
- Tool output `support_claim_ids: list[str]` not tuple — strict ToolOutput re-validates a
  JSON-round-tripped result on journal replay; tuple could never validate. Correct.
- Third counting site `tests/api/test_agent_registry_wiring.py:117` (55→56) — brief missed it.
- Injectable `jobs: EntityResearchJobReader` on the tool — additive, keeps precondition tests
  DB-free.
- `pin_requirements=("entity_research_job",)` — free-form pin kinds are the established pattern.
- Tool's `gateway` param is redundant at runtime (only powers `gateway_required`) — kept as a
  composition-health refusal; revisit at E2.
- `prose_step.bind()` in fleet_main is unconditional even when the entity fleet is off — harmless
  (step never invoked without the fleet).

## For E2 (`contact.overview`)
Same seam: contact fleet handler post-`project()` (`contact_research_fleet.py:407` — note it has
NO try/except at all today), `ProseSynthesisServices` grows a `contact` synthesizer (second field,
same tool — `field_not_composed` refusal flips off), §4.1 SENSITIVE-facet exclusion provably out
of the prompt, binding-stamp rule (all-STRONG cited ⇒ STRONG else WEAK, merge then refuses to
serve WEAK). E3 (Positioner composition) unblocked; slice-3 gate satisfied. The A+B contract and
this seam give E3 its trigger + optional-judge pattern.
