# Research progress projection — 2026-09-28

Scope: user authorized progress reporting only. Display Completed for usable account/contact
research even when execution needs_review; keep execution diagnostics intact. No research-to-typed
field mapping and no multiple-project selector; both explicitly excluded/deferred.

Implemented:
- Batched delivery projection scoped by workspace/project/context/run/subject. Account requires
  published Overview + Insights; person requires own Contact page. Current available output
  artifacts and latest indexed dossier completion determine product completion.
- JSON dossier persistence adds a lightweight artifact_reference to the same snapshot with state
  and version, in the same transaction; no job-row lock upgrade or new migration.
- Project card stages: research, compiling findings, storing claims, writing narrative, completed.
  Percentages are milestone fractions, not duration estimates; parent and nominated people each
  contribute. Person status lines name the contact. Queued work does not say complete.
- Account list/detail reuses the same readiness projection; backend job status is never rewritten.
  Older flows retain their status/stage behavior. Latest unavailable dossier cannot fall back to
  an older snapshot. Published pages must follow the dossier snapshot.
- Completed cards retain existing 60-second linger. Backend execution/provider diagnostics remain
  stored, but do not make a usable delivery appear failed in product progress.

Verification:
- 156 backend tests passed covering progress fold/API, real dossier import and publication,
  account status/detail/list, expired/missing outputs, person scope, and untouched needs_review.
- 11 frontend progress/contract tests passed; scoped mypy passed (4 files), ruff/diff checks passed.
- The previous one-query account-status test was updated to two fixed batched reads (jobs and
  delivery), retaining the no-N+1 rule. No provider calls or signed-in browser test performed.
- Tests use the existing isolated completion_repair DB on port 59390 with rollback fixtures.

Unrelated frontend restoration/reconciliation/experiment changes left unstaged. No workers or live
runs started or modified. This projection checks persisted publication availability; it is not a
new research-quality judge or a replacement for the page reader's evidence handling.
