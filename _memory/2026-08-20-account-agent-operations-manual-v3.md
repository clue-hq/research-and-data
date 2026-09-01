# Account agent operations manual — steering v3 (2026-08-20)

Tier-1 static failure playbook for the ACCOUNT research agent, authored from the 2026-08-19 live
run's defect catalog and wired through the versioned resource mechanism. **No commit** (orchestrator
commits); no service restart; no live-DB writes.

## Where it landed

`platform/agents/catalog/entity-research/account/v3/` — the live steering bundle:

- `manual.md` (**new**, ~19.5 kB ≈ 5k tokens): per-tool sections for all eleven account tools
  (`read_account_research_state`, `research_account_deep`, `enrich_account`,
  `inspect_account_evidence`, `discover_buying_committee`, `record_committee_role_inferences`,
  `assess_account_coverage`, `read_research_result`, `read_evidence`,
  `finalize_account_research`, `delegate_account_facet`), each with produces / when-and-when-not /
  call shape / refusal reactions / one-line invariant, plus a global settlement contract
  (evidence-backed OR exhausted-with-terminal-attempts; empty is honest; fabrication is the only
  failure), the loop rule (an identical repeated call is refused identically — change it, make the
  named call, or finalize), round-shape rules, and the empty-turn rule.
- `prompt.md`: v2 text + a 5-line pointer making the manual binding.
- `skill.md`: carried forward from v2 byte-identical.
- **No `profile.md`** — deliberately (see below).

Every refusal reaction is sourced from a real live failure: `provider_terminally_unproductive`,
`provider_rejected` (Sumble 402/422), `provider_spend_unreconciled`, `engine_authority_rejection`
(incl. the coverage refusal that prints the exact `discover_buying_committee` arguments),
`reference_type_rejected`, `request_authority_violation`, `research_request_shape_rejected`,
`identical_read_loop`, `empty_model_turn`, `parallel_round_shape_rejected`,
`finalization_already_proposed`, plus the engine-disposes outcome correction at finalize
(needs_review returned to a `completed` request → emit unchanged, never re-buy).

## Version mechanics — steering v3, profile stays v2 (deliberate)

`EntityResearchRuntimeContext` pins **only the profile** to the durable job authorization
(`agent_profile_ref` + `agent_profile_sha256`), and `AccountResearchDefinitionResolver.resolve`
hard-refuses any job whose authorization names another profile ref. The live DB had **19 queued
`agent-profile:account-research:v2` jobs** at authoring time; a v1→v2-style uniform ref bump would
have stranded every one of them ("R5 definition requires one exact live account-job fence/profile").
The profile body did not change, so:

- profile ref/version stay `agent-profile:account-research:v2` / `v2`, loaded from the frozen
  `account/v2/` directory (`_ACCOUNT_PROFILE_VERSION`, `_profile_root`);
- prompt + both skills move to `v3` (`_ACCOUNT_STEERING_VERSION`), loaded from `account/v3/`:
  `agent-prompt:account-research:v3`, `agent-skill:governed-account-research:v3`,
  `agent-skill:account-tool-operations-manual:v3` (a **second** skill in the bundle).

Steering is replay-pinned by the R3 journal (`system_prompt_sha256` / `resource_manifest_sha256`)
rather than by the authorization, and the turn key carries `task_attempt` since `9cfe4a49`, so a
resumed job legitimately re-drives under newer steering — no `EntityResearchJournalConflict`.
In-flight v2 jobs therefore pick up the manual on their next drive. **Rule recorded in code: bump
the profile ref only for a genuine role-identity change, and drain launched jobs first.**

Also: `ACCOUNT_RESEARCH_PROFILE_REF` is now exported and used by
`AccountResearchFleetLauncher` (it previously hard-coded the same literal — a silent drift hazard
between launcher and resolver).

## Files touched

- `platform/api/clue_api/account_entity_research_composition.py` — version constants,
  `profile_catalog_root` kwarg, `_account_catalog_root()`, per-resource versioned `_resources()`
  with the manual as a second skill, public `ACCOUNT_RESEARCH_PROFILE_REF`.
- `platform/api/clue_api/account_research_fleet_launch.py` — stamps the shared constant.
- `tests/api/test_entity_research_cutover_r10.py` — the two account-steering guards pointed at
  **v1** since the v2 bump (frozen dir → vacuous); repointed to the live root, made
  wrap-insensitive (`_steering_text`), + two new tests: manual covers every tool and every live
  refusal code; steering/profile pin split with the frozen-history assertions.
  *Finding: `assert "call `finalize_account_research` again" in prompt` had silently stopped
  matching at v2 because the sentence rewrapped — it only passed against v1.*
- `tests/api/test_account_entity_research_r5_db.py` — resolve-path assertions on the real bundle
  (profile v2 + prompt/skill/manual v3, manual body present).

## Verification (throwaway `clue_opsmanual_checks`, alembic head, dropped after)

Green: `test_account_entity_research_r5_db`, `test_entity_research_runtime_r3(+_db)`,
`test_entity_research_cutover_r10`, `test_catalog`, the **5×3 comprehensive harness**,
`test_comprehensive_account_execution_db`, `test_account_entity_research_fresh_skip_db`,
`test_committee_agent_inference_acceptance_db`, `test_account_research_fleet_launch_r6_db`,
`test_account_field_derivation`, `test_entity_research_tools_r4`, `test_tool_authority_audit`,
`test_m8d_r1_entity_research_quarantine`, `test_account_deep_fixture_a1`,
`test_comprehensive_research_contract`, `test_entity_research_r2_db`,
`test_entity_research_parallel_r9_db`, `tests/contact_research`. ruff format/check + `uv run mypy`
(732 files) clean.

Pre-existing, reproduced at HEAD with the change stashed:
`tests/api/test_toolbelt_wiring.py::test_out_of_order_matrix`
(`confirmed_discovery_router_unavailable`).

## Deliberately not done

- No contact-agent manual (the contact bundle is still `contact/v1`; same pattern applies when its
  turn comes).
- No trimming of the ~5k-token static cost — the founder-specified 11×5 structure implies it; the
  alternative it replaces is a job looping to the graph recursion cap.
- `delegate_account_facet` is documented as *not bound* under the current composition
  (`facet_contract.enabled=False`), not enabled.
