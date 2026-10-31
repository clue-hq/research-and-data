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

## Final review (fresh reviewer, 2026-10-31) — fixed
- Recorder writes run in a savepoint (a DB error no longer rolls back a drain's ledger rows).
- Design scene/site/web agents' refusals now open `openrouter_design` (recorded from the run's
  collected calls after its receipts land — `record_design_run_incidents`).
- A per-minute/per-second quota reply is a rate limit (Gemini bursts), not a first-sight refusal.
- A failed key check logs its error type only (no traceback carrying the environment).
- The review's minors were then all fixed (founder go, 2026-10-31): retried attempts are not
  reported; "insufficient" needs funds/balance and a Composio 4xx on a tool run or connected
  account is unclassified; observed rows say retry_exhausted / estimate (Websets); the threshold
  reads the incident provider and design receipts carry provider_failed: codes; PDL/Adyntel
  refusals flush the scope at once (`spend.flush_if_refused`); observing is a background task;
  the key check closes retired keys, reads the design .env + .env.local, sends any unsent alert;
  a drain logs one recorder_failed; research-card and two-writer race tests; FailureHook dropped,
  sentry-sdk + python-dotenv declared; Exa + Exa Websets share one Sentry event per outage.

## Owed
- Founder: the Sentry alert rule (spec §10); top up PDL; re-run Pallet ad onboarding afterwards.
- The advertiser-name fallback (use the brand kit's name when PDL can't answer) — separate change.

## Same day, follow-ups (founder go, 2026-10-31)
- Assets page Delete now archives on the design API (was page-memory only); archived kit assets are
  hidden on the page and skipped in the agent's kit manifest (`brand_kit_asset_manifest`).
- New agent action `asset(action="knock_out_background", node_id)` (`lumen_agent/image_knockout.py`):
  exact colour-to-alpha on a plain tile, refuses non-plain/transparent/SVG, trims, re-places in the
  same node. Founder-approved tool-description wording. Live check: Pallet's kit mark
  (asset_ing_6333fd520407e88f, white bars on black) knocks out cleanly.
- Open founder question: may the agent recolour a dark full logo to white (still forbidden).

## Production read-only check (2026-10-31, before the PR)
- Every production ad-assets harvest is unverified: PDL answered `company_identity.http_error` on all
  11 jobs (the prod PDL key needs checking). Pallet kept a person's posts (advertiser "Sushanth Raman",
  18) and Conduit AI too ("Cole Rubin", 26): both need the ad-assets onboarding re-run once PDL answers.
  Illumio, Kaseya, Proxon guessed their company right.
- Open prod incident: gemini credits_exhausted since 2026-10-28.
- public_media opens a refusal incident most weeks (14 in 30 days); keyless providers (public_media,
  live_http) are now never tagged `alert=provider`, so they never email.
