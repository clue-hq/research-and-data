# 2026-09-01 — ARV2 R0 foundations plan authored and ratified (planning session, docs only)

Founder (Shashank) ratified the R0 plan for the ARV2 research-lane rebuild. The plan is
**`docs/specs/ARV2-R0-foundations-plan.md`** — read it before doing any R0/R1 work; this note is
only the session record.

## What happened this session

- Six parallel Fable study agents swept this branch (`integration/design-improvement`, worktree
  `semarang`): composition roots + entity-research lane, gates/judges/guards, Stage-0 recon +
  memory composition, claim store + providers, frontend read layer vs the new dummy frontend
  (`/Users/aryankeshri/conductor/repos/clue-frontend`), and the 128-commit delta vs
  `origin/platform/comprehensive-account-contact-research`.
- Load-bearing claims re-verified first-hand before writing the plan: the two kill-switch
  inversions (`stage0/interview.py:746-754`; `sumble_claim_materialization.py:159-181`), the
  unconditional C7 read gate (`research_view_governance.py:327-337`), flag defaults
  (`settings.py:112/232/266/357/492`), the R11 DEEP-slot bridge (`run_composition.py:555-561`),
  the R1 quarantine list (`entity_research_quarantine.py:49-61`), and the head-of-abm v37/v38
  catalog version collision between the two branches (diffed directly — same numbers, different
  contents).

## Decisions recorded (see the spec for full context)

1. Base branch: keep this line, MERGE comprehensive in (not cherry-pick, not rebase). Pre-merge:
   re-mint comprehensive's head-of-abm v37/v38 → v41/v42 and recipe v17/v18 → v20/v21; then one
   `alembic merge`; ~12 shared-file resolutions. Needs Aryan's sign-off (his branch).
2. Quarantine by flag + five named surgical edits (both inversions, readiness floor, lane gates,
   the Exa cost-overrun suspend → record-only). No DB schema changes; waterfall quarantined not
   deleted; write gate + human gates kept.
3. v1 drops scoped memory from composition (`CLUE_MEMORY_ENABLED=false`; durable project context
   replaces it) and retires Stage-0 fast/background recon (research-agent `.md` pipeline instead).
4. Dummy frontend is presentation truth; accounts feature re-lift from `clue-frontend` repo; ten
   contract gaps need founder rulings; serving strategy = keep `/frontend/v1`, map to display
   shapes inside the frontend repository adapters.
5. Division of labor: Shashank — platform deepagent/onboarding/ICP/project context/Exa MCP;
   Aryan — ARV2 lane productionization + accounts FE/BE integration.

## Open items / not yet done

- Step 1 of the checklist (joint base-branch ratification with Aryan) is the unblock for
  everything else. No code was changed this session — docs only.
- Compliance-floor keep/remove decisions (pre-spend gate, identity binding, use gate, DSAR) are
  flagged for an explicit founder ruling, recommendation = keep all four.
- `claim.signal_priority` does not exist — the PoC's P1/P2/P3 ranking needs a small migration,
  scheduled for the ARV2 lane, not R0.
- The subagent study reports live in this conversation only; the spec captures everything that
  matters from them.
