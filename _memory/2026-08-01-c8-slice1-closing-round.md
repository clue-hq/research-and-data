# 2026-08-01 — PC-C8 slice 1: consolidated closing round (post-merge of tasks 1.4 + 1.5)

Base `5e569e5` (`platform/c8-context-card`, tasks 1.4 and 1.5 merged). Addresses the eight items
from the 1.4 APPROVED-WITH-MINORS review plus task 1.5's deferred grant handoff.

**Workspace deviation, surfaced:** the coordinator asked for this to run in the main workspace
(`.../workspaces/research-and-data/dar-es-salaam`). This agent is harness-isolated to its worktree
— `git -C <shared checkout>` and `source` of an outside `.env` are both refused — so the work was
done in the worktree on branch **`platform/c8-slice1-close`**, branched off `5e569e5` (same object
store, so the base is byte-identical). Merge from there rather than expecting commits in the main
checkout.

## 1. Delegation withholding (M1) — the map contradicted itself

`AgentSurfacePolicy` gained **`withheld_delegation_roles: frozenset[AgentRole]`** (default empty).
On a surface that withholds roles, `_resolve_resource` drops them from `delegation_roles` *and*
`delegation_tool_grants`, which cascades exactly like the tool ceiling already did:

- `ExactAgentToolSurfaceMiddleware._allowed` installs `delegate_specialist` iff `delegation_roles`,
  so the framework tool leaves the allowed set;
- `generated_resource_map`'s Delegation block renders `- none` and the capability line flips to
  `delegate_specialist: unavailable on this surface`;
- `resolve_delegation` refuses (`is not delegated by`);
- `stage0_trial._DelegationDisabled` becomes an **unreachable backstop** — documented at the class,
  which now records that it used to be the whole fence.

Two knock-ons worth knowing:

- `AgentProfile` validates "a non-delegating profile must use zero delegation limits", so the
  narrowed profile also zeroes `max_delegation_depth`/`max_delegations`. That is the honest reading
  (a surface with nobody to delegate to has no delegation budget) and it narrows
  `AgentPlanPolicy.from_profile` with the surface instead of advertising a budget for nothing.
- Declared grants are still **resolved** before being dropped, so a surface cannot hide a stale or
  retired child pin by withholding the role that owns it.
- Composition guard extended: withholding a role the profile does not delegate is refused
  (`does not delegate`), mirroring the tool guard; the "withholds nothing" message replaced
  "withholds no tool" now that either dimension counts.

**The general map test** (`test_the_map_never_advertises_anything_the_surface_withholds`) parses
the map *structurally* rather than substring-scanning it — a plain `in` cannot distinguish "the
research role is withheld" from "get_research_view is available", which is how the first attempt
produced a false positive. `_advertised_capabilities()` walks bullets under the advertising
headings only, and the assertion derives its expectations from the policy, so a future withheld
capability rendered through a new path is covered the day it is added. Two controls keep it honest:
a positive control (kept tools *are* found) and a full-surface control (the withheld names *are*
advertised on the unrestricted role, so the test cannot pass by the parser going blind).

## 2. The grants bump — profile **v10**, skill **v7 unchanged**

`inspect_statement_history@1` + `inspect_readiness_history@1` granted to `HEAD_OF_ABM`:
`C6_AGENT_TOOL_AUTHORITY` entries flipped, both pinned in a new `head-of-abm/v10/profile.yaml`
(v9 byte-untouched), `C6_ACTIVE_PROFILE_VERSIONS` v9 → **v10**.

**No skill v8 — investigated and decided.** A skill's `tools:` list is a *disclosure gate*
(`required_tools ⊆ effective` or the skill is dropped), not a "tools this skill may mention" list.
`stage0-interview` is routing procedure; it neither needs nor mentions history inspection, and
listing the pair would only make the skill disappear from any future surface that withheld one.
The skill body is unchanged, so v7 stays active and no third catalog version was forced.

