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

## Finding write identity checkpoint (2026-09-25)
- New record_research_finding@3 derives its job-scoped identity from canonical content and canonical resolved source IDs. No model operation_key; exact retries replay, different payloads remain separate, explicit correction tools remain the update path.
- Immutable recipe/profile revision 15 is the new launch default; historical resources retained.
- Selected offline DB/runtime/catalog checks: 31 passed. /tmp/arv_runtime_checks.py blocks external sockets; escalated only for isolated local Docker/Postgres access after sandbox refused the socket. No external calls or fleet jobs this turn.
- Next: whole-batch model feedback and explicit durable failed-attempt replacement.

## Batch repair feedback checkpoint
- Native Deep Agents before-model middleware now charges one repair round per completely settled failed batch, with checkpointed count/batch identity. Per-tool errors always return feedback; fourth failed round stops before another model call. Read precondition refusals remain non-budgeted.
- Nine scripted-model offline checks passed: seven parallel failures all visible, mixed success retained, sequential exhaustion, plan rejection, checkpoint/compaction state and duplicate-batch handling.
- Existing unrelated dirty account-research-briefing skill has a pin-digest mismatch. Tests use /tmp/arv_catalog_snapshot.py: isolated catalog copy, only that file restored from HEAD; the user's edit is untouched. No providers used.

## Durable recovery checkpoint / session close
- Governed tools accept optional retry_of node keys as plan metadata, not provider input. PlanToolStep omits the new field when empty so old proposal serialization remains stable; the reviewed AgentPlan schema digest is updated.
- Before invocation, C5 checks explicit repair references belong to the same execution/workspace/agent slot/tool. Only successful replacement receipts append node.recovered; original node.failed records remain immutable. Recovery is restricted to leaves without graph dependents. Unrelated success clears nothing, replacement/recovery replay is idempotent, and replaying a recovered failed attempt is refused.
- Execution settlement excludes explicitly recovered failures and does not rerun them. Successful finalization refuses unresolved failed attempts with actionable feedback. finalize_turn is called alone, after sibling results settle. No source/relationship/presentation verification policy was added.
- Repair-round counters survive compaction/replay within a turn and reset for a new turn. Per-call, batch and recovery logs plus durable execution events preserve observability.
- Migration 4c916b02ed9b adds the recovery event CHECK vocabulary; one Alembic head. Fresh disposable DB upgrade to head -> downgrade this migration -> upgrade passed, and disposable DB removed. Downgrade refuses populated recovery audit records rather than modifying history. Application and r13 databases were not migrated or changed.
- Final explicitly selected offline suite: 120 passed in 93.87s. Covers real scripted parent -> specialist with seven failed findings, seven corrected writes/recovery links, both executions completed, cold replay with no duplicate claims, and evidence-erasure lineage. Ruff/diff checks passed; mypy --follow-imports=silent passed for 11 changed source files. Tool input validation also rejects malformed retry_of before invocation.
- Broader selection earlier: 139 passed / 4 failed. Two repair-related failures fixed (contract digest and fake runtime missing state). Two unrelated baseline Stage-0 tests remain: test_real_deepagent_tool_call_uses_exact_governed_descriptor_wrapper invokes open_product_set_selection_gate absent from active v64, and test_stage0_final_response_reports_the_gate_and_does_not_claim_a_confirmed_icp expects stale skill wording. No unrelated product instructions changed.
- Tests used isolated catalog snapshot only to restore the already-dirty account-research-briefing v1 to its committed, pinned content; current working-tree skill digest mismatch remains outside this repair. Source edits to that skill and account_research_catalog plus prior docs/memory were left untouched.
- No provider/model network calls, fleet workers, paid testing, app-data writes or publication this turn. Scoped local checkpoints only. Apply the migration before running updated workers. Reconciliation scheduling/cross-subject recovery and the direct-agent claim-authoring trial remain separate next steps.

## Founder adjustment: ten repair rounds
- Increased shared MAX_TOOL_REPAIR_ROUNDS from 3 to 10 per agent turn, preserving whole-batch counting and independent agent counters. The eleventh failed batch prevents another model call; the tenth corrective round can succeed.
- Updated runtime architecture documentation and boundary regression checks. All 11 scripted tool-feedback tests passed (external sockets blocked, isolated catalog snapshot for the existing unrelated dirty briefing skill). Ruff and diff checks passed. No provider calls, workers, database changes or remote publication.
