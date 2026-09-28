# Person research release after account import

Status: implemented locally; live acceptance not started.

## Agreed behavior

For new v4 revision-18 launches, person investigations may start once the parent account's JSON dossier and complete claim import commit. Each nominated person already has an account-authored delegation brief. Account narrative generation and finalization continue independently. Reconciliation remains on its existing account-settlement boundary.

## Implementation

- `FinishDossierTool` retains a `research_account_import_ready` artifact reference to the completed manifest in the same transaction as the import and dossier snapshot. Partial/failed imports produce no readiness reference. Repeated completion is idempotent. The reference uses the existing storage substrate; no new table or parent-row lock upgrade is needed.
- The fleet's existing sweep reads this durable readiness. Queue offers occur after its database transaction exits and reuse existing job deduplication. A restart between import and enqueue is recovered by a subsequent sweep. The configured sweep interval defaults to 10 seconds; actual start time also depends on worker capacity.
- Settlement and sweep share the same eligible-child query. A later nomination can use an already-completed import. Account narrative failure does not revoke import readiness. Existing suspension and privacy-stop controls remain effective.
- Person context and its task instructions expose `/research/parent-account-dossier.json`. This view resolves the persisted parent link within the same workspace, run, account and pinned context, then reads the verified completed artifact. An in-progress revision does not replace the completed reference. The view includes the document, version and import receipt and rejects writes/edits.
- Existing access to the exact delegation brief, account claims, original sources and pinned seller/product/ICP/persona context remains. Person agents continue writing their own JSON dossiers and importing their own claims.
- Readiness and successful sweep queue offers are logged with job identifiers. Raw evidence is not added to logs.
- New launches pin recipe 18. Earlier pinned runs retain account-settlement scheduling. The reviewed v17 researcher profiles, prompts and dossier skills are reused; no research methodology or model change.

## Verification

Provider-free tests cover:

1. Import readiness while the parent is still in progress, before initial settlement.
2. No release on partial import; transaction rollback removes readiness; retries do not duplicate markers.
3. Fresh-handler recovery and queue deduplication.
4. Person completion recorded before the account settles, without premature reconciliation.
5. Read-only parent dossier access through the actual workspace backend and refusal across workspace/account/person/context boundaries.
6. Completed parent dossier remains visible while a revision is only a draft.
7. Late nomination, later narrative failure, privacy stops and suspended generations.
8. Historical recipes retain the previous release policy.

The five new integration tests pass against the isolated `clue_dossier_import_test_20260926` database. Existing import, runtime, driver, pages and generation checks were also exercised; lint, formatting and focused mypy pass. Account/person resource hashes were verified for revisions 2–18.

Initial test fixtures failed database constraints because a simulated terminal job lacked required terminal metadata and a simulated execution used an unsupported role spelling. Fixtures now use the production job-finishing helper and existing execution role. These were fixture defects, not relaxed production constraints.

## Live acceptance still owed

Launch a fresh revision-18 account-plus-person run when authorized. Observe account import commit → person queue offer/start while account narrative remains active; inspect the actual person brief and parent dossier reads; verify person JSON outputs and imported claims. Confirm real latency, trace continuity and provider costs.

The previously prepared r17 live test remains paused. Its harness must be updated to expect revision 18 before a future launch. This implementation started no fleet workers and made no paid provider calls.

Additional verification: three older prompt/resource tests assumed revisions 13/15 were still the default. They now explicitly request those historical revisions; the new default is checked separately as revision 18. All 30 selected offline prompt/schema/navigation checks passed after this adjustment.
