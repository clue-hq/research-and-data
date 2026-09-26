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
