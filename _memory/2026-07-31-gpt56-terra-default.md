# GPT-5.6 Terra default — 2026-07-31

## Decision and implementation

- Branch: `platform/clue-trial`.
- The local `.env` now sets `CLUE_SYNTHESIS_MODEL=openai/gpt-5.6-terra`; no credential value was
  changed or recorded.
- `DEFAULT_SYNTHESIS_MODEL` and `.env.example` now use `openai/gpt-5.6-terra`, so ICP synthesis
  and settings that intentionally reuse the synthesis default select Terra when no override exists.
- Every selected deepagent role now resolves to a new immutable profile version using Terra:
  Head of ABM v5, research specialist v4, content drafter v4, reviewer v4, and account research v3.
  Older GPT-4.1 profile resources remain unchanged as replayable historical evidence.
- The OpenRouter Chat Completions agent adapter sends `reasoning_effort=none` for the GPT-5.6
  family. This preserves function-tool compatibility without changing prompts, temperatures,
  output limits, or the frozen model-policy contract.

## Verification

- Active registry inspection resolved all five roles to `openai/gpt-5.6-terra` and the new exact
  profile addresses/manifests.
- Focused config, gateway, catalog, registry, runtime, and trial suites passed; DB-dependent tests
  skipped when their configured database fixture was unavailable.
- The gateway regression asserts the actual OpenRouter payload contains both
  `model=openai/gpt-5.6-terra` and `reasoning_effort=none` when function tools are bound.
- Focused Ruff, Ruff format-check, and mypy passed.
- The combined agent/gateway/config/registry/Stage-0/Clue-trial selection passed with only the
  expected environment-gated skips.
- Repository-wide `make check` stopped at its first formatting gate because 19 pre-existing files
  outside this model migration would be reformatted. They were left untouched; every modified
  Python file in this change passes focused Ruff format, Ruff lint, and mypy.

## Operator note

- Restart the running trial API after this commit so its process reconstructs the profile registry
  and reloads `.env`. A new trial will then durably pin the Terra-backed Head-of-ABM v5 profile;
  an already-created execution remains pinned to the prior immutable profile by design.