**How the model learns which tool resolves which omission.** A governed tool's model-visible
*description* is generated boilerplate (`agent_runtime_wiring` sets it from a stock docstring), so
the input **field descriptions are the entire prose surface** — and while these tools were granted
to nobody they had none. Added: `project_id` gets the trusted-authority phrasing; each tool's
`cursor` names the card omission kinds it resolves ("this is the tool that resolves the card's
`statements_over_cap` and `excluded_statement_evidence_missing` omissions"); `statement_id`/
`route_key` state the ambiguity refusal; `gate` states its default. That is the F8 discipline
applied to a surface that just became model-facing.

**Trial surface validated against the new pin list** — the three withheld tools are still pinned by
v10, so the policy resolves; the two inspection tools are installed on **both** the base role and
the trial surface (§7 sanctions them there, and a restricted surface is precisely where an
unresolvable omission would first appear).

## 3. AC-7's last clause — `tests/api/test_c8_omission_resolution_contract.py`

The card names no tool (§3/§7) and the manifest decides what is installed, so the two halves can
drift silently. The contract now joins them, **count-agnostic**: it walks every
`Stage0CardOmissionKind` member and requires each to be either resolvable (its cursor kind is
accepted by a granted tool) or listed in `_UNRESOLVABLE_BY_DESIGN` *with a reason*. A new kind
added without a decision fails on the day it is added, not the day a card first emits it.

Two kinds are deliberate exceptions, and finding that out was worth the exercise:

- `client_knowledge_over_cap` emits a `client_knowledge` cursor **no tool accepts** — spec §7
  deliberately deferred `inspect_client_claim` as a platform-general read. Recorded as a decision
  rather than repaired here; it is a real (small) honesty gap in the card and belongs with the C6
  toolbelt owner.
- `omissions_truncated` carries a count and never a cursor; a separate test holds it to that.

The accepted-cursor mapping is read off `STATEMENT_CURSOR_KINDS`/`READINESS_CURSOR_KIND` — the
tools' own constants — so a tool narrowing what it accepts fails the test instead of drifting.

## 4. M2 — merged-loser entity: **refuse**

`resolve_claim_entity` now refuses an entity with `merged_into` set
(`interview_entity_merged`, message naming the survivor). `get_account`/`get_contact` deliberately
do not follow the pointer (`surviving_id`'s job), so an existence check alone accepted a row
identity resolution had already retired — the documented M9.4×M2.3 hazard, except the mis-keyed
claim here is **durable** and outlives the read.

Refusal over silent redirection: the function's contract is "a live entity", and quietly moving a
client's own words onto an entity the caller did not name is not a repair anyone asked for. The
reason code carries the survivor so the caller re-routes deliberately.
`test_a_merged_away_entity_is_refused_and_its_survivor_is_accepted` covers both directions — the
survivor half is the control that proves the refusal is about the merge, and it also pins the
tier-3 path (a verified *other* entity).

## 5. M3 — the two missing tests

`test_a_foreign_workspaces_entity_is_not_found_and_the_tool_says_so_typed`:

- (a) an entity created in workspace B, referenced from A → `interview_entity_not_found`, with the
  control that the same id resolves fine *from its own workspace*. Every prior fixture refused an
  id that existed nowhere, which a check that forgot the workspace clause would also have refused.
- (b) a direct `RecordInterviewAnswerTool.preconditions()` call asserting the typed reason code
  reaches the model surface (plus the control that a defaulted client entity returns `()`). The
  whole reason the tool re-runs the resolver in preconditions is that the model reads a reason code
  instead of a stack trace, and nothing proved that path returned one.

## 6. Smalls

- **M4** — `interview_entity_required` is commented as defence-in-depth (unreachable: `_route_shape`
  fires first and both callers construct the model). The 1.4 memory note's claim that it was live
  is corrected in place.
- **M5** — `build_head_of_abm_stage0_execution` now checks `resource_manifest_sha256` against the
  surface it resolved, mirroring the runtime. A surface narrows the *effective tool set*, not the
  profile resource, so `profile_ref` alone cannot tell a trial turn from a full one; a forgotten
  `surface=` now fails loud instead of silently building an adapter with wider plan authority than
  the constitution the model was given.
- **M7** — comment at `SubmitIngestionTool.parameter_policy` recording that the display
  intentionally lost brand/project post-hoist (injected authority is not caller-chosen; the durable
  receipt and the declared-context hash are unchanged).
- **M8** — the guard-the-guard test now **plants** forbidden names at depth 2 (`properties`) and
  depth 3 (through an `items` container) in a real schema and asserts the walk reports exactly
  those two paths. Note: the provider transform inlines `$defs`, so the plant goes into
  `properties.declared_context`, not a `$defs` entry.
- **M6 — done, not deferred.** `registry.projection()` now carries a `surfaces` tuple per role
  (`SurfaceRegistryEntry`: surface, reason code, manifest sha, effective tool addresses, withheld
  tool names, effective and withheld delegation roles). Purely additive (defaults to `()`), so
  `/agent/registry` and its two consumers needed no change. Without it an operator reading that
  endpoint is told the trial can call `start_recon` and delegate to a research specialist.

## Digests / pins moved

| what | value |
|---|---|
| `inspect_statement_history@1` input | `886263cab48572d3779e9a7d7dbb1b72f636f1441d0cd2d50c0dd696592daac6` |
| `inspect_readiness_history@1` input | `fb5d502f6dcea92f508ba311519aa4983bae89b2a74a2a1d4871c300683b4d99` |
| head-of-abm resource manifest | `d6ccc354b796729941fdeed249b2bf962478e8d393af30f90c5ac15d10cc185c` |

Output digests unchanged. Both input digests moved because of the new field descriptions (§2); they
were previously pinned nowhere, so `head-of-abm/v10/profile.yaml` is their only pin site. The
manifest aggregate is re-pinned in `tests/api/test_agent_registry_wiring.py`. No other role pins
either tool, so v10 + that one test constant are the whole re-pin surface.

## Tests

New: `tests/api/test_c8_omission_resolution_contract.py` (5).
New in `test_c8_trial_surface.py` (11 total): `…_never_advertises_anything_the_surface_withholds`,
`…_withholds_delegation_rather_than_crashing_on_it`,
`…_operator_projection_reports_the_narrowed_surface_not_just_the_full_role`; the policy-validation
test gained the `does not delegate` case and the middleware test now smuggles `delegate_specialist`
as well as `start_recon`.
New in `test_c8_project_card_wiring.py` (13 total):
`test_a_merged_away_entity_is_refused_and_its_survivor_is_accepted`,
`test_a_foreign_workspaces_entity_is_not_found_and_the_tool_says_so_typed`.
Flipped: `test_c8_inspection_tools.py::test_the_inspection_tools_are_granted_to_the_head_of_abm_and_nobody_else`
(the tripwire's designed post-grant form — kept rather than deleted, because "granted to exactly one
role" is the claim still worth guarding), `test_tool_authority_audit.py`,
`test_agent_registry_wiring.py` (AVAILABLE instead of ROLE_UNAVAILABLE, new manifest sha),
`test_catalog.py` (v10 sorts lexically *beside v1*, not after v9).

## Verification

`tests/api tests/agents tests/stage0 tests/clue_trial tests/projections tests/architecture` — the
only failure is the documented pre-existing `test_agent_runtime_wiring_db.py::
test_delegation_is_durable_…` (hand-built registry selecting the frozen `head-of-abm@v1`, stale
pins). `tests/api/test_c8_inspection_tools.py` and `test_c8_card_dsar.py` green. Whole-tree run
diffed against a stashed-baseline run of the same command: **identical 37-failure set**. `mypy`
clean (458 files), `lint-imports` 24/24, `ruff check` clean repo-wide, `ruff format` clean on every
touched file (the 15-file repo-wide format drift is byte-identical before and after — verified by
stash-diff, not asserted). `tests/db/test_db_migrations.py` and the live trial deliberately not run.

## Follow-ups left open

- **`client_knowledge_over_cap` has no resolving tool** (§3 above). The card emits a resume cursor
  nothing accepts. Options when §7's `inspect_client_claim` decision lands: grant it, or stop
  emitting the cursor for that kind. Ledgered in `_UNRESOLVABLE_BY_DESIGN` so it cannot be
  forgotten silently.
- The surface **framing prose is still code-defined data**, not a byte-pinned catalog resource
  (1.4's deviation 1, unchanged). Promoting `AgentSurfacePolicy` to a catalog resource is additive
  if a later slice wants the bytes pinned.
