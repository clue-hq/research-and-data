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

