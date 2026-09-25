# Research runtime repairs — checkpoint 1

## Agreed scope

- Repair infrastructure in separately reviewable checkpoints before a saved-dossier claim-writing
  trial: artifact concurrency; workspace/history access; tool-error recovery; reconciliation.
- Account and person agents will own their entity's findings in the later trial. No skill,
  prompt, specialist ownership, default runtime, scheduling, or live research changes in this
  first checkpoint. No provider calls or fleet workers started.
- Existing unrelated worktree edits are left alone.

## Artifact deadlock

- Reviewed r13 Postgres logs: source `FOR SHARE` reads cycle against artifact upserts.
- Added a deterministic two-connection reproduction: each transaction holds the other's source
  shared lock, then re-records its existing content-addressed output. Before the fix, real
  Postgres reports DeadlockDetectedError (40P01).
- Cause: record_artifact unconditionally updates erasure columns, including for unchanged live
  records, acquiring an exclusive row lock unnecessarily.
- Fix: reuse a live row with matching workspace, hash, media type and byte count under FOR SHARE.
  New, erased or metadata-mismatched records keep the existing upsert path. Privacy erasure,
  artifact lineage, retention and tenant checks remain enforced.
- Regression also verifies an exclusive erasure lock cannot be acquired while live reuse is
  in progress, and erasure proceeds after that transaction commits.
- First test iteration exposed UUID-to-string conversion missing on the new return path;
  corrected to match get_artifact before verification.

## Verification and isolation

- Fresh migrated database: clue_runtime_repair_20260925, existing isolated Postgres at 59274.
  No historical run database was modified.
- Storage/artifact, research storage and evidence suites: 26 passed, one S3/MinIO case skipped.
- Ruff check and format passed for the changed Python files.
- Research runtime/advisory and durable agent artifact integration: 10 passed, including the
  real governed runtime with scripted models across research revisions 5, 6, 9, 11 and 13.
- Closing result: 36 passed, one optional S3 case skipped. No paid calls. Checkpoint 1 complete.

## Still pending

- This fixes the reproduced unchanged-artifact lock-upgrade cycle, not a proof against every
  possible lock-order problem. No paid or end-to-end research acceptance yet.
- Next checkpoint: framework compaction archives and authorized workspace reference navigation.
- Then repair per-batch error recovery, durable failed-attempt finalization and reconciliation
  triggers/scope handling before the isolated dossier-to-claims trial.
