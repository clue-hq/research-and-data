# JSON dossier integration — 2026-09-26

User authorized porting the account/person trial method into the main research platform.
Implementing v4 quality revision16: parent researcher owns JSON sections/review; C5 tools save,
validate and finish/import through existing deterministic importer. Removes parent claim-specialist
delegation/direct finding writer for new profiles; keeps narrative and historical resource pins.
Shared replace_section keeps trial/production behavior aligned. Artifacts persist both canonical
JSON and versioned state/receipts; partial imports freeze and resume without duplicate writes.

Current focused checks: 18 offline parser/profile/trial tests and 9 isolated DB tests pass,
including actual scripted account/person Deep Agent/C5 finalization/cold replay. Broader existing
runtime/launch/nomination checks in progress. Typecheck of four changed API modules passed.
No paid providers, application data, workers or publication.

Failures during development: generated recipe initially omitted mirrored compatibility/global
allowlists (fixed); new scripted model initially had incorrect _generate signature (fixed).
Reviewed lock ordering and chose job-scoped advisory serialization rather than an exclusive job
row lock, avoiding reversal against authority's execution->shared-job lock ordering.

Separate unrelated preexisting dirty files were left unchanged. No broad reconciliation or
narrative redesign; post-import dossiers are frozen. Live output quality remains untested.

## Closing verification

Integration complete locally. Across focused runs, 45 offline tests and 27 isolated Postgres
checks pass (new JSON tools/import, scripted account+person runtime/cold replay, default-launch
worker continuation, historical runtimes and nominations). Both source-erasure regressions pass:
canonical JSON and receipt/state become unreadable when their source is erased. Ruff passes;
mypy passes for four changed API modules. All historical launch manifests (r2-r16) checked.

Default-launch fixture updated to produce an actual imported dossier. Its initial receipt
parser incorrectly tried parsing native line-numbered file output as JSON; fixed to skip
non-JSON tool messages. Old default expectation updated 15->16. A one-off diagnostic imported
RecipeDefinition from the wrong module; corrected to clue_execution (production already correct).
No live research quality claims, workers, provider calls, app DB writes, push or publication.

Exact review paths and remaining semantic/live acceptance limits:
docs/superpowers/plans/2026-09-26-json-dossier-integration.md.
