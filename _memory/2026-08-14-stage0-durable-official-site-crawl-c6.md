# 2026-08-14 — Stage-0 durable official-site crawl C6

## Outcome

C6 is implemented and accepted in default-off, exact-workspace-allowlisted shadow mode. The
authoritative C7 materializer is intentionally absent and authoritative composition fails closed.

## Implementation

- Added one-run lifecycle with PostgreSQL-time fast deadline, persisted transition sequence,
  immutable fast/background checkpoints, cold replay, and materialization-before-fast-complete.
- Added phase blocker fencing. Durable leased/provider/reconciliation/persistence work requeues;
  it cannot publish a false checkpoint/terminal state. `fast_closing` resumes recovery claims only.
- Moved production onboarding recon off the API event loop into a reference-only fleet task.
  Existing setup start/status/replay response vocabulary is unchanged.
- Added a second reference-only fleet task for the official-site crawl. It begins only after the
  legacy fast Client-KB version is committed, so current browser release remains truthful.
- Added API-root provider composition, bounded robots/sitemap acquisition, default-off allowlist
  settings, Firecrawl credential checks, and C7 authoritative refusal.
- Added task kinds with reversible migration `93113e83bf2f`.
- High-fanout discovery now refuses overflow URL observations at the page ceiling instead of
  rolling back the fetched page's persisted snapshot.
- Added retained/replay live runner `scripts/16_official_site_c6_live.py`.
- Contract/evidence: `docs/specs/FI-stage0-durable-official-site-crawl-C6-composition-contract.md`.

## Live Firecrawl evidence

- Database: `clue_c6_official_site_20260814` on the isolated local project Postgres.
- Artifact root: `/private/tmp/clue-c6-official-site-20260814-live-artifacts`.
- Target: `https://insighthealth.ai/`.
- Final run: `94b425e6-f252-4c34-841b-a478c3467cc3`.
- One crawl run for the recon; 16 pages; 11 fetched URL snapshots; 10 unique blobs.
- Fast checkpoint: 8 snapshots. Background checkpoint: 11 snapshots. Both version 1.
- First pass correctly returned `recovery_pending` for one still-leased pre-dispatch page.
  After lease expiry the same run reclaimed/fetched it and reached `completed`.
- Five dispatched Firecrawl exceptions returned neither receipt nor request ID; recovery marked
  them `spend_unknown` and quarantined them without another provider call.
- Cold replay: same run/checkpoint IDs, zero additional attempts, 0.010 seconds.

No API keys, provider receipts, captured bytes, browser tokens, email addresses, or user names are
recorded here.

## Verification

- Focused C0–C6/setup/fleet/settings matrix: 208 passed on disposable database
  `clue_c6_regression_20260814_0840`.
- Ruff formatting/check: green across 1,379 Python files.
- Mypy: 655 source files, zero issues.
- Import contracts: 25 kept, zero broken.
- Alembic: sole head `93113e83bf2f`; clean C6 downgrade to `6e7ba5968751` and re-upgrade.
- `git diff --check`: green.
- A monolithic shared-schema pytest pass was stopped at 47% after destructive migration tests
  contaminated later tests, reproducing the repository's known shared-DB failure mode. Independent
  failures also reproduce without C6: design-subsystem logging-discipline exclusions and the
  Stage-0 skill resource fixture mismatch. No C6-focused test failed.

## Retained boundaries / C7 handoff

- C6 shadow mode performs no extraction/model call and writes no Client-KB claims.
- C7 must implement the checkpoint materializer, grounded claim provenance, and authoritative
  fast/background projection. Only then can authoritative mode and browser lineage be tested.
- C8–C10 still own product progress, observability, DSAR/retention, and rollout completion.
- Keep the live database/artifact root until evidence review; do not run destructive migration or
  broad regression tests against it.
