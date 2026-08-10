# FI-2 slice 3 complete — final review CLOSE, FI-2 done end-to-end (2026-08-08)

Slice 3 (the research economics, FI-2 §6/P4) closed at `1979b565` + this close-out commit on
`platform/frontend-integration`. Local commits only, nothing pushed. Single alembic head
`9398ae4467e3` (Lane B's); slice 3 added **no** migration. With this, all four FI-2 slices are
done: slice 0 (substrate), slice 1 (global-lens read layer + frontend flip), slice 2 (C7 lineage
convergence), slice 3 (economics + write-safety).

## How slice 3 landed
- Task 1 (§6.4 project-scoped supersedes), Task 2 (§6.1 account fresh-skip + zero-result close),
  Task 3 (§6.2 bundle shrink + §6.3 Sumble freshness; WIP `49f98ec5` adopted by a successor,
  reviewed APPROVE-WITH-FIXES, fix round `72f800d6..14c0c380`, re-review CLOSE), Task 4
  (canonical economics fixture `tests/integration/test_fi2_slice3_economics.py` +
  `field_species` relocation to `claimstore.registry` + third fail-closed species default).
- Final whole-slice review: **CLOSE SLICE, zero Critical.** All six per-clause fixture mutations
  independently reproduced; the A1-fixture choice, the `field_values` seam, and `_run_p2`'s
  lineage mint all ruled faithful. Relocation AST-verified pure; lint-imports 25/25.
- Ratified deviations (the only two spec↔impl divergences): estimate netting NOT implemented
  (five verified blockers; gross figure pinned by `test_fi2_62_launch_estimate_db.py`), and
  §6.2's bundle-shrink clause naming a quarantined file while the **R5 guard** is the live
  enforcement point.

## Important findings carried forward (none blocked the close)
- **I-1 — structured-path no-respend hole.** The Sumble ladder (`sumble_account_gaps.py:421-444`)
  consults confidence but never `evidence_span`; `born_complete` requires evidence but never
  confidence; the R5 `already_known` refusal covers `research_account_deep` only — the
  `enrich_account` branch has **no** borrowed-set check. A neutral fresh evidence-backed claim at
  confidence 0.7 is born-complete ("no money spent") yet Sumble-eligible → an `enrich_account`
  call re-spends. Inverse shape (0.9 confidence, blank span) refused as "already answered" while
  §6.1 expects it researched. Pre-existing ladder, but slice 3 made no-respend a shipped
  contract. **Fix before any production second-project run that uses the structured path.**
- **I-2 — Exa tier-4 refresh is bought but not served (§6.1 depends on M8D R11).** Tier-4 claims
  are born `unverified`; `MergePolicy.require_verified_tier4` withholds them; no composed run
  reaches VERIFICATION (R11 gap); `current_values` therefore never shows them, so the field stays
  stale to the fresh-skip → re-buyable every run (bounded per-run by the budget cap). Worse: the
  money buys nothing at all — first-time tier-4 qualitative research is equally invisible (the
  documented "silent blanking", `platform/api/clue_api/verification/handler.py:5-11`), and the
  slice-1 read layer's neutral facts read the merge, so none of it reaches account detail. The
  read layer's two halves also disagree: relative sections read raw claims (`<> 'rejected'`),
  neutral facts read the merge. The economics fixture pins both halves so it speaks up when R11
  lands. **§9's AC clause 4 ("stale fact refreshed once, both lenses see it") is met for
  tier ≤2 sources only** — record that qualification at spec sign-off.
- **I-3 — §6.4's committee READ half is open.** Task 1's verdict covered writes only (correct:
  no committee supersede exists). The MVP read surface scopes committee by membership + the
  account-run reference index, not `run_lineage`; only C7 reads lineage. Slice-1/2 read-layer
  work, not slice 3's — but do not record "§6.4 complete" without this caveat.

## Minor follow-ups (ledgered, not done)
- M-2: the three fail-closed species defaults are unreachable; the one *reachable* fallback is
  `default_research_scope` → NEUTRAL inside `field_species`, and `resolve_research_scope`'s
  docstring argues the opposite doctrine — wants ONE ruling. Exposure: only a hard-deleted
  relative declaration (no FK protects `claim.field_key`).
- M-3: `AccountGapReason.STALE` (`clue_core/account_gap_enrichment.py:38`) landed under the WIP
  outside Task 3's declared list — additive, migration-free; retro-note as a contract-delta.
- M-4: §6.2's parenthetical "(and the M8D provider wiring's field selection)" has no
  implementation — `entity_research_provider_wiring.py:252-271` does no borrowed-set subtraction;
  effect is over-*reservation* only (guard blocks the spend). Name it in the §6.2 amendment.
- M-5: §6.4's committee-write verdict has no pinning test (a future committee supersede would
  land silently).
- M-7: fixture asserts in-flight `observed_coverage`, not the durable
  `entity_research_account_coverage.coverage_json` (same object, one hop short of §10's
  "ledger-based").
- Second born-complete derivation in the finalization engine (`account_entity_research.py:1333-49`)
  is deliberate defence-in-depth, equivalent today — drift risk only.
- Done in the close-out commit: M-6 (`packs.py` "pre-§6.4" → open-class wording),
  M-9 (`.playwright-mcp/` gitignored).

## Founder decision list (consolidated, slice 3)
1. **Re-scope spec §11 item 3 (estimate netting):** build an estimate-*proposal* surface, net on
   both sides, and model the non-skippable committee leg (a wholly borrowed account still spends
   — the fixture settles at 1.25 for committee discovery; "account axis free" would be a *wrong*
   estimate, not conservative).
2. **Amend §6.2:** name the R5 guard as the live enforcement point; mark the bundle compiler
   quarantined-path-only; implement or delete the M8D-wiring parenthetical (M-4).
3. **C6 prompt bump rider (from Task 2):** sanction `claim:` refs as buying-unit evidence so an
   all-borrowed account's COMPLETED close is prompt-reachable.
4. **I-2 above:** record §6.1's dependency on M8D R11; qualify §9 AC clause 4 to tier ≤2.
5. **I-1 above:** fund the structured-path no-respend fix (unify the ladder's eligibility with
   the born-complete predicate or extend the guard to `enrich_account`).
6. Standing acks still open from slices 0–1: C6 profile re-pin, `hq_geo`-at-mint (GDPR consumer
   reads NULL), `logoPath` as funded backend work, the account-detail/contact-profile design pass.

## Verification state at close
Economics fixture 6/6; `tests/integration` alone 21/21; touched suites 36–49 green across
reviews; frontend_read 102/102; `tests/db` 12/12; mypy 583 clean; ruff check clean; lint-imports
25/25. Pre-existing failure set unchanged and re-attributed by three independent reviewers:
`test_agent_registry_wiring::…c61_backend` (environmental), `test_b4_composed_run_db` lease
flake (passes isolated), `test_workspace_rename_guard` (local untracked design attachments),
shared-DB pollution class, 11-file format drift (M8C/M8D-era, byte-identical to baseline).
