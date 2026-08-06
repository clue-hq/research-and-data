# M8D R0 — Authority contract and forbidden-flow acceptance

> **Status:** accepted for R0 on 2026-08-06.
>
> **Scope:** contract types, canonical fixtures, schema fingerprints, and rejection tests only.
> No runtime composition, provider adapter, database schema, launch path, credential, or spend
> control was widened.

## 1. Frozen authority

The shared-kernel contract in `clue_core.entity_research` makes the M8D ownership split explicit:

| Component | Frozen authority |
|---|---|
| Head-of-ABM | The one user-facing `deepagents.create_deep_agent()` component |
| Shared fleet | One subject-neutral mechanical queue/lease/wait shell; no tool choice or provider dispatch |
| Job controller | One subject-neutral durable envelope; no tool choice or provider dispatch |
| Account agent | Exactly one `langchain.agents.create_agent()` class with account semantic tools |
| Contact agent | Exactly one `langchain.agents.create_agent()` class with contact semantic tools |
| Facet agent | Optional `langchain.agents.create_agent()` child under the bounded facet policy |
| Engine service | The only component class allowed to dispatch an admitted provider request |

Account and contact agents receive closed provider-neutral tool surfaces. Provider SDK tools and
the superseded `research_account_gaps`-only surface are invalid contract states. Channel reveal
and independent validation are paired; no environment switch can represent validation.

## 2. Frozen lifecycle and authorization

The selection and job contracts carry exact workspace, project, product, project-run, directive,
field plan, source plan, admitted fields and sources, questions, facets, channel permissions,
policy references, budget envelope, approval references, and selected entity identities.

- Account research requires its own user-confirmed launch and contains account profiling plus
  committee discovery, but no contact deep research.
- Contact research requires a later, separate confirmation and contains only contact research.
- A contact job must be present in the exact selection, strongly identity-resolved, and linked by
  evidence to the exact account.
- Committee membership is one valid selection basis, not a prerequisite. The canonical fixture
  also admits a user-selected, identity-resolved non-committee contact.
- No run can create an automatic successor run.

## 3. Frozen source, tool, result, and causation contracts

Field attempts can reference only sources in that field's effective plan. The canonical
qualitative plan starts with `exa_deep`; injecting `deterministic_exact` when it is absent from the
plan is rejected.

A governed tool request records exact run, job, subject, target, agent turn/execution, tool
identity/version/input digest, field/source plans, fields, sources, questions, budget reservation,
idempotency, and complete follow-up lineage when applicable.

A completed tool result is valid only after it carries request, raw response, retained content,
normalized-result, provider-receipt, and cost-settlement references. Every requested field appears
exactly once as found, null, unsupported, conflicting, or rejected. Found values retain evidence;
rejections retain their decision records; inline and indexed delivery remain lossless.

Provider causation requires the durable order:

```text
agent turn starts
    -> governed tool call is journaled
    -> provider operation is reserved
    -> provider request is dispatched
```

An additive follow-up must carry the parent operation, exact observed result, and typed reason as
one all-or-none lineage set.

## 4. Frozen facet, parallelism, and finalization contracts

Facet delegation is optional, depth one, limited to one or two children, non-recursive, and charged
to the parent budget. Parallel calls require engine admission, distinct atomic reservations,
provider rate-limit authority, no in-batch dependency, and no overlapping fields unless all calls
are explicitly authorized corroboration. Repeated calls to one tool/provider are parallel only as
distinct admitted facets.

A finalization proposal cannot coexist with pending provider work. It includes immutable coverage,
claim-delta, spend, identity/use/verification, state, evidence, result, and review references. A
`COMPLETED` proposal has no unresolved fields; `NEEDS_REVIEW` has durable review flags. The engine
must verify every gate against the same state digest. A terminal job requires the accepted engine
receipt; a model message alone has no terminal authority.

## 5. Executable forbidden-flow battery

The fixture battery rejects 56 named cases across these boundaries:

| Boundary | Rejected examples |
|---|---|
| Agent ownership | Entity deepagent substitution, agent/controller provider dispatch, controller tool choice, duplicate contact agent |
| Tool authority | Gap-only account surface, provider SDK exposure, reveal without validation |
| Selection and locality | Account channel/contact-identity authority, cross-axis fields, weak/unassociated contacts, unproved committee member, unselected/cross-scope/wrong-account job |
| Lifecycle | Unconfirmed launch, automatic successor, account-to-contact or contact-to-account operation leakage |
| Source planning | A manufactured deterministic attempt absent from the effective field plan |
| Tool/result integrity | Parentless or cross-axis requests, wrong entity tool, partial follow-up lineage, missing raw data/field/value/evidence/rejection decision |
| Provider causation | Dispatch before the agent tool journal, partial operation follow-up lineage |
| Facets and concurrency | Excess-depth/count, recursive or separately funded facets, unadmitted/dependent/shared-budget/cross-axis/overlapping/duplicate parallel work |
| Finalization | Pending work, unresolved completed state, review without flags, stale state, unreconciled spend, transcript-only completion |

The test suite also fingerprints 13 public JSON schemas. Contract widening therefore requires an
explicit R0 contract-version decision rather than silently passing old examples.

## 6. Exit evidence and boundary

The R0 focused gate is:

```bash
.venv/bin/pytest -q tests/unit/core/test_entity_research_r0_contracts.py
```

It passes canonical fixtures and proves that each forbidden fixture fails validation. “Tests fail
against a forbidden old flow” means the forbidden payload is rejected while the test suite remains
green; R0 intentionally does not leave the repository with expected-red tests.

R0 does **not** claim that the current active runtime already implements these contracts. R1 owns
dependency-guided quarantine of pre-agent provider acquisition, gap-only/deepagent entity paths,
generic deterministic-first initialization, automatic contact progression, and mechanical contact
research ownership. No R1 code was changed here.
