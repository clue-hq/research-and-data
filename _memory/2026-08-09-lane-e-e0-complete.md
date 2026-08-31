# 2026-08-09 — Lane E slice E0 COMPLETE (L1 fix + prose field packs + empty-state proof)

## What landed (charter `docs/specs/FI-lane-E-on-completion-synthesis.md` §5 E0)

1. **L1 fix** — `ResearchSectionKind.VALUE_NARRATIVE` added to `ACCOUNT_SECTION_ORDER`
   (`narrative/research_views.py`, after INSIGHTS / before COMMITTEE — the one Lane-E-permitted
   edit in that file). Red-proofed: pre-fix, a VERIFIED `account.value_narrative` candidate raised
   `section_not_allowed_for_subject:value_narrative` (the whole-view 404). Guard regression kept:
   a routed-but-unordered section (EVIDENCE for accounts) still fails closed.
2. **Prose field pack** — new module `subsystems/research/clue_research/narrative/prose_fields.py`
   (own module per demarcation §2.5, NOT `fields.py`): `account.summary` + `contact.overview`,
   both `value_type=object`, `tier_plan=()`, `pass_kind=DEEP`, `gate="faithfulness"`,
   `single_source_sufficient=True`, `corroboration_min=1`, 90d TTL, **TENANT_PRIVATE declared**,
   **PROJECT_NEUTRAL**; routes → ACCOUNT/SUMMARY and CONTACT/SUMMARY, `subject_current` +
   `neutral_or_exact` (deliberately opposite the narrative's pinned/exact route). The shared
   `_PROSE_SCHEMA` `required` set: `paragraphs` (minItems 1), `prompt_version`,
   `synthesized_from_job_id`, `research_outcome` (enum completed|needs_review — §7-D1 stamp),
   and **`project_id` nullable — the §7-D2 day-one slot, always null while neutral; do not
   "simplify" it away**. Exported from `narrative/__init__.py`
   (`ACCOUNT_SUMMARY`/`CONTACT_OVERVIEW`/`PROSE_PACK`/`PROSE_FIELD_KEYS`/`load_prose_pack`).
3. **Wiring** — `load_prose_pack` appended idempotently inside
   `clue_api.narrative_wiring.register_narrative_wiring` (PF-7). Both production processes call it
   (`fleet_main.py:401`, `projections_main.py:59`) so route rows exist in both — zero
   composition-root edits.
4. **D-10 empty-state proof at the composer** — with zero prose claims, account SUMMARY +
   VALUE_NARRATIVE and contact SUMMARY render `availability=UNKNOWN`,
   `reason_codes=("unresearched",)`. The account case was red-proofed against the pre-fix
   composer (VALUE_NARRATIVE section absent → StopIteration).
5. **D4 visible contract change carried into the executable fixture** —
   `tests/fixtures/research_views/account_view_manifest.json` gains the `value_narrative` section
   (owner claim_derivation, block value_narrative); `test_account_fixture_covers_the_current_
   frontend_species` set updated; `_compose_account_fixture` gains a VALUE_NARRATIVE candidate
   (statement count 4→5). NOTE per charter: recording D4 into
   `apps/frontend/docs/api-contracts/accounts.md` is the FI-2 agent's edit, NOT Lane E's — flag
   at integration, do not edit that file from this worktree.

## Verification (all on throwaway DB clue-pg-lima-v1:55060, fresh schema)
- TDD: L1 composition test watched RED (exact defect reason) → GREEN; D-10 account test watched
  RED against reverted composer → GREEN; prose-pack tests watched RED (ImportError) → GREEN.
- Suites green: tests/narrative (incl. new test_prose_fields.py), tests/unit/core,
  tests/api/test_narrative_wiring.py; wider sweep tests/api + tests/integration +
  tests/claimstore green except ONE pre-existing failure
  (`test_agent_registry_wiring::test_resolved_snapshot_materializes_through_c61_backend`,
  `WorkspaceSecurityError: workspace parent directory does not exist` — fails identically at
  baseline via stash-check; environment/filesystem issue in clue_agents, unrelated to Lane E).
- `make db-smoke` green on clean schema; single alembic head `9398ae4467e3`; no migration minted
  (field registration is rows, not schema). `make typecheck` (584 files) + `make contracts`
  (25 kept/0 broken) + ruff clean on all touched files.

## Process note (user directive mid-session, now in global memory)
E0 was implemented inline by Fable — a violation of the standing "Opus implements, Fable
plans/reviews" rule; the user re-issued it mid-session. **E1/E2/E3 must be implemented by Opus
subagents** (Fable writes the brief + reviews). Global memory updated
(`opus-subagents-fable-orchestrates.md`).

## Next: E1 (the seam + account.summary)
- `narrative/prose.py` (evidence read → prompt → parse → claim+support → judge), born with
  `judge: FaithfulnessJudge | None` (A+B contract, on this branch since `97db79f1`);
  `synthesize_entity_prose@1` tool; `ProseSynthesisStep` post-`reconcile` in the account fleet
  handler; A9 key `uuid5(LANE_E_NAMESPACE, f"{job_id}:{field_key}")`; fail-soft; supersede key
  `(entity, field, workspace, project_id=None)`; outcome gate {completed, needs_review}, never
  cancelled. Acceptance suites run with `CLUE_VERIFICATION_ENABLED` both true and false.
