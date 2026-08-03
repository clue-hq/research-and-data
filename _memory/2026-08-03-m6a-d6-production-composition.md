# 2026-08-03 — M6A D6 production composition

## Final state

- Branch: `platform/c8-exa-sumble-discovery`.
- Implementation commit: `bddca66` (`feat(discovery): compose live Exa D6 acquisition`).
- D6 status: `PASS`; acceptance record is
  `docs/specs/M06A-D6-production-composition-acceptance.md`.
- No Sumble gap-filling or contact-discovery slice was implemented.

## Implementation

- Added the confirmed-ICP -> stable `DiscoveryPlan` / closed `DiscoveryBatch` compiler and
  `ExaWebsetsDiscoveryStarter` production seam.
- Production fleet composition now originates missing durable Exa work, while the prior D3 worker
  reconciles operation wakes and D4 materializes terminal results.
- `DurableDiscoveryPhaseHandler` never holds its transaction across provider I/O and cannot use the
  legacy empty-channel fallback when a starter is configured.
- Added separate default-off spend authorization:
  `CLUE_EXA_WEBSETS_ACQUISITION_ENABLED`. Lifecycle may drain with acquisition disabled;
  acquisition also requires the lifecycle worker and API key.
- Default D6 cap is two company rows, LinkedIn URL + revenue band, 28 credits / 12.572 internal
  cents. Email/phone are explicit opt-in and reserve 48 credits / 21.552 cents.
- Preserved the scoring bypass: committed `SCORING` phase, no fit/intent scores, then Exa-criteria
  selection and human checkpoint.
- Live D6 exposed a D5 seal-readiness omission for item-artifact-linked discovery provenance
  claims. Readiness now unions those claims with field-resolution claims; a real-DB regression
  covers it.

## Live acceptance

- Dedicated DB: `clue_d6_acceptance_20260803`; migration head `3f41f54d6238`.
- Project run: `957f34e1-f426-5d10-95db-75f7ce1187a7`.
- Batch: `5f48fda5-c72e-546d-8699-fd90ee701356`.
- Operation: `e7d6a220-7468-4451-a0d2-4af24dc00b24`.
- Exa Webset: `webset_01kz3bczvnsh1svtzv4xg3psc8`.
- Charged: 28 credits / 12.572 internal cents.
- Result: 2 accounts, 10 provider page receipts, 11 sealed claims, 14 field resolutions
  (`11 resolved`, `3 confirmed_missing`), one signature-verified replay of a current provider event
  through the production webhook ingestor.
- Seal: `08de49006f1c352762d44acffc5c3136a066ab7afcdaa80df6a578f056bd8625`.
- Fresh-process replay returned the same accounts/manifests/seal with zero create, lookup, poll,
  item-page, or event-page calls.
- Local report: `.context/discovery-fixtures/d6-acceptance/d6-replay-report.json`.

## Honest scoring-bypass outcome

- Both accounts had `yes` for all three required Exa criteria.
- New Jersey Brain and Spine: industry and revenue confirmed missing.
- Michigan Head and Spine Institute: industry confirmed missing; revenue resolved.
- Durable checkpoint: `selected=0`, `hold=2`, `excluded=0`; project remains paused; numeric score
  claims = 0; no account entered `DEEP`.
- Do not weaken the policy or fabricate selection. The later Sumble gap waterfall owns these
  terminal gaps. A database test separately proves selected -> human approval -> DEEP and rejects
  approval of held rows.

## Verification

- Fresh dedicated regression DB: `clue_d6_regression_20260803`, migrated base -> head.
- D2-D6 + scoring-bypass + production-composition suite: 87 passed.
- Ruff: all tracked Python files pass; every D6-touched Python file is formatted.
- mypy: 471 files, zero issues.
- import-linter: 24 contracts kept.
- Repository-wide gate remains non-green for baseline issues: 14 untouched formatter files and
  seven reproducible tests outside D6 (one stale agent tool digest, three old harnesses incompatible
  with the D5 checkpoint trigger, one stale Sumble tier expectation, one memory-boundary test, and
  one secret-shape fixture). Four additional failures from the first full run disappeared when the
  failing set was rerun without the loaded `.env`/ordering contamination.

## Next boundary

- D6 is closed. Do not repeat the live Webset for this exact run.
- Next approved work should use the later Sumble account-gap slice for only held/high-confidence
  accounts, preserving both providers' claims and field-specific conflict policy.
