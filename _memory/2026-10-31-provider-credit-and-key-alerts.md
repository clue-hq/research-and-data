# Provider credit and key alerts — 2026-10-31

Branch `fix/design-reference-ads` (trenton, founder: same branch), local commits only.
Spec `docs/superpowers/specs/2026-10-31-provider-credit-and-key-alerts-design.md`; plan
`docs/superpowers/plans/2026-10-31-provider-credit-and-key-alerts.md`. Trigger: the Pallet ad
onboarding where PDL answered 402 and nobody was told.

## What changed
- Classifier (`clue_core.provider_failures`): new refusals `quota_exhausted` (429/403 naming a
  quota) and `key_missing`.
- The incident recorder moved to `clue_spend.incidents` (`clue_api.provider_incidents` re-exports).
  Open events carry tag `alert=provider`; an incident nobody could send is sent by the next process
  with Sentry.
- `clue_spend.drain_provider_calls` records incidents itself, so every spend scope (design requests,
  ingestion pool, chat naming) alerts — not only the platform's ARV2 drain.
- Design-side OpenRouter refusals are incident provider `openrouter_design` (ledger rows keep
  `provider='openrouter'` — the cost views group by it).
- PDL goes through the design spend caller; Exa deep through a spend caller the coordinator opens.
- Exa Websets, Composio, Cloudflare, Clerk keep their own httpx clients and report each answer via
  `clue_spend.record_observed_call` (bound in `clue_api.provider_observers`).
- `clue_spend.key_check`: start-up check per role (platform-api, design-api, worker), only where
  Sentry is installed; a missing key opens `<role>:<ENV_NAME>` / `key_missing`. Left out: ZoomInfo,
  Clay, Apollo, BuiltWith, D&B, Firecrawl, Sumble, Parallel (dormant).

## Verification
- Targeted test files green (see the plan ledger). Pre-existing, unrelated: `test_discovery_driver`
  1 failure under the keyless wrapper; `test_exa_deep_acquisition_e1` 4 seeding failures (spine
  Project `updated_at`); lint-imports 1 broken contract (agents → gateway).
- Live on trenton: platform API + workers restarted; open `key_missing` incidents for the lane's
  blank keys (Composio, Cloudflare, Podcast Index ×2, YouTube), one Sentry event each.

## Owed
- Founder: the Sentry alert rule (spec §10); top up PDL; re-run Pallet ad onboarding afterwards.
- The advertiser-name fallback (use the brand kit's name when PDL can't answer) — separate change.
