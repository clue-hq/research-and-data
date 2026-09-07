# ARV2 roadmap — the index

**The single authoritative plan is `ARV2-MASTER-PLAN.md` (its data-source child is `ARV2-DATA-SOURCE-MAP.md`: endpoint + SQL + column behind every screen element; its product-catalog child is `ARV2-PRODUCT-CATALOG-CONTRACT.md`: Exa request shape, catalog artifact, product-set gate, the multi-product ruling; its company-overview child is `ARV2-COMPANY-OVERVIEW-CONTRACT.md`: Exa Agent request + validated schema + artifact rendering; the Track O plan is `ARV2-ONBOARDING-PLAN.md`: phases O0–O7, the synthesis agent, the remaining research contracts, decision boxes O-D1–O-D6); the founder work split is `ARV2-WORK-SPLIT.md`; Shashank's setup runbook is `ARV2-GETTING-STARTED-SHASHANK.md`; coding agents start at `ARV2-AGENT-BRIEFING.md`. Read those first; the documents below are the audit trail.**

**Updated 2026-09-05.** Presentation truth: `clue-frontend` `integration/live-backend-v1` @ `84f8ee7`. One page that says where every plan document lives, what each one decides,
and where we are. Roles: **Aryan = tech founder** (platform deepagent, onboarding, brand context,
ICP, project context, Exa MCP). **Shashank = co-founder** (research PoCs, frontend specs and dummy
frontend, the accounts integration lane).

## Where we are
- **R0 foundations — DONE** (merge of the two branches, old lane off by flag, inversions fixed,
  verification off). Remaining admin: push R0 to the shared base; rotate the two leaked API keys.
- **Next:** the founder session on open rulings, then Track D (display + frontend integration)
  starts immediately against the real Zafran claims, with Track R (the research lane) in parallel.

## The documents, in reading order

| # | Document | What it decides | Status |
|---|---|---|---|
| 1 | `ARV2-R0-foundations-plan.md` | R0: base branch, the quarantine ledger (keep / flag-off / surgical edits), flag posture, seams, checklist | Ratified 2026-09-01; executed |
| 2 | `ARV2-R0-seam-freeze.md` | The two frozen seams: the launch contract and the ICP artifact format (5 decision boxes with recommended answers) | DRAFT — needs the joint session |
| 3 | `ARV2-plan-delta-2026-09-03.md` | What the Person-Depth and One-Account runs change: R1–R4 content (AI Ark name-scoped, Apollo dropped, Gemini two-model media, contact-depth charter + coded compliance floor, the priority/outreach_safe migration), the refinements-program edits, coordination items | Proposed |
| 4 | `ARV2-plan-2026-09-04-accounts-integration.md` | **The current plan of action:** two tracks meeting at the claim store — Track D (load PoC claims → display layer → `/frontend/v1` payloads → accounts re-lift) and Track R (R1–R4); contract v1 = the port-of-spain models + backend semantics; the 13 D0 rulings on the truncation/drift list; the display-block generation policy; the operating model for a non-technical co-founder; the first ten steps | Proposed |

Background (earlier, on the chicago worktree, `docs/specs/ARV2-*.md`): the rebuild plan (provider
verdict, keep/drop treaty), the build runbook, the schema-impact audit, the Apollo / Melissa / AI Ark
contracts, the Eve decision, the sources-and-variables architecture, the smoke-test findings.
Evidence (chicago `.context/`): the sample runs v1–v3, the AI Ark canary, the cluehq.ai smoke test,
the Person-Depth and One-Account runs, the display-layer control test, the frontend-page-content
spec module, the head-of-abm refinements program.

## The stages, one line each
- **R0** foundations — done.
- **Track D** (now): D0 rulings + contract v1 → D1 migration + PoC claim loader → D2 recipes + Luna
  section runner → D3 the five payloads → D4 accounts re-lift → D5 Zafran acceptance.
- **Track R** (parallel): R1 providers → R2 account agent → R3 committee + person agent → R4
  discovery + fleet. Writes the same claim rows the loader wrote.
- **Track O** (Aryan): onboarding as research pipeline, ICP `.md` artifacts, project context,
  brand context, Exa MCP; the chat-shell output-pane motion handoff.
- **Phase 6** cleanup PR: delete the quarantined code only after D5 and the R2/R3 exit gates.

## Standing rules (from CLAUDE.md and the plans)
Dummy frontend = presentation truth, re-lift don't patch, no invented components · every flag in
`.env.example` in the same commit · contracts recorded in `docs/api-contracts` · save raw before
parse · agents never merge; the tech founder owns the four integration points (migration, loader,
read surface, composition) · no push without review · one shared base, pulled daily · one founder
ruling session a week.

## Session notes
`_memory/2026-09-01-arv2-r0-plan-ratified.md`, `_memory/2026-09-01-r0-step2-merge-complete.md`
(with the 09-03 and 09-04 addenda).
