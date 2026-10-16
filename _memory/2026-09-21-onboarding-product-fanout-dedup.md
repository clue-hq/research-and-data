# Onboarding product fan-out deduplication

- Bounded follow-up to the fresh native onboarding test; parent owns the live website work.
  No live DB writes, worker restart, provider calls, recovery action, commit, or push here.
- Root cause: catalog synchronization returns one immutable lineage link per catalog entry.
  Alias and high-confidence model matches can resolve several entries to one product. The driver
  scheduled all links, but product research step identity is `(run_id, product_id)`, so the second
  link attempted the same primary key and containment correctly failed the aggregate run.
- Changed only the driver fan-out: stable deduplication by non-null resolved product ID before
  creating work, retaining the first catalog name for the query/document path. Catalog entries,
  lineage, store uniqueness, and failed-run terminal guards are unchanged.
- Regression evidence: the new offline test failed with duplicate provider calls; the new real
  store case failed with `onboarding_step_pkey`. After the fix, 25 offline driver tests and 20
  isolated DB driver/store/lineage tests passed. Coverage includes alias/model matches, unresolved
  entries, distinct products, first-name retention, and preserved lineage with one step/call.
  Scoped Ruff, format, and diff checks passed. Initial Ruff/format findings were corrected.
- DB tests use the uniquely named disposable database recorded under ignored
  `.local-setup/onboarding-dedup-test/database.json`; migration/red/green test receipts are there.
  Initial sandbox TCP denial was retried with approved local access; no shared schema was changed.
- Existing failed runs are not resumable through this fix. `start_step` intentionally rejects
  duplicates, `finish_run` cannot overwrite a terminal failure, and the enqueuer uses
  `reopen_terminal=False`. Preserve the failure and use its ready documents where supported.
  If a completed aggregate run is required, a new normal onboarding request after workers load
  this fix is the supported path, with fresh provider spend; do not reset/requeue the old run.
- Closing state: changes left uncommitted for the parent's requested review. Full-repository
  tests and fresh live onboarding on this fix were not run; checks above are the bounded proof.
