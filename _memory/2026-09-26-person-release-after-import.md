# Person release after account claim import — 2026-09-26

User approved the discussed scheduling change; implement and verify offline, then stop before live testing. Broader reconciliation changes remain deferred.

Implemented recipe 18 default: FinishDossier retains a completed-import artifact marker transactionally; the existing fleet sweep and settlement use one child-selection helper. Person jobs can enqueue while the account remains in progress. Failed/partial initial imports do not release; successful-import narrative failure does not block. Queue dedup and durable sweep recovery preserved. Older pinned recipes keep settlement-based release.

Added read-only /research/parent-account-dossier.json using the persisted parent relation plus workspace/run/account/context checks and verified artifacts. It exposes the latest completed import, not an in-progress revision. Person task/context point to it; own person JSON authoring/import remains intact.

Five new isolated DB integration checks passed (release/retry/rollback, parent view, sweep restart/dedup, early child result, historical policy); existing import/runtime/driver/pages/generation checks exercised. Targeted Ruff/format and mypy passed; all launch manifests 2–18 verified. Initial test fixture mistakes: incomplete terminal-job metadata and unsupported execution role spelling; corrected to production finish helper/existing role, no production constraints relaxed.

Details: docs/superpowers/plans/2026-09-26-person-release-after-import.md.

Live testing still paused; no workers/provider calls started. Prepared .artifacts/arv4-clue-zafran-20260926-r17 harness needs revision-18 expectations before future authorized launch. Preserve unrelated existing working-tree edits (including .gitignore and older notes/briefing changes).

Additional verification: three older prompt/resource tests assumed revisions 13/15 were still the default. They now explicitly request those historical revisions; the new default is checked separately as revision 18. All 30 selected offline prompt/schema/navigation checks passed after this adjustment.
