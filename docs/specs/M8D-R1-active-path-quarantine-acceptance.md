# M8D R1 — Active-path quarantine acceptance

> **Status:** Accepted on 2026-08-06 on
> `platform/c8-account-profiling-integration`.
>
> **Scope:** This acceptance closes M8D R1 only. It does not compose the R2 shared job contract or
> the R3–R6 replacement entity agents.

## 1. Boundary implemented

New entity research is fail-closed at both production entry classes:

1. A project run reaching `DEEP` is handled by `EntityResearchQuarantinePhaseHandler`, which raises
   `entity_research_agent_not_composed` before a scheduler, account profiler, provider preparer,
   committee preparer, or contact preparer can run.
2. Historical entity-research tool descriptors are wrapped by `ReplayOnlyEntityResearchTool`.
   Completed journal/idempotency records can still replay under the exact historical address and
   schema; every cache miss fails the same reason before the historical tool body is invoked.

The exact replay-only addresses are:

```text
enrich_account_gaps@1
enrich_selected_accounts@1
launch_account_deep@1
profile_contact@1
profile_contact@2
research_account_gaps@1
research_account_gaps@2
resolve_committee@1
run_deep_account@1
```

The address set is deliberately version-exact. A future replacement version is not silently
quarantined, and it cannot inherit authority merely by reusing an old name.

## 2. Active composition removed

The production fleet and per-run composer no longer construct or inject:

- the `create_deep_agent()` account-research runtime or governed gap profiler;
- pre-agent Exa Deep account acquisition;
- pre-agent Sumble Teams/People committee acquisition;
- account-deep scheduler, locks, supervisor controls, or provider-neutral preparation callbacks;
- mechanical contact preparation or automatic account-to-contact progression; or
- the old universal coverage-controller decision path.

The account-research deepagent profile is no longer active. Old account profiles and the
`account-research-unit-v1` recipe asset remain on disk as historical definitions, but the recipe is
not seeded as a current system recipe and its entity-research tool calls are replay-only.

## 3. Infrastructure deliberately retained

R1 does not delete accepted provider or data substrate code. The following remain available for
the replacement composition:

- Exa and Sumble transports, operation state machines, polling, immutable snapshots, receipts,
  settlement, and replay;
- claim materialization, evidence, provenance, identity, verification, governance, and handoff;
- discovery-stage Exa Websets and Sumble discovery enrichment, which are not entity research; and
- provider lifecycle workers needed to finish already-authorized durable operations.

Keeping a lifecycle worker alive does not authorize a new entity-research operation. Originating
tools and the DEEP composition are the quarantined boundaries.

## 4. Executable exit-gate evidence

The R1 battery proves:

- every forbidden historical tool address is wrapped in the live toolbelt;
- a cache miss returns `entity_research_agent_not_composed` and invokes no former provider body;
- an exact completed idempotency record replays without invoking that body;
- production composition has no reference to the removed agent/provider/preparer collaborators;
- the per-run DEEP handler fails loudly and the old constructor seams no longer exist;
- active agent capability disclosure marks the retired entity tools replay-blocked;
- the historical recipe is not seeded, while its pinned file remains loadable; and
- the accepted provider, coverage, contact-research, durability, and claim suites remain green.

Verification commands:

```text
.venv/bin/pytest -q tests/api/test_m8d_r1_entity_research_quarantine.py \
  tests/api/test_run_composition.py tests/api/test_agent_platform_wiring.py \
  tests/execution/test_recipes.py tests/api/test_agent_registry_wiring.py \
  tests/api/test_toolbelt_wiring.py tests/projections/test_emitter_callsite.py \
  tests/api/test_clue_trial_spine.py tests/fleet/test_b4_composed_run_db.py

.venv/bin/pytest -q tests/api/deep tests/api/test_exa_deep_acquisition_e1.py \
  tests/api/test_exa_deep_http_transport_e1.py tests/api/test_exa_deep_materialization_e2.py \
  tests/api/test_sumble_account_gaps_s1.py tests/api/test_sumble_committee_acquisition_s2b.py \
  tests/api/test_sumble_committee_eligibility_s2d.py \
  tests/api/test_sumble_committee_preparation_o2.py \
  tests/api/test_sumble_committee_preparation_wiring_o2.py \
  tests/api/test_sumble_committee_source_s2c.py tests/contact_research tests/coverage \
  tests/resolvers/test_exa_deep.py tests/resolvers/test_exa_deep_contract_a0.py \
  tests/resolvers/test_exa_deep_wire_e0.py tests/resolvers/test_sumble.py \
  tests/resolvers/test_sumble_committee_contract.py
```

The repository-wide run also exposed two failures outside the R1 boundary:

- the shared database contains a stale `core.work_email` definition relative to unrelated current
  worktree changes, causing `FieldRedefinitionError` during the DSAR fixture bootstrap; and
- `approve_contact_research_selection@1` exposes trusted workspace/project fields in a model-facing
  schema, an existing contact-selection authority issue not introduced or widened by R1.

Neither failure can originate a quarantined provider operation. They remain separately owned and
are not hidden by the R1 acceptance result.

## 5. Exit decision

R1 is accepted. New entity research has one loud failure mode, exact historical replay is retained,
the invalid orchestration has no production composition root, and the provider/durability/claim
substrate remains intact for R2 onward.
