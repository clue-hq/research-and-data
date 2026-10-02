# 2026-08-19 — explicit Account research is not tier-gated

**Branch:** `platform/comprehensive-account-contact-research-v2`

## Founder ruling

Fit/intent scores and numeric `high` / `low` tiers are prioritization metadata, not eligibility.
An attributable user turn that explicitly selects an Account, plus a research directive whose exact
scope includes it, authorizes account research and buying-committee discovery whether the signal
tier is high, low, or absent. Directive execution effort (for example `standard`) is a separate
vocabulary and does not have to equal the signal tier.

The ruling removes only tier eligibility. Exact selected scope, directive lineage and confirmation,
privacy policy, provider configuration, provider spend accounting, budget ceilings, and durable
human authority remain enforced.

## Implementation

- `compute_account_research_estimate` no longer reads `account.scoring.tier`; it resolves the exact
  per-Account effective directives and sums their immutable effort-policy caps.
- The normal account-fleet launcher and directive-confirmation gate no longer translate an absent
  or mismatched tier claim into a refusal.
- The quarantined durable `account_deep_launch` substrate no longer contains a second copy of the
  same tier predicate.
- Committee discovery's local contract language now says explicitly selected Account, not
  high-tier Account.
- The founder ruling is frozen in the comprehensive-research contract, implementation plan decision
  ledger, and the historical Lane-D contract-gap row.

## Red/green evidence

The Option-B DB acceptance fixture was changed to a mixed signal set (existing high + low) under a
`standard` effort directive. Before the implementation, the gate failed with
`account_tier_checkpoint_missing`. After the implementation:

- mixed high/low signals + standard effort complete gate -> approve -> confirm -> fleet launch;
- a selected Account with no numeric tier still receives the correctly priced confirmation gate;
- 194 relevant committee, D1-D5, gate, fleet, selected-launch, and durable-launch tests pass;
- `make lint`, `make typecheck`, and `make contracts` pass (727 typed files; 26 contracts kept).

## Preserved live continuation

The existing acceptance state remains intact: database `clue_d5_live`, frontend port `3010`, API
port `8006`, storage `/private/tmp/clue-d5-live-20260819/artifacts`, and agent workspace
`/private/tmp/clue-d5-live-20260819/agent-workspace`. The Python API/fleet processes do not use
auto-reload; only those processes must be restarted with the same environment to load the fix.
The frontend process/browser session must remain untouched. Resume the exact existing draft and
selected Account through `launch_selected_account_research@1`; no tier checkpoint action is needed.

## Committee-path continuation and live exit evidence

The exact R6 account job is now the committee path's durable human-selection authority. On that
path only, the implementation:

- accepts the outer project run while it is paused at the legacy `tier_checkpoint`;
- does not require a Pass-A scoring checkpoint, ICP must-have criteria, a tier checkpoint approval,
  or a tier claim;
- lets already-fresh Account claims serve as committee-office evidence instead of requiring a new
  provider result in the current job;
- reuses the exact sealed-discovery Sumble Organizations response when no later Account-gap
  Organizations snapshot exists, avoiding an unrelated re-purchase;
- admits the least source trust tier (`source_tier = 4`) and the least Account label (`tier4`) on
  historical claim-backed paths as well;
- keeps the exact job/account/directive, sealed-discovery membership, privacy/use policy,
  provider pre-spend authority, durable receipts, and spend accounting intact.

The preserved browser/API/fleet/database/storage instances were reused. A raw paid Sumble canary
first proved Organizations and People availability (9 credits total). The subsequent browser-driven
committee run reached real Sumble Teams and People calls: Teams charged 70 credits and People
charged 40, leaving 146 credits. The durable committee operation reached `ready`, returned two
identity-resolved members, and the account agent wrote one evidence-cited economic-buyer inference.
The final job outcome was honestly `needs_review` because two overlapping finance-office candidates
were ambiguous and one remained roleless; this is no longer a signal, tier, checkpoint, provider,
or API-credit blocker. The authenticated contacts UI rendered the inferred member with role,
confidence, and provider evidence.

The governed role claim also holds an agent-authored rationale. Per the founder's data/display
boundary, the backend Contacts read now serves that rationale as nullable
`roleOnCommittee.reasoning`, and the frontend Zod model preserves it. The existing buying-committee
table/profile intentionally renders no new field or component. A same-session browser probe of the
authenticated BFF returned HTTP 200 with `value`, `confidence`, and `reasoning`, while the rendered
page remained unchanged and contained no `Role reasoning` label.

Operational receipts retained for replay/debugging:

- entity-research job `d610683d-7b36-512b-8a9a-0afd6a69ac36`;
- committee operation `279be8c7-0f54-46c7-9672-a93c55d24c0e`;
- reused discovery Organizations operation `c87dd4fc-c53a-4c73-891f-60d092e3af00`;
- Teams request `01a01717-9596-7565-8c24-0c8df569a7e4`;
- People operation `24ada6f7-5990-4d3f-9acc-67cd186f73f0`.

## Final review and verification

The post-live review covered all changed contracts, preflight/eligibility paths, provider-spend
authority, durable readers, migration triggers, agent prompt/skill behavior, and regressions. The
scope remains exact-job-only; historical batch/deep paths retain their checkpoints and claim
lineage, with tier 4 now allowed.

- focused committee/provider/R5/R6/D5/governed-contacts suites: 89 passed;
- frontend test suite: 353 passed;
- `make lint`: passed (1,581 files formatted; Ruff clean);
- `make typecheck`: passed (727 source files);
- `make contracts`: passed (26 kept, 0 broken);
- frontend `design-system:build`, `lint`, and production `build`: passed;
- Alembic: one head; isolated scratch DB downgrade -> upgrade -> current succeeded at
  `fc3e5477e872`;
- `git diff --check`: passed.

One discarded verification attempt imported the full profile component into the plain Node test
runner; it failed on the existing CSS-module import because that runner has no CSS loader. The test
was removed rather than adding test/runtime machinery or touching the UI. The backend contract,
frontend schema retention, and no-new-visual behavior are covered by DB/API tests plus the live
authenticated browser probe.

Known display follow-up, not a discovery blocker: the chat launch card can remain visually stale at
`Queued 0 of 1` after the terminal job, even though the durable job, contacts read, and contact
profile are complete. Also retain the previously observed old-task replay-spin issue for a separate
fleet recovery slice; it did not affect this successful committee operation.
