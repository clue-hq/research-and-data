# Deepagent co-defines the buying committee before drafting — steering lane (2026-08-20)

## Founder ruling implemented

Before the Head-of-ABM drafts/launches an account-research directive that discovers a committee,
it must settle with the user (a) what the project sells (confirm from confirmed product context
rather than re-asking) and (b) who fills champion / economic_buyer / technical_evaluator / blocker
at this kind of company — then encode the outcome into `directive.committee_plan`. STRONG PROMPT
EMPHASIS only: **no deterministic gate, no new refusal anywhere** (founder: teach it via prompt).
Live motivation: directive v9's ratified plan was all-empty, the account agent improvised
`target_functions` at call time, and a vocabulary mismatch excluded two physician-executives.

## What changed (steering content only; zero engine files)

- `platform/agents/catalog/skills/account-deep-steering/v8/SKILL.md` — new section
  **"Co-define the buying committee with the user before you draft one"**, placed immediately
  after "Stay non-linear". Covers: the two things to settle in conversation; the plan-field
  encoding (`personas` with the platform persona keys, `functions`, `levels`/`teams`,
  `candidate_cap`/`relationship_depth`); why an all-empty plan is the wrong statement (the live
  loss, named); **provider-vocabulary awareness** (matching is case-insensitive containment
  against provider job-function/title values and the account agent may narrow but never invent, so
  synonyms — `Clinical` + `Physician`, `Information Technology` + `IT` — belong in the plan
  itself); the executability pairing (`sumble_people` allowed + committee discovery allowed, which
  the draft tool's `_committee_intent_names_a_capable_source` validator already requires); and the
  decline path — propose the mapping yourself, put it in the plan, and state it persona-by-persona
  in the message carrying the confirmation gate (or in the same-turn message on the exact-subject
  direct-launch path).
- `platform/agents/catalog/profiles/head-of-abm/v38/profile.yaml` — skill sha re-pin
  `55bd36ec…` → `03dfbf58…`.
- `tests/api/test_agent_registry_wiring.py` — HEAD_OF_ABM aggregate manifest digest
  `6ce7b34f…` → `eca3d400…`, with the reason in the existing comment block.
- `tests/agents/test_o3_account_deep_behavior.py` — content pins for every load-bearing sentence
  of the new section (mirrors the file's existing "the steering skill, not the tool description,
  carries the contract" pins).

## Versioning discipline followed

In-place amendment of the **current** skill version + re-pin, which is this repo's own precedent
for steering-content fixes: `0fce7a84` and `3fde62a9` (both 2026-08-19) each edited
`account-deep-steering/v8/SKILL.md` in place, updated the v8 sha inside `head-of-abm/v38`, and
moved the aggregate digest in `test_agent_registry_wiring.py`. A **new** skill/profile version is
minted only when a *tool pin* changes (v37→v38 rode `draft_account_research_directive` @4→@5); no
tool version moves here. No recipe revision is involved either — the C5 interaction slot pins tool
allowlists, not steering bytes, so `recipe0-stage0-v18` is untouched. Skill sha = sha256 of the
whole SKILL.md bytes (`FolderSkillCatalog`).

## Tests

`tests/agents` (205) + `test_agent_registry_wiring.py` + `test_comprehensive_research_contract.py`
+ `test_account_research_directive_a2.py` + `test_lane_d4_agent_gate_db.py` — all green against a
freshly migrated `clue_missoula_steer`. ruff clean/formatted; the one mypy error is pre-existing in
`tests/profiling/conftest.py`. `test_lane_d4_model_planned_kickoff_db.py::test_the_deepagent_plans_the_whole_kickoff_through_the_c5_slot`
fails identically at pre-change HEAD (sealed-membership fixture) — pre-existing.

## Account-manual reconciliation note (not edited — another lane owns it)

`catalog/entity-research/account/v3/manual.md:169-170` still carries the improvisation fallback:
"`target_functions` (1–20, each copied from the confirmed committee plan; when every plan selector
is `(unrestricted)`, choose the functions your account evidence supports)". Same fallback is
composed live in `account_entity_research_composition.py::_committee_plan_block`. Both stay
correct — a plan can still legitimately be unrestricted — but with this steering in place the
empty-plan path should become rare rather than normal. If the account lane wants to tighten it,
that is its call; the engine behaviour is unchanged either way.
