# Original project context in native website design — 2026-09-28

- Continued the active quality goal without a paid generation, live page/data edit,
  service restart, or push. Existing unrelated working changes remain untouched.
- Verified original user-message transfer already exists in the design leg envelope.
  The remaining gap was access to original project instructions/decisions: Design
  saw the delegation summary and seller files, but not the project's source records.
- Added an injected platform adapter read for only the opening turn's pinned
  instructions.md and decisions.md. It uses existing artifact-integrity and
  workspace/project checks. It returns exact bytes plus source identifiers, not
  a new synthesis. Missing pins are explicit; no unpinned current-state fallback.
- Native web scaffold materializes this as a read-only project-context/snapshot.json.
  Failed/removed adapters replace previous context with an unavailable snapshot.
  The prompt distinguishes this old opening-turn snapshot from current instructions.
- RED observed: absent adapter and dropped workspace source files. The initial
  runtime test incorrectly expected edit() to throw; corrected it to check the
  backend's structured permission error and unchanged bytes.
- 27 disposable database tests passed, covering exact transfer, no opening/pin,
  foreign workspace/project, tampered/erased artifacts, existing reads and pinning.
  Scoped adapter mypy and changed-file Ruff checks passed. Runtime checks pending
  at this entry; append final result before committing.
- Incidental root formatter churn on legacy native files was removed; only intended
  hunks retained. A guessed nonexistent test filename caused no tests to run in one
  command; corrected with repository file discovery.
- The canonical project still lacks the latest no-logo-in-navigation correction.
  This change does not manufacture it or rewrite past pins. The visible Projects
  route redirects to Home on the running frontend; no Instructions editor was found.
  Browser was returned to the original failed native chat, with no message submitted.
- Next: complete offline checks, then enforce/qualify selected structure and current
  correction delivery before any new paid generation. Broader goal remains incomplete.

## Closing verification

- All 312 selected runtime tests passed (platform reads, workspace isolation,
  typography references, solo mode, account prompt contract and web substrate).
  The initial combined invocation had 311 passes and one Chromium launch failure
  from macOS sandbox Mach-port denial. That one network-blocked synthetic browser
  test passed on an escalated retry. No application/provider generation occurred.
- All 27 selected database tests passed on a migrated disposable database, removed
  afterward. Scoped mypy passed. Ruff passed on the changed adapter/read module,
  tests, prompt and filesystem backend; harness import-order check passed. Full
  harness Ruff still has pre-existing modernization warnings, left untouched.
- The no-logo correction and final structural/visual qualification remain pending;
  this is a verified source-transfer checkpoint, not goal completion or live rollout.
