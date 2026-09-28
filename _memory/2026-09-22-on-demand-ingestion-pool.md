# On-demand ingestion pool

User authorized plan and implementation of an ingestion-only pool that starts on demand,
using four workers with ten image-analysis slots each, isolated from primary fleet work.
No need to preserve in-flight development ingestions. Plan:
`docs/superpowers/plans/2026-09-22-on-demand-ingestion-pool.md`.

Implementation uses the existing fleet queue/leases and a separate coordinator slot to
avoid parents occupying all image-worker capacity. Local process deployment first; do
not claim hardware/provider-account isolation from processes alone. Verification uses
mocked model calls and the isolated San Diego test database; no paid backfill authorized.

## Implementation and verification

- Primary and embedded design workers now require `kind=agent_turn|web_turn` in the
  atomic fleet claim. Coordinator requires `ingestion`; image workers require
  `asset_analysis`. Required capabilities are opt-in; existing optional hints retain
  their semantics. The tagged design envelope gained a per-image shape, no migration.
- Each image is a durable child keyed by workspace, parent job/generation, asset and
  target fingerprint. It reuses the existing analyzer and cache with concurrency one.
  Parent generation plus live child lease fence writes. Failed terminal tasks clear
  stranded description status rather than hanging parent progress. Spend uses the
  child's fleet UUID; no provider/model configuration changes.
- Controller uses a per-database session advisory lock; one coordinator plus four
  image processes, ten slots each, two-second polling, sixty-second idle shutdown.
  Child crash replacement backs off; owned process groups stop on controller loss.
  `scripts/dev_stack_san_diego.sh restart-ingestion` starts/restarts the controller.
  Operations and scope: `docs/runbooks/ingestion-pool.md`.
- 57 root regressions passed on `clue_san_diego_assets` / Redis 65170, including four
  real OS processes reaching a forty-party mocked-provider barrier, one image/call,
  required SQL routing, stale parent/child fences, failed-child reconciliation,
  crash replacement, replay identity and idle/wakeup behavior.
- 94 API tests passed; one opt-in paid live test skipped. Covered website, PDF,
  uploads, ads, enrichment, descriptions and ingestion jobs. TestClient now hosts
  distinct coordinator/image workers to preserve injected capture/storage/provider
  fixtures; the production API still drains only turns.
- Real controller CLI smoke used a fresh migrated temporary database, disabled
  describing and an asset-enrichment job. Verified one coordinator + four image
  processes, honest failure when analysis is disabled, both fleet tasks settled,
  then zero execution children. Temporary DB removed. Logs under the temp directory
  `clue-pool-smoke-psk387_8`; script `/tmp/san-diego-ingestion-pool-smoke.py`.
- Focused Ruff/format, mypy on changed substrate/fleet files, shell syntax and whitespace
  checks passed. All 28 import contracts kept. Full monorepo suite not run.
- Development failures fixed: moved cache helper initially omitted its settings import;
  DB-test cleanup needed explicit asset deletion before workspace deletion; an old
  concurrency assertion expected 15 rather than 40. One API description test observed
  16/17 calls when run concurrently with the forty-slot load suite; the exact cause
  was not established. Sequential final API run passed all tests; the assertion now
  includes description progress diagnostics on any recurrence.

## Live activation / closing state

- Verified process cwd before replacing only San Diego's primary workers and design
  API. Frontend/platform twins unchanged. Design 8013 and platform 8023/8033 return
  OpenAPI 200; frontend 3033 remains up. No new listener port or other-workspace conflict.
- Design API PID 29558; primary worker PIDs 29185/29186/29187/29188, three slots each;
  controller PID 29559, configured four image workers x ten slots, idle with no children.
  Startup logs contain no errors. `.runtime/processes.json` refreshed; verify PIDs again
  before future operations. Logs use `/tmp/san-diego_*`.
- The old 54 queued / four claimed entity-research test rows have no live leases and
  remain untouched; fourteen old running ingestion rows have no work_id and are not
  execution backlog. No fresh provider spend or historical regeneration performed.
- Local processes share host/DB/Redis/provider account. Hard CPU/memory/provider-quota
  isolation and cloud deployment remain infrastructure work. Existing synchronous
  `describe-assets` maintenance and platform ICP/persona synthesis are outside this
  brand-ingestion pool; normal queued brand/image ingestion uses it.
