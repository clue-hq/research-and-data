# Programmatic JSON dossier import

- Founder authorized developing programmatic parsing/storage of the claim-ready
  JSON dossier, and reiterated that no second model should extract the claims.
- Moving the trial's finding contract and proposal mapping to reusable ARV2 modules;
  direct JSON parser/importer preserves original entries, resolves source and finding
  references, retains all five review statuses, and reports partial failures.
- Scope is the account import seam and isolated trial adapter. No production fleet
  selection, specialist ownership, research prompts, reconciliation or display edits.
- Existing 27 parser/trial tests pass; new modules pass focused mypy. New real-DB
  tests pending. Plain python command unavailable; switched to repository .venv.
  Docker socket blocked in sandbox; escalated local-container inspection succeeded.

## Verification and closeout

- Three real-Postgres tests passed in dedicated throwaway database
  clue_dossier_import_test_20260926: all statuses, forward links, exact values,
  replay, immutable import ID, failed-write rollback/retry, scoped/revoked grants.
- Saved replay run-02 JSON imported directly in new isolated run-08: 122 findings,
  122 matching readbacks; repeat import replayed every ID. No model or acquisition
  calls; external sockets blocked. Original reports and previous receipts preserved;
  new import-location record is namespaced rather than overwriting the old pointer.
- Existing trial models/proposal mapping now reuse shared code. Legacy line parsing
  remains only for old experiments. Production fleet routing unchanged; current
  account-only import seam is ready for separately reviewed lifecycle integration.
- Importer logs scoped IDs/counts and opens a shared observation span. No claim text
  in logs. JSON source text and all original entry fields remain inspectable.
- Known limits: semantic errors are preserved, not repaired; cyclic finding links
  still require explicit repair; semantic dedup across imports/reconciliation and
  person integration remain outside this slice. No migration, worker or publication.
- Closing checks: 27 focused offline tests and three isolated Postgres tests passed;
  focused strict mypy, Ruff and diff checks passed. Independent comparison of exported
  run-08 claims against the original JSON also passed 122/122, including source sets
  and resolved links. Review saved in run-08/IMPORT-REVIEW.md. No pending processes.
