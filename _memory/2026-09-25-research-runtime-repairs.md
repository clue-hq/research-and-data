# Research runtime repairs

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

## Checkpoint 2 — workspace, native compaction and evidence navigation

- Deep Agents CompositeBackend now sets artifacts_root=/work. Its existing summarization
  middleware writes /work/conversation_history/<thread-id>.md and supplies the recovery path;
  no custom compactor, summary format or shell execution was introduced.
- Evidence files now use account-manifest sequence + sanitized title/URL, with index.json,
  authorized ls/glob, exact-name resolution and helpful unknown-path/offset/erasure errors.
  Names are views over the existing immutable source metadata, not an alias database or copies.
  UUIDs remain canonical internal identity; UUID filesystem paths have no compatibility alias.
- Finding, evidence-search and disposition tool v2 accept these readable paths and reuse the
  existing canonical write/authorization logic. New v4 launches pin research resource revision
  14. Revised resources only change navigation/tool syntax; research ownership stays unchanged.
- Dossier views refresh inventory paths without rewriting saved dossier/manifest bytes.
- Tests use real workspace + native summarization with scripted models; two compactions append
  history and native read_file reopens it. Working notes/output writes succeed while source and
  context writes and host traversal remain unavailable. Execution remains a separate capability.
- Isolated clone clue_r13_navigation_20260925 was made from retained r13 DB. The replay read all
  1,261 sources through readable names and checked identical text, plus all five scoped person
  inventories. The saved account dossier hash stayed unchanged. Artifacts are under
  .artifacts/runtime-navigation-r13-20260925/. Historical DB/blobs were not edited or deleted.
- Final explicit offline selection: 84 passed, 1 optional S3/MinIO case skipped, with external socket access blocked
  by temporary runner plugin (loopback PostgreSQL permitted). Includes real governed parent /
  specialist execution through revision 14, provider/media handoffs, scope/revocation and writes.
- Updated fixture pins that combined v2 hashes with the newer default runtime. Historical
  catalog resources remain intact. Ruff passed for changed files. Mypy reports one unrelated
  pre-existing design_leg_wiring.py:1627 Mapping-versus-dict assignment; new files are clean.

### Testing mistake and follow-up discipline

- A broad tests/arv2 invocation unintentionally reached live suites: their Secrets fixture loads
  .env and does not require explicit live opt-in. Stopped the process when identified; informed
  the user immediately. Do not describe this checkpoint as having made zero provider calls.
- Ledger records six AI Ark operations totaling 3.2 credits, public website/ATS reads, an Exa
  overview, two searches and contents. Completed Exa operations report $0.041 in aggregate
  (agent poll rows repeat the same job cost, not additional distinct jobs). One deep-research
  request was interrupted without a final receipt; its cost is unknown. No fleet/application
  research launch was made. Paid results were not used to claim repair acceptance.
- Final tests used an explicit quality/runtime file selection plus /tmp/arv_offline_only.py to
  refuse external socket connections. Never run the entire ARV2 directory assuming it is offline.
- Pending after this checkpoint: tool-error recovery and reconciliation; then saved-dossier
  claim-writing trial. No paid end-to-end acceptance or fleet restart in this checkpoint.

- Closing checkpoint 2: final path-boundary follow-up passed (4 tests), including invented source
  numbers that must return useful feedback instead of overflowing the database integer type.
  No historical evidence deleted, no schema migration, and no remote publication.
