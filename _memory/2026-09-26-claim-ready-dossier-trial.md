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
