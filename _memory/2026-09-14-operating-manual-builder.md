# Operating-manual builder and the four generated chapters (lane 1, plan 2b, task 1)

**Date:** 2026-09-14. **Branch:** `research-streaming` (worktree `san-salvador`).
**Commit:** `e6b87359e`, base `7d4c2def9`. Local only.
**Design:** `docs/superpowers/specs/2026-09-13-head-of-abm-operating-manual-design.md`.
**Report:** `.superpowers/sdd/2026-09-13-operating-manual/task-1-report.md`.

## What exists now

Four generated manual chapters, each an ordinary catalog skill so the profile can pin it like any
skill and the capability map discloses it with its summary and materialized path:

- `platform/agents/catalog/skills/manual-{tools,fields,errors,limits}/v1/SKILL.md`

Built by `python -m clue_api.manual_build --write` (`make manual`); `--check` (`make manual-check`)
exits 1 on drift. Byte-stable across runs.

## Where the code lives, and why it is split

- Rendering: `platform/agents/clue_agents/manual/{__init__,build,fields_snapshot}.py`.
- Entry point: `platform/api/clue_api/manual_build.py`.

**The split is forced, not stylistic.** The import-linter contract "agents import only the toolbelt
facade + projections" forbids `clue_agents` → `clue_api`, so the toolbelt and the handful of
composition-root constants (`_MAX_GOVERNED_TOOL_FAILURES`, `_GOVERNED_TOOL_REPAIR_HELP`,
`_FAILURE_MESSAGE_LIMIT`, `READ_REFERENCES_BUDGET_BYTES`, the budget ceiling, `ModelFinalizeRequest`,
`GovernedToolFailure`, `TRUSTED_TURN_FIELD`) are collected into a frozen `CodeFacts` and passed in.
Do not "simplify" this by importing `clue_api` inside `clue_agents`; import-linter follows lazy
function-local edges too.

## Decisions worth remembering

- **`catalog/manual/tool_notes.yaml` is the authority on refusal codes**, per controller ruling M3.
  The builder renders exactly the codes listed and never greps source. A granted tool with no entry
  fails the build by name. Codes were curated from research `A-tools.md` and re-verified against the
  tool modules; the sweep found two codes newer than the research doc
  (`read_account_research`: `offset_past_end`, `offset_not_paged`).
- **`#:` attribute comments are parsed out of model source** because pydantic drops them unless the
  model sets `use_attribute_docstrings` (none does). This is the only path by which the read tools'
  status vocabularies reach anything the model sees.
- **The fields chapter groups by namespace, with the family as a column**, not one section per
  family. Measured reality: 161 keys in 132 two-segment families, only three multi-key
  (`contact.facet` 23, `account.resonance` 6, `account.scoring` 3). 132 one-row sections would have
  been noise. The family column is the exact `field_prefix` string, computed the way
  `read_tools.claim_prefixes` computes it.
- **Two constants were given names** so the chapters import rather than retype:
  `clue_agents.execution.RECEIPT_REFERENCE_VALUES_MAX_BYTES` and
  `clue_agents.runtime.superstep_ceiling()`. No behaviour change.
- **`fields.json` is a committed snapshot** (161 rows) written by
  `python -m clue_agents.manual.fields_snapshot` against the lane DB (`set -a; source .env; set +a`).
  SELECT only. Committed so the build and the drift test need no database.

## Open follow-ups

- `tool_notes.yaml` is founder-review pending (33 KB of prose the agent will act on).
- Task 2's drift test must check the inverse of what the build checks: a refusal code in the source
  with no note. The build only catches a tool with no entry.
- `PROFILE_VERSION = "v53"` is pinned in `clue_agents/manual/build.py`. When Task 4 bumps the
  profile to pin the chapters, that constant must move with it; nothing currently fails if it does
  not. Worth a Task-2 assertion.
- Nine of the 21 tools render as "Complete a project step" (design §7 item 10). Visible in the
  chapter now.
- `manual-tools` is 78 KB / 1,245 lines. Inside `read_file`'s 2,000-line default window, but if it
  grows, split by tool family.

## Verification performed

`pytest tests/agents` 288 passed / 2 skipped; `tests/api/test_arv2_read_tools.py` +
`test_agent_model_env_override.py` 30 passed; ruff format + check clean on every touched file;
`mypy platform/agents/clue_agents` clean; `lint-imports` 26 kept, 0 broken; `--check` clean before
and after a re-`--write`. No live tests, no `make check`, no broad suite.
