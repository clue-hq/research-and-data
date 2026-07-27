# C7.4 — reference-only snapshots and scoped evidence access

## Outcome

C7.4 is complete on `platform/c7-research-views`. The implementation adds durable, append-only,
body-free research-view snapshot receipts and a current-policy evidence-action service without
creating a second truth store or persisting signed evidence locators.

## Implementation

- Migration `a69a1769d4bc` adds snapshot, ordered reference, support, action, reachable-subject, and
  evidence-access-audit tables with exact scope foreign keys, closed checks, append-only triggers,
  deterministic operation idempotency, and one safe Alembic head.
- `narrative.research_view_snapshots` composes a C7.3 live view into a reference manifest, stores it
  atomically, and resolves only the saved reference set against current claims, tombstones,
  verification, policy, and composition state. Missing or no-longer-eligible references become
  unavailable/redacted/restricted/stale; historical bodies are never reconstructed.
- `api.evidence_access` is the sole authorized C7 `StorageBackend.presign` boundary. It proves the
  exact workspace/project/snapshot/action/statement/claim/subject relationship, delegates current
  policy authorization, validates public/API/artifact source state, caps previews at 300 seconds,
  returns opaque capabilities, and records body-free audits.
- `account_handoff.payload` is nullable and has an optional snapshot pointer, purge timestamp, and
  backfilled subject index. DSAR/objection handling purges indexed payloads; legacy writes reject
  account, committee, or provenance-reachable subjects that are already tombstoned.

## Legacy compatibility disposition

Immediate removal of the old body payload is unsafe before C7.6/C7.7:

- `narrative.handoff_store` remains the central decoder for `HandoffService`, HTTP, and toolbelt
  callers.
- `review.disposition_store` has one isolated direct SQL reader for legacy ICP/provenance context.
- New C7 snapshot writes are reference-only. The compatibility interval is bounded to the C7.6
  production committee handoff and C7.7 serving cutover; those slices must migrate the readers,
  stop new body writes, and then remove legacy decoding.

## Verification

- Targeted C7.4 snapshot/evidence/DSAR/legacy suites: green.
- Full DB-enabled pytest suite: green.
- Mypy: `Success: no issues found in 429 source files`.
- Ruff format/check over all changed files: green.
- Alembic: one head; isolated clean upgrade → downgrade → upgrade: green.
- Manual legacy migration check from the C7.2 schema proved backfill of view account, committee
  contact, and provenance-claim subjects.
- Offline full migration SQL generation and serialized-body/key leakage checks: green.

## Environment and failure notes

- Docker was unavailable, so verification used a dedicated Postgres.app database on port 5432.
- The shared default database had stale pre-C7.2 state, so it was not used for acceptance.
- Repository-wide `make check` formatted 879 files successfully, then lint found `T201` only in
  unrelated untracked `.claude/` and `.codex/` scripts. Those user-owned files were preserved.
  Scoped Ruff, full Mypy, full pytest, and migration gates for the implementation are green.

## Next handoff

C7.5 adds the additive, idempotent re-check report over existing durable C5/C6 operation
authority. It must not mutate snapshots, weaken policy gates, or introduce another research/model
loop. C7.6/C7.7 own the final legacy handoff writer/reader cutover described above.
