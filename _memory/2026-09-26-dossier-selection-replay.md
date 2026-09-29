# Saved-source structured dossier replay

- Founder authorized retry of claim-storing stage following selection-guidance
  revision. Re-author from the latest saved research then import into a new isolated
  database; deterministic re-import alone would not test revised judgment.
- Added prepare_replay to the existing live dossier adapter; shares JSON skill
  preparation with fresh mode. Copies exact source bodies/context and prior dossier,
  excludes reviewer answers and old working notes. Replay mode removes acquisition
  tools, empties capabilities and adds a defensive acquisition refusal.
- Twelve focused offline tests pass; ruff and diff checks pass. Tests cover source
  fidelity, acquisition capability removal, snapshot verification, old-note/reviewer
  exclusion, original mutation detection and refusal to overwrite a prior run.
- Prepared .artifacts/account-dossier-replay-20260926/run-01 from the completed fresh
  trial. Configured account model unchanged, configured tracing retained. No Exa,
  enrichment, fleet, person research or production writes. Original snapshots intact.
- Existing isolated database container confirmed running with approved sandbox
  escalation. Model replay launched; output and semantic review pending. Planned
  import destination: account-claims trial run-06, preserving all earlier runs.

## Completed and reviewed

- Initial execution hit the 200-step graph limit after 68 calls, before finalizing.
  Continued in run-01-continuation-01 from 140 saved model-input messages, existing
  working JSON and native history archive. Final pending output could not be replayed
  because the audit serializer omitted tool-call fields. This is context recovery,
  not a persisted graph checkpoint. Original attempt retained unchanged.
- Added optional saved-message continuation support to the isolated runner. Founder
  explicitly requested 700 steps; claim-ready fresh/replay invocations now use 700.
  Other previews and production runtime limits unchanged. No new environment flag.
- Continuation completed after 14 more calls. Final 95 findings in 12 sections;
  all 95 imported into isolated run-06 with exact content/metadata/source/section
  equality. Repeat import reused every ID, no duplicates or errors. No acquisitions.
- Recorded model spend $3.935124 across both attempts, no new provider-research spend.
  Broad source acquisition was reused; this was not a fresh end-to-end research run.
- Semantic results mixed: recovered omitted source material, preserved meaningful
  voice, repaired one unrelated reference, and formed durable conflict/duplicate
  links. Bundled events/speakers, repeated fit summaries, hypotheses in factual text
  and research gaps as supported observations persisted. Skill was read completely.
  Role-label and time-incomparable conflict judgments remain questionable.
- Detailed independent review at .artifacts/account-dossier-replay-20260926/REVIEW.md.
  No manual finding corrections or production promotion. Possible future controlled
  comparison: same sources but raw provider report instead of prior claim-shaped
  draft, to investigate anchoring; not proven causal and no further run launched.
- Twelve focused tests passed, continuation message reconstruction exercised live;
  ruff, compile and diff checks passed. Preserve concurrent edits to the draft skill.
