# Revise an imported research dossier

Implemented locally, 26 September 2026. Applies to account and person researchers in
quality recipe17. This extends the existing JSON dossier/import tools; it does not
add an extraction model, change research acquisition, or redesign reconciliation.

## Agent workflow

1. Read `/research/dossier/latest.json`, including its import receipt and version.
2. For a concrete correction or extension, call `begin_dossier_revision` with
   `expected_version`, a readable `reason`, and optional `withdrawals` mapping F-IDs
   to reasons. A new durable draft copies the imported document. Current claims are
   unchanged at this point.
3. Keep a finding's F-ID when correcting it. Give independent additions new F-IDs.
   Submit complete changed sections through `save_dossier_section`, preserving
   unrelated entries. Missing prior IDs must match explicit withdrawals. A wrong-entity,
   duplicate, or uncertain observation can remain a finding with its review metadata.
4. Critically review against the formation skill, correct defects, validate, then
   `finish_dossier`. This applies the complete revision atomically.
5. Use the new receipt's claim IDs for final handoff and narrative refresh. A failed
   revision leaves the previous claims current and the draft editable; repair or retry.
   `discard_dossier_revision(expected_version)` restores the last imported document.
   Draft history remains retained. It cannot undo a successfully applied revision;
   that requires another explicit revision.

## Storage semantics

- Completed snapshots remain immutable. Artifact references retain each draft, import
  receipt and baseline reference under the original job/context/subject.
- Unchanged entries reuse their existing claim IDs. Changed entries create new claims,
  retire their earlier versions and set `superseded_by` through the shared claim-store seam.
- Changes to a target F-ID propagate to entries referencing it, even when those entries'
  authored text is unchanged. Stored duplicate/conflict references point to current IDs.
- Withdrawals retain original rows, sources and rationale. They do not fabricate replacements.
- Uncertain replacements retain their assessment. The prior version is retired through an
  append-only withdrawal assessment and linked to its replacement; retirement does not
  assert that the replacement is verified. Generic correction-tool policy is unchanged.
- Version-specific import identities allow reverting wording without reviving old claims.
- A transaction savepoint surrounds all revision writes and retirements. Failure rolls them
  back together. Source/blob writes may leave unreferenced storage objects handled by existing
  storage lifecycle; they are not published claims. Initial partial-import recovery is unchanged.
- Baseline claim revisions are captured and checked under claim locks. External corrections
  cannot be silently overwritten. Such conflicts require rereading/review, not blind retries.
- Reused claims are checked against job, subject, pinned context, actual evidence grant,
  original entry, section and resolved claim value. The agent cannot nominate arbitrary claim IDs.

## Downstream behavior

The existing claim-quality event outbox records retirements and new assessments. Existing
page dependency fingerprints change immediately; the driver delivers events into generation
`claim_changed` signals for the applicable subject and context. Account overview/insights and
person pages continue using their existing dependency/refresh logic. Narrative refresh can
also be requested by the researcher after successful import.

This change does not run a page-generation model by itself. Workers must be running to process
queued refresh work. Existing advisory presentation retains historical/uncertain observations
with status information. No new verification or presentation restrictions were added.

## Scope and limitations

Tools operate on the dossier owned by the authorized research job, including its governed
continuations. This is not a new frontend editing endpoint or a migration of historical runs.
Older recipe pins remain unchanged; new launches default to recipe17. Cross-account/person
reconciliation semantics and researcher judgment about whether a correction is warranted remain
separate work.

## Verification

Focused offline profile/schema tests and isolated Postgres tests exercise account/person
revision, unchanged ID reuse, uncertain replacements, dependency remapping, explicit withdrawal,
reverting wording, immutable history, cold receipt replay, atomic failure/retry/discard, external
assessment conflicts and generation/page invalidation. No paid model/provider calls, live fleet
jobs, or application database changes were used. Final test counts are in the matching local
memory note.
