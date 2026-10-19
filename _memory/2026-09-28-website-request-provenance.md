# Website request provenance — 2026-09-28

## Scope

- Continued the website goal from the completed native-run audit, offline only.
  No new native generation, provider call, ingestion, saved-page change, runtime
  restart or remote push. The user's no-new-run restriction remains in force.
- Original checkout, `codex/design-agent-v1`. Unrelated research tests and earlier
  account acceptance/import notes are preserved, outside this checkpoint.

## Finding and change

- The original user message already reaches the design runtime unchanged. The
  defect was conflicting instruction: planning prompts promoted the strategy
  brief's verbatim text into requirements. The audited native plan did that.
- Shared leg rendering now identifies the brief as an agent-authored summary and
  distinguishes actual user requirements, reported decisions and recommendations.
  The brief bytes, user message, block ordering and growing prefix remain intact;
  the new explanatory header deliberately changes the initial prefix once.
- Missing/empty history roles now render as `unattributed`, not `user`. Reproduced
  the incorrect attribution in an offline RED test. Production history normally
  supplies roles; this edge case is not established as a cause of the audited run.
- Canonical page-planning and campaign skills now use a compact three-part record:
  attributed user requirements, revisable working choices and source evidence.
  Explicit user requests still win; useful delegated choices are retained without
  inventing approval. Approval of structure does not verify factual claims.
- Website author/solo prompts now agree with that record. An inherited plan cannot
  make an assistant proposal binding merely by repetition. Mandatory chrome was
  replaced by the chosen shell, if any. Tiny copy edits explicitly need no plan-file
  write, resolving a conflicting solo instruction found in review.

## Verification

- Before/after read-only application probes covered: an emphatic strategy brief;
  a current correction; an explicit user request for navigation/pilot/demo; a tiny
  CTA change; and a prior approved outline with an unsupported later addition.
  Both probes correctly reasoned about these cases. The baseline exposed wording
  ambiguity but did not reproduce the native model's failure. No measured model
  improvement or rendered-quality result follows from these probes.
- RED: unattributed history was labeled as user approval. GREEN: correct roles,
  unchanged current request, distinct frozen summary, stable growing prefix,
  batch assignment and non-leg behavior. **15 offline substrate/session tests**
  passed; DB/executor tests were deselected and no live database was touched.
- **19 runtime skill materialization/solo-mode tests** passed, including the
  final tiny-edit wording. These check delivered skills and prompt/tool wiring,
  not model compliance. Fatal/syntax Ruff and `git diff --check` passed.
- Root command: `.venv/bin/python -m pytest` with the selected offline tests in
  `tests/design/test_p37_design_entry_consumption.py` and `test_design_sessions.py`.
  Runtime command: root venv, design cwd, `PYTHONPATH=.:apps/api:apps/agent_runtime`,
  `test_web_skill_family.py` and `test_web_solo_mode.py`; `-q -o addopts='' --tb=short`.
  Scratch directories were unique `/tmp/clue-handoff-*` paths.

## Remaining boundaries

- This is instruction-level provenance, not typed persisted approval enforcement.
  Initial design history contains leg exchanges, not the whole strategy transcript;
  unavailable prior approvals must remain reported context.
- Continued sessions may omit the cached brief. The header then is not resent;
  current prompts/skills supply the guidance. Old mislabeled cached messages are
  not retroactively rewritten. Live rollout/cached-session behavior is unverified.
- The separate Head-of-ABM manual's stale leg-start claim still needs a normal
  catalog version update; immutable historical catalog files were not changed.
- Source typography/media geometry, interaction reconstruction, nonredundant account
  argument and complete phone inspection remain open. Existing source-copy and
  review-observation checkpoints do not constitute creative-quality acceptance.
- Saved pages are unchanged. No improved native page or completion of the goal is
  claimed. Next work should validate these remaining contracts offline before any
  separately authorized native generation.
