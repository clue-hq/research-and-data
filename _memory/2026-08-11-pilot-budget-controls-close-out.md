# 2026-08-11 — Pilot budget-controls toggle DONE (`platform/pilot-budget-controls`)

Founder ruling: pilots never see cost numbers; nothing stops a pre-approved action on budget;
spend recording stays complete (provider consoles own hard control). Shape ratified: silent
internal estimate kept for approval integrity; presentation + enforcement off.
Spec: `docs/specs/FI-pilot-budget-controls.md`. Branch cut off Lane F head `642064e6`
(Lane F branch frozen as reviewed); commits `f207ba16` (spec) + `910707da,13c223d9,eb2f9ba9,
faec5b10` (core) + `da669e4a,65f61d55,1ec63362` (fix round 1). Nothing pushed.

## The flag

`Settings.budget_controls_enabled` / `CLUE_BUDGET_CONTROLS_ENABLED`, default **true**
(today's behavior). Pilot deployments set `false`. Deployment-scoped (restart applies), same
caveat as `CLUE_VERIFICATION_ENABLED`.

## OFF-mode semantics (all record-only, never authority-off)

- Gate: `max_spend_cents` still computed + stored on the immutable gate row; withheld from
  tool results (AMOUNT_WITHHELD "" — forced by the v23 profile's pinned output_schema_sha256;
  even a docstring change moves the digest) and served `null` on the gates route.
- Launcher: caller `expected_estimated_cost_cents` ignored; the gate's
  `expected_subject_sha256` directive-digest binding remains the stale-approval guard (proven
  still-refusing). Gate-answer amount-echo check inert; digest check armed.
- R9 admission (`DbEntityResearchToolBatchCoordinator.admit`) admits past job/run caps, both
  fleets; reservation/settlement rows unchanged.
- M7.5 project-run budget pre-gate never pauses a phase.
- Sweep-found refusals gated the same way: `require_provider_spend_capacity`
  (`durable/provider_spend.py` — money comparison only; lock/ACTIVE/authority checks intact;
  threaded by injection through 7 durable wrappers / 8 API services / ~14 composition sites),
  Exa Websets discovery preflight headroom, Stage-0 reverse-profiling budget pause
  (`budget_exhausted` still recorded in the payload). BUDGET_STOPPED unreachable.
- Left ON deliberately (shape, not economics — orchestrator-ratified): depth/fanout envelopes,
  waterfall/planner/spawn/committee/agent-plan ceilings, canary/quality suspension, M9.1
  authority gate.
- Frontend: `chat-gate.ts` `max_spend_cents` nullish (null, never ""/0 — `parseCentAmount("")`
  would render a fabricated $0.00); gate-card answerability keys on the subject digest alone
  (a required-amount check would have made every pilot gate permanently un-approvable — found
  and fixed in round 1); no cost row rendered when withheld; contract note in
  `apps/frontend/docs/api-contracts/projects.md`.

## Verification

19/19 dedicated both-states tests + stage0 handler; frontend 140/140 + lint + build; ruff /
mypy 630 / lint-imports 25 clean; Lane F acceptance green at fix head; provider-spend consumer
suites (12) green; whole-repo failures triaged byte-identical to BASE (pre-existing dev-.env /
shared-DB baseline). No migration; no tool descriptor digest moved.

## Known trades + residuals

- Client cannot distinguish "amount withheld by policy" from "durable amount read failed";
  the failure case renders an answerable card whose approve the server refuses
  (`GATE_AMOUNT_STALE`) when controls are ON — server-authoritative by design, documented at
  the code site + contract doc.
- Stale fixture/doc nits (frontend repo): `chat-gates.repository.ts` header docstring;
  `chat.fixture.ts` hardcoded amount (fixture mode always shows a cost) — frontend-owner
  cleanup.
- Merge order into `platform/frontend-integration`: Lane F first (`platform/lane-f-r11-bridge`),
  then this branch (it contains Lane F's history).
