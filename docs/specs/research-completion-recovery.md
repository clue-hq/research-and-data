# Research completion and delegation recovery

Implemented locally on 2026-09-28. Applies to platform account and person research, not a trial-only adapter.

## Completion ownership

For JSON-dossier research (v4 recipe 16+), the researcher supplies its summary, gaps, and optional specific unprocessed-source UUIDs. It may write those notes to `/outputs/research.json`; without that file the finalizer uses its supplied user message as the summary. Existing complete reports remain accepted as notes, but their mechanical identity/reference fields are rebuilt rather than trusted.

`quality_completion.build_completion_report` reads the exact saved dossier/import receipt, scoped committee evidence, delegated jobs and publication records. The common account/person runtime writes the canonical report before the existing governed finalizer snapshots outputs. Job/context IDs, imported finding IDs and artifact references come from storage. This does not generate claims, infer research quality, or waive ownership checks.

The report records dossier saved, claims imported, dossier version/artifact and narrative publication/page artifacts. Accepted execution finalization remains separately identified by the durable finalization envelope/key. Final research-job settlement retains its existing coverage checks. A saved dossier is not the same as a published narrative or completed execution.

For researcher-owned narration (recipe 20+), missing pages produce a repairable refusal naming the missing pages and `read_narrative_inputs` / `write_research_narrative`. An incomplete import points to the existing draft and `finish_dossier`. Completion bookkeeping itself requires no new research; genuinely unfinished investigations remain the researcher's responsibility. Invalid notes identify the file and required correction. Earlier successfully committed work remains available.

The task input and finalizer tool description disclose this backend-owned contract. Historical pinned skill/prompt bytes are unchanged. Legacy non-JSON research retains its original completion file requirement.

## External references are scoped

`claim_ids` remains owned by the research subject. `committee_assessment_ids` is an explicit contextual-reference category: an account-owned committee selection or assessment in the same workspace, account and context. Person reports can reference only committee evidence naming that person. This is not permission to reference arbitrary claims from other entities/workspaces.

Generation-child membership cross-checks the backend-generated child list so a corrupted parent pointer cannot silently hide a delegated job. Invalid references receive field-specific errors; a correct child ID with damaged delegation metadata requires backend repair, not an invented replacement.

## Enrichment preserves delegation

Previously an unseeded person lookup called the nomination reference builder with the current person job as parent, then replaced all `input_refs`. This overwrote the true account parent, brief, generation and recipe references.

Provider references now carry a separate `provider_job_id`. Lookup merges only provider-owned keys atomically into the persisted job, under workspace/run/account/person predicates. Seed reopening validates the persisted provider origin and reads the operation under that job. This supports both account-discovered seeds and person-owned enrichment across restarts without rewriting the delegation.

## Explicit repair of already-corrupted jobs

`quality_delegation_repair.restore_person_delegation` is an operator recovery function, not an agent tool or automatic mutation during reads. It verifies the scoped generation child, one retained identity-bound brief, the referenced account parent, the child's pinned profile and any provider operation. It restores parent/brief/generation/recipe references and separates provider provenance. Existing unrelated metadata is preserved and a recovery marker is recorded. Repeating the repair is a no-op. Missing/ambiguous originals or a conflicting different parent are refused.

## Verification

113 focused offline/isolated-Postgres tests passed, including native account/person runtime finalization with full legacy reports, notes-only reports and no manually written report. Tests also cover cross-subject/context/workspace rejection, enrichment restart, delegation recovery/replay and detection of silently omitted children.

An additional adjacent runtime/driver/dossier check passed 22 tests. One existing driver fixture failed because it expects recipe 22 while the current checkout selects recipe 24; that unrelated expectation was not changed.

Saved-run replay used separate databases and cloned blob directories. Grok 4.6 Vari and Nick executions finalized against their saved 38/49 findings and existing narratives using a scripted finalizer call. DeepSeek Nick and Muse Nick/Vari recovered their briefs and parent dossiers; incomplete research/narratives remained incomplete. No paid calls occurred. Original evidence, claims, display blocks, page pointers and provider-ledger rows match the recovery copies.

Evidence: `.artifacts/finalization-repair-20260928/`. Original comparison databases/workers were not modified or restarted. Fresh paid model adherence is not established by scripted replay. Provider capacity/errors, missing narrative generation and reconciliation output-shape failures are separate work.
