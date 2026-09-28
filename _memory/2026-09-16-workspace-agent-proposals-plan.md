# Workspace-local agent-proposed fields — planning

Founder requested a detailed implementation plan and corresponding agent documentation after the
Settings audit identified global registration of unknown ARV2 field keys. Scope is planning/docs,
not implementation or live operations. Baseline Irvine `settings-page`, `c5092f276`.

Prepared `docs/superpowers/plans/2026-09-16-workspace-agent-proposed-fields.md` and the companion
`docs/agents/research-field-scope.md`. Linked Settings spec/completion plan, ARV2 master plan/README
and agent authoring guide. The companion contains current behavior, exact proposed operating
instructions and immutable-resource publication requirements; it is not automatically mounted.

Key findings: human research rows require `settings-v1`/`human:%` at the DB; contact facets need
explicit class handling; normalized unknown keys can preserve reserved/foreign namespaces;
Settings falls back to “Workspace member” without a human name. Global field snapshots include
historical proposals. Historical cleanup must inspect global-field FKs beyond claims and cannot
infer platform ownership from global-table membership or a description alone.

Proposed defaults P1–P7 remain for review: automatic local active registration, manager governance,
neutral reusable instructions with raw rationale scoped to provenance, no metadata overwrite,
subject-bound keys, historical containment and preservation of lifecycle/privacy refusals.
Phases cover audit, substrate, writer/runtime, Settings/readers, historical reconciliation,
actual agent manuals/bundles, and controlled two-workspace live acceptance.

Current selections checked: Head profile v57, manual v4, ARV2 account/person bundles v1. Next
versions must be allocated afresh; no active catalog bytes/pins were changed. An older authoring
guide table was labelled as the historical C6 baseline rather than current configuration.

One combined documentation patch failed on an incorrect master-plan heading; apply_patch made no
partial changes, and the corrected patch succeeded. Initial guessed module/migration paths were
resolved through rg --files; no runtime commands or database operations were attempted.

Closing verification: checked all 24 local Markdown links across the seven product/agent docs;
all resolve. `git diff --check` passed. `.venv/bin/python -m clue_api.manual_build --check` passed
(`4 manual chapters are current`), confirming existing generated resources remain consistent.
No application tests were rerun for this documentation-only change. Active profiles, migrations,
services, provider calls and data are unchanged; implementation/live proof remain unchecked.
