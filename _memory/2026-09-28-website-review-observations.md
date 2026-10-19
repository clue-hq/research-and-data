# Website review observations — 2026-09-28

## Scope

- Continued the existing website goal with offline tools and saved-run evidence.
  No native generation, paid provider call, ingestion, saved-page change, runtime
  restart or remote push. Keep the no-new-run restriction in force.
- Original checkout, `codex/design-agent-v1`. Preserve unrelated research tests
  and the pre-existing account-acceptance/import memory notes.

## Changes

- Added a turn-local observation ledger exposed through `view("review")` and
  saved automatically as `review_evidence` at website finalization.
- Receipts bind page, local document version, render iteration and image hash.
  They aggregate delivered strips, invalidate stale reads, and retain clone
  comparison abstentions, capture omissions and media-readiness gaps.
- Tall state captures now support `state:<n>:tile:<i>` and refuse stale views.
  Source behavior consulted during inspection is retained for manual comparison
  with the final component; it is not proof the behavior survived.
- Desktop clone-content overflow now appears as advisory evidence. Deliberate
  contained horizontal scrolling may be valid; no new durable verdict is minted.
- Updated the existing review skill and references for these actual contracts.
  No new acceptance gate: finalization still preserves the agent's outcome.

## Evidence and limits

- Replayed the exact recorded view calls against the saved native PNGs without
  rendering or showing them to another model. First render: readable desktop
  strips 0/9/11 of 12, tablet 0 of 16, phone strip 0 of 18. Final render after
  mutation: desktop strip 9 only, no tablet or phone strips. Prior clone review
  is stale at that final version and retains its viewport-mismatch abstention.
- Replay output remains ignored at
  `.local-setup/hotel-equities-import/native-skill-repair-validation/review-observation-replay.json`.
  Replay version numbers identify capture sequence, not persisted DB revisions.
- A source overview and receiving all strips do not prove attention, good design,
  all tab states, keyboard behavior or persistence. Ledger quality verdict is
  always `not_computed`. Independent browser observations and earlier-turn critique
  cannot be certified by this current-turn ledger.
- Offline skill probe correctly distinguishes whole-page failure from an accepted
  narrow edit whose affected regions are inspected. Scope and source-interaction
  reconciliation are still reviewer judgments; unsupported acceptance remains
  mechanically possible. Do not call this a complete quality-enforcement fix.

## Closing verification

- RED cases reproduced missing ledger/state strips, desktop overflow advice,
  comparison/media limits and lost unobserved-capture class names.
- Focused ledger checks passed 7 tests after repair. Broader suite: 244 passed,
  one inherited fixture failed because its supposed settled unchanged preview
  omitted `_preview_media_ready`. Confirmed the same fixture in HEAD; corrected
  its precondition without relaxing the production readiness guard.
- Independent code review found failed repeat reviews could hide behind an older
  success. Reproduced RED, then recorded failed/error attempts separately while
  retaining previous evidence. The review/cap/preview/finalization/budget rerun
  passed **63 tests**. This includes final JSON persistence and the corrected
  inherited fixture. No complete production/browser quality acceptance is claimed.
- Commands: root `.venv/bin/python`, design-subsystem cwd, explicit
  `PYTHONPATH=.:apps/api:apps/agent_runtime`, `-q -o addopts='' --tb=short`, unique
  `/tmp/clue-review-*` directories. Suites: runtime substrate, review gate/cap,
  solo mode and skill family; API clone review gate. No DB changes or provider
  calls. A pre-existing unresolved PIL type annotation in the changed test file
  was made available under TYPE_CHECKING for targeted lint.
- Skill RED/GREEN probes were documentation-only. They identified the real
  remaining boundaries: review scope is prose, required interaction reconciliation
  is manual and finalization does not enforce the reviewer's choice.
- Tool changes do not resolve the upstream brief drift, page argument, source
  typography/media contracts, four-state interaction implementation, matching
  reference capture width or excessive mobile content. No improved live page has
  been demonstrated; the wider goal is still active.
