# F8 — enforced Stage-0 preconditions made visible at the point of authorship

Date: 2026-08-01 · branch `platform/clue-trial` · base `a25a04b`

## Why
Live acceptance turn 2: Terra routed product facts through `record_interview_answer@1` but
paraphrased a claim `value`; `interview._exact_quote` correctly refused ("claim value is not
textually entailed by the exact interview quote"). The rule was enforced but never stated where
the model authors the field. Prevention pass mandated by the user: state every runtime-enforced
rule in the model-facing field description. Verifiers unchanged (F7 already made refusals visible).

## What changed
- **Descriptions only** on the Stage-0 tool input models (`platform/api/clue_api/stage0_tools.py`,
  all seven tools) and on `InterviewStatement` (`subsystems/research/clue_research/stage0/
  interview.py`). No validation logic, types, defaults, or validators touched. `interview.py` was
  listed as "untouched" in the brief, but the claim-route `value` field the brief names lives
  there and nowhere else — the edit is `Field(description=...)` metadata plus a class-docstring
  rewrite (the docstring is the model-facing object description).
- **Prevention gate** `tests/api/test_stage0_tool_guidance.py`: (1) an explicit
  enforced-constraint → required-substring map asserted against the real model-facing schema
  (`_with_trusted_runtime` + `convert_to_openai_tool` + `provider_compatible_tool_schema`), so
  hidden authority fields are exempt and a description that never reaches the provider cannot
  satisfy the gate; (2) every model-visible field (nested statement fields included) must carry a
  ≥20-char description; (3) the covered tool set is re-derived from `C6_AGENT_TOOL_AUTHORITY` and
  `_Stage0Tool.__subclasses__()`, so a newly model-invocable Stage-0 tool fails the build until it
  declares guidance. Written RED first (43 missing rules, 62 undocumented fields), then green.
- **Coordinated immutable bump**: `skills/stage0-interview/v5` (v4 bytes + new §3b "Authoring
  rules for routing" + the 5 changed tool hashes) and `profiles/head-of-abm/v7` (v6 + skill v5 pin
  `1207579f…` + the 5 changed `input_schema_sha256` pins). v4/v6 bytes untouched.
  `C6_ACTIVE_PROFILE_VERSIONS[HEAD_OF_ABM] = "v7"`.

## New tool input-schema hashes (output hashes unchanged)
- `evaluate_stage0_readiness` `5cd02f910efd4212…`
- `record_interview_answer` `17e741cba55facd0…`
- `start_confirmed_project_run` `a59f57b070c50045…`
- `start_recon` `a69370b41efe2892…`
- `submit_onboarding_input` `9a1f4eda9363e2a6…`
`get_research_view`, `propose_field`, `propose_source`, `submit_ingestion`, `synthesize_icps` are
byte-identical, so no other role's profile needed a bump (only head-of-abm pins Stage-0 tools).
`confirm_project_product` / `override_stage0_readiness` hashes also changed but are pinned nowhere
(human-only).
- Head-of-ABM aggregate resource manifest: `4c0f8693…` → `d64fe87af513664a…`.

## Verification
`tests/agents`, `tests/architecture`, `tests/api`, `tests/stage0` all green (DB-gated tests skip —
no throwaway DB was provisioned, and the shared local DB holds the pending acceptance-run state, so
DB tests were deliberately not run against it; the change is description-only). ruff + ruff format
+ mypy on changed files, `lint-imports` 24/24.

## Notes / follow-ups
- Model-facing schema cost for the 5 Stage-0 tools is now ~15.2 KB of JSON, ~7.4 KB of it
  descriptions (~2k tokens per request across the whole Stage-0 surface). Acceptable, but watch it
  if more tools join the Head-of-ABM belt.
- The gate's substring table is deliberately crude (it proves the rule is *mentioned*, not that it
  is well phrased); keep entries pointed at the enforcing code path in comments so a verifier
  change forces a description review.
- `evaluate_stage0_readiness.metrics` remains model-supplied (Task-5 ledger item); the description
  now says plainly that inflating a number records a false readiness decision, but that is
  guidance, not enforcement.
