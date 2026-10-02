# Account-agent research dossier (side conversation)

- User approved a complete trial-style account-agent dossier before claim processing;
  no new research verification or presentation gates, person research rewrite, or paid run.
- Reuse trial 03 reporting behavior, not benchmark-specific facts. New account profile v13,
  prompt v11, account-dossier skill v4, quality recipe revision 13; historical/person pins retained.
- No separate save tool: account filesystem write/edit middleware snapshots the exact report
  through ResearchArtifacts and existing artifact_reference retention/index. Scoped version views
  expose report + original-source inventory; claim delegation gets the pinned version path.
- Reports remain agent synthesis, outside arv2_evidence_source; citation matching distinguishes
  referenced from merely retrieved sources without implying reading. Existing privacy lineage applies.
- Parent's dirty files and running jobs untouched. Own isolated Postgres database:
  codex_dossier_20260925 on localhost:5432, created solely for rollback-isolated tests.
- Implementation in progress; verification and final status to follow.

## Closing verification
- 38 focused tests passed (two invocations); one S3/MinIO storage variant skipped because
  test endpoint is not configured. PostgreSQL tests ran in the dedicated throwaway database.
- Scripted real Deep Agent/runtime test exercised filesystem save, durable version view,
  claim-specialist delegation, exact originals and cold execution replay.
- Dedicated persistence test exercised exact UTF-8 content, citation vs retrieval inventory,
  identical-save reuse, changed-version history, simulated downstream failure, scope/refusal,
  revocation and existing erasure derivation. Dossiers never enter the evidence-source table.
- First test pass exposed one stale scripted model-call count (8 vs new 10); corrected that
  expectation. Ruff and targeted mypy passed. No provider/model paid calls or fleet activity.
- This verifies storage/handoff mechanics, not live dossier writing quality or mandatory
  model compliance: the before-claims sequence is instructed, without a new quality gate.
- No frontend viewer added. Agents read /research/account-dossier/latest.json or numbered
  version views; receipts carry exact report/manifest artifact keys for ordinary artifact reads.
- Later person findings are incorporated by the existing account continuation using the
  same reporting instructions; person runtime/prompt and specialist profiles stay pinned.
