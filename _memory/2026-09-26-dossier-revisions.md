# Post-import JSON dossier revisions

User authorized next slice: corrections/extensions after import, preserving claims and history.
No broad reconciliation changes or paid provider/model calls.

Implemented explicit begin/discard revision tools under new quality recipe17. Begin snapshots
baseline document/receipt/claim quality revisions; edits retain F-IDs. Unchanged claims reused;
changed references propagate through duplicate/conflict entries. Finish applies new claims and
retirements atomically. Explicit withdrawal reasons required for removed IDs. Qualified replacements
remain qualified: prior version withdrawn via quality assessment, linked with shared supersession
seam. Existing quality events and page-input fingerprints invalidate downstream synthesis.
Atomic revision failure leaves editable draft and old claims current; initial partial imports
still freeze/retry. Discard restores previous completed dossier without changing claims.

New immutable parent profiles/prompts v17 and v17-person, formation skills v2, acquisition skill
account v7/person v3 (only updated formation-skill path), recipe and manifest. Historical pins kept.

Progress: 13 isolated database tests pass, covering account/person replacement/reuse/remapping,
uncertain replacements, revert-to-original, explicit removal, atomic rollback/retry/discard,
stale external assessment and existing generation/page invalidation. Four-module mypy passes.
First old retry tests failed because completed receipt returned original replay flags; corrected
to label receipt replay without rewriting claims. Review caught old formation-skill paths in
acquisition skills; versioned those references too. No application DB writes or worker launches.
Closing checks/commit pending.

## Closing verification

27 isolated Postgres checks pass across dossier import/tools, scripted runtime, default-launch
driver, pages and generation. 17 focused offline parser/profile/port checks pass. Four changed
API modules pass mypy; changed Python files pass Ruff and git diff --check. All historical/current
launch manifests r2-r17 match pins. Added regression checks for explicit skill paths being mounted
and historical v16 having no revision tools. Reuse re-resolves source grants and compares the
complete resulting value (including related claim references) before accepting a retained ID.

No live semantic judgment/page-generation acceptance performed. Refresh signals/fingerprint
changes are verified; actual prose refresh requires workers. New launches select17, older pinned
runs unchanged. No frontend correction editor or cross-job migration introduced. Separate
preexisting dirty files preserved.

Final path-mount regression initially used SkillBundle.name instead of materialized_path;
corrected the test to inspect the actual runtime mount. All 17 offline checks pass afterward.
