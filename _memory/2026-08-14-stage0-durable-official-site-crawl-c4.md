# Stage-0 durable official-site crawl C4

Date: 2026-08-14
Branch: `platform/onboarding-integration`
Outcome: C4 implemented, reviewed, verified, and ready for C5 composition; production crawl
scheduling/onboarding activation remains intentionally absent.

## Durable boundary delivered

- `DurablePageAcquirer` commits `prepared` and `dispatched` before one `PageFetcher.fetch_one`
  invocation, records bounded body-free result metadata, then persists the successful body.
- Recovery has separate typed entry points. `retry_persistence` and `resume_persistence` cannot
  fetch; `reconcile` may only call a provider operation-lookup capability for the original durable
  operation key. Missing lookup support quarantines instead of redispatching.
- Provider success followed by storage/DB failure raises
  `AcquisitionPersistencePendingError`, retaining bytes for persistence-only replay. A staged
  PB-B2 blob supports a fresh-process replay. A committed snapshot whose page-completion update was
  lost is reused under a fresh fence and is not duplicated.
- Provider success whose body was never staged, or whose staged artifact is missing, erased, or
  tampered, becomes `provider_success_artifact_unrecoverable` quarantine. A transient storage
  backend outage remains retryable persistence work.
- A crash after dispatch becomes `spend_unknown/reconciliation_pending`. Recovery without a
  supported lookup quarantines while preserving `spend_unknown`; lookup results follow the frozen
  success, retryable-no-spend, ambiguous, permanent, robots-refused, or policy-refused transition.

## Artifact, provenance, privacy, and DSAR

- Successful bytes use PB-B2 `artifact` rows and workspace/content-SHA storage keys. PostgreSQL
  retains only metadata and references. Identical bytes from distinct URLs share one blob/artifact
  but retain distinct URL snapshots and provider provenance.
- Provider receipts are recursively bounded by depth, item count, string size, and 16 KiB encoded
  size. Credential/body/header/cookie/token-shaped keys are removed before PostgreSQL. The provider
  request ID remains in its typed column if the optional receipt is omitted for size.
- `evidence_reach(workspace_id, crawl_run_id?)` returns body-free run, attempt, snapshot, and
  artifact references, scoped fail-closed to the workspace/run. Tests prove neighboring workspace
  exclusion.

## Files and review disposition

- Added `official_site/artifacts.py` and `official_site/reconciliation.py`; extended the C1
  persistence claim to admit the narrow `persisted` snapshot-before-completion crash boundary.
- Added the provider-free C4 source guard and the real-Postgres crash/recovery/provenance suite.
- Added `scripts/15_official_site_c4_live.py` and the binding C4 acquisition contract; parent C0-C4
  status docs now identify C5 as the next slice.
- Final sweeper review removed a redundant stored completion flag and unused recovery reads, kept
  transient storage outages distinct from permanent artifact loss, and confirmed no unresolved
  C4 P1/P2 issue. Exact-line review initially made a transition tuple look malformed because two
  command outputs were concatenated; the source was correct. The resulting review still added the
  missing five-case non-success reconciliation matrix.

## Verification

- Focused C4: 14/14 pass on fresh DB `clue_c4_official_site_20260814_focused`.
- Complete C0-C4 official-site subsystem: 117/117 pass on the same separate focused DB.
- Alembic: one head `6e7ba5968751`; clean isolated upgrade, downgrade to `da5f3fe5a90f`, and
  re-upgrade succeeded.
- Static gates: Ruff format/check green; mypy green across 651 source files; import-linter 25 kept,
  0 broken; `git diff --check` green.
- Repository-wide diagnostic on separate DB `clue_c4_official_site_20260814_full` reached 100% and
  reported 35 failures. Three reproduce independently and are outside C4: missing materialized
  Stage-0 skill resource, the existing clue-design direct-logging exclusions, and an agent-context
  fixture with no current-user instruction. The other 32 include three destructive migration-test
  failures followed by downstream database/schema/registry-state failures, matching the known
  suite-order contamination pattern. The isolated C4 and complete official-site gates remain green.

## Retained live evidence

Untouched live database: `clue_c4_official_site_20260814_0628`
Artifact root: `/private/tmp/clue-c4-official-site-20260814-0628-live-artifacts`

- Firecrawl: run `9886bc95-bde4-41ed-adb2-0bdc26954c37`, attempt
  `20e3a4d3-cb7d-432b-9b7d-995f38c137be`, snapshot
  `15d3f247-7ff7-4f3c-abe8-612135c7ddbe`, one fetch, `persisted/fetched`,
  `spend_confirmed`, SHA-256
  `7f8c26a916385719500fb8b9d2f7412826aae41d075ffb8e25d37678abd687aa`.
- Scrapling: run `40ed72ce-69d1-404c-a9cc-5724772a73d6`, attempt
  `a839ff46-0c97-410b-b140-2da00f341d5a`, snapshot
  `b4b2ebb8-9ca6-4175-97da-90289068c4fd`, one fetch, `persisted/fetched`, `no_spend`,
  SHA-256 `ff67a9d764d6a2367a187734e697f6a53217db9a21c101d410a113ca871a299d`.
- A final body-free DB query found exactly one snapshot for each attempt, and `shasum -a 256`
  matched both content-addressed filenames. The live DB was not used for regression tests.

## C5 handoff

C5 must own the bounded PostgreSQL worker pool, operation-key generation, heartbeat/reclaim,
priority and depth expansion, C2 response/link policy, and claim routing. It must not fetch from a
persistence/reconciliation path, cancel an ambiguous paid call at the fast deadline, branch on
provider names, store bodies in PostgreSQL, or collapse URL provenance when blobs deduplicate.
