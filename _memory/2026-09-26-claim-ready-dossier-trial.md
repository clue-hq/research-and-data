# Claim-ready dossier trial

- Founder approves generic dossier instructions and a saved-data trial: sectioned
  dossier, one meaningful finding per entry, then mechanical claim import. Preserve
  prior trials; production promotion is not part of this slice.
- Added generic SYSTEM/SKILL/TASK/README under docs/superpowers/drafts/
  2026-09-26-claim-ready-dossier. No target-specific discoveries in instructions.
- Reused numbered trial harness with dossier-mode preparation/tools and optional
  origin metadata in existing shared writer. New account_dossier_trial.py parses
  sectioned JSON lines, renders readable Markdown, resolves finding references,
  imports and compares stored values. No acquisition or alternate persistence.
- Nine focused tests and ruff pass. Real cloned-DB rollback smoke verifies five
  statuses plus dossier-origin metadata and exact statement bytes; no probe rows.
- Initial Docker call failed under sandbox; approved escalation prepared run-03.
  Source/context hashes match prior run; historical prompt snapshots unchanged.
- Authorized Grok/OpenRouter saved-data trial started with shared Langfuse and local
  traces. No fleet, person research, reconciliation, publication or new Exa/AI Ark.
  Results and quality assessment pending. Review production integration separately.

## Closing checkpoint: provider limit

- Run-03 ended during source reading: OpenRouter 403 weekly key limit exceeded.
  Thirteen completed model calls, fourteenth rejected; no dossier-writing calls,
  generated entries or trial claims. No tool/parser/import failure established.
- Preserved local traces, frozen instructions and REVIEW.md/review-metrics.json in
  the isolated folder. Source/context hashes match prior run. User notified and
  asked to report when configured key allowance is available. No alternate key/model
  or billing change attempted. Retry must preserve interrupted run; current harness
  has an in-memory checkpoint, so do not claim durable in-place continuation.
- Nine focused tests, ruff, compile and diff checks passed; real database smoke
  rolled back all probes. Generated-dossier quality and real generated import remain
  untested. Production integration still deferred. Local checkpoint 6c26b98eb.

## Authorized retry completed

- Founder updated configured API key and requested retry. Prepared run-04 in a
  fresh isolated DB/folder; all input and prompt hashes match interrupted run-03.
  Rollback-only real-DB smoke passed. No prompt/code/model change for this retry.
- Completed 101 entries -> 101 shared-store claims. All stored content/metadata,
  source IDs and sections match entries; relationships resolve. Deterministic
  re-import replayed every receipt with no duplicates. No paid calls in re-import.
- Grok 4.6 completed 46 calls, recorded $3.545966, ~640.6s to freeze dossier.
  Source reads broader than prior writer; six validator calls and 17 file edits
  repaired cycles, missing links and one malformed fragment. No tool exceptions.
- Independent REVIEW.md separates transfer success from mixed semantic quality:
  preserved statement detail, but omissions, bundling, scope/interpretation leakage
  and role parsing regressions remain. Agent changed some semantic annotations
  while making references pass. Do not certify quality or promote production.
- Prior trials preserved. Known shared Langfuse warnings recur; local traces/usage
  retained. No acquisition, fleet, person jobs, reconciliation or publication.
- Next review: meaningful units, source coverage, judgment separation and easier
  reference authoring. No additional iteration authorized or started here.
