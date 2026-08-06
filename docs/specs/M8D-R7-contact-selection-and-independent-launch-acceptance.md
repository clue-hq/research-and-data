# M8D R7 — Contact selection and independent launch acceptance

**Status:** accepted 2026-08-06
**Roadmap:** `M8D-entity-research-agents-and-shared-fleet-refactor-roadmap.md` §14 R7

## 1. Accepted boundary

R7 makes contact research a separately selected and separately launched unit of work. It does not
start automatically after account research, and it does not require a contact to belong to the
buying committee.

An accepted launch has two attributable human actions:

1. approve an exact, immutable contact-selection receipt; and
2. confirm launch of that exact active receipt and its exact reviewed budget.

The launch creates `CONTACT_RESEARCH` jobs on the subject-neutral R2 fleet. It makes no provider
call and constructs no contact agent. R8 owns contact `langchain.agents.create_agent()` execution;
R10 owns bounded credentialed Exa/Sumble acceptance and cutover.

## 2. Exact selection authority

Every target is one canonical contact under one exact canonical account. The receipt freezes, per
contact rather than as a permissive run-wide union:

- selection basis: committee member or user-selected associated contact;
- strong identity claims and current-account association claims;
- committee role/persona claims when and only when committee membership is the basis;
- selected contact fields and the exact source keys authorized for each field;
- directional question identifiers and the exact facet fields they target;
- email/phone permission, reveal sources, validators, and their independent caps;
- source, jurisdiction, use, retention, freshness, and contact-policy pins;
- a positive target-local research budget and content-addressed budget reference; and
- selection and launch approval references.

The run-wide R0 selection is only an index. Its fields, sources, questions, facets, channels,
policies, and approvals must equal the exact union of the target-local authorities. A job consumes
only its own `SelectedContactResearchAuthority`; it cannot borrow another contact's source, facet,
question, channel, or budget.

## 3. Admission and launch rules

`ContactResearchSelectionApprover` validates current Postgres state before persisting authority:

- workspace, project run, account run, account, product, directive pin, and effective ICP config
  must agree;
- the directive must be confirmed and must allow contact profiling;
- the contact must be unmerged, strongly identity-resolved, and keyed to the exact account;
- every evidence claim must exist in the workspace and belong to that contact;
- committee admission requires current role and persona claims from the exact account run;
- non-committee admission forbids committee claims and instead requires explicit association
  evidence;
- fields, questions, sources, facets, channel operations, policies, provider caps, and budget must
  be closed subsets of the effective directive and contact policy; and
- the new receipt is either a human initial selection or the sole linear human successor.

`ContactResearchFleetLauncher` accepts only the active current receipt, its exact content hash, an
explicit human selection approval, a second attributable launch operation, and a budget equal to
the exact sum reviewed in the receipt. A repeated operation is idempotent only when its entire
authority is unchanged.

Automatic directive-confirmation committee materialization remains useful preparation state, but
it is deliberately insufficient launch authority.

## 4. Durable enforcement

Migration `02e552db75da` adds or strengthens:

- human-initial and human-successor contact-selection approvals;
- committee/non-committee selection guards over current identity and association evidence;
- `entity_research_run.contact_selection_id` and its scoped foreign key;
- immutable `entity_research_contact_launch` receipts;
- immutable per-job `entity_research_contact_job_authority`; and
- a deferred `entity_research_contact_run_complete` constraint trigger.

At commit, every contact run must have one active current selection, one separate launch receipt,
and an exact job-authority row for every and only selected contact. Direct R2 insertion, a stale or
cancelled selection, missing approval, partial job authority, or changed replay fails atomically.
Launch, cancellation, and successor approval also share one selection-scope transaction lock. A
selection with nonterminal R2 jobs cannot be cancelled or superseded; the shared fleet must first
accept terminal/cancellation receipts, preventing active jobs from losing their authority mid-run.

Historical pre-R7 M8C committee receipts remain reconstructable for exact replay through their
discovery-provenance claim. New R7 human selections always persist explicit association,
field/source, facet, and target-budget authority.

## 5. Acceptance evidence

The isolated Postgres acceptance suite proves:

- one committee member and one governed non-committee contact can share a run while retaining
  different target-local budgets and exact authority;
- the non-committee contact has no committee role/persona claim and is admitted only through
  identity plus current-account association;
- selection and launch replay create exactly one receipt, one run, and one job per target;
- changed replay authority, cross-contact evidence, automatic-only selection, stale selection,
  cancelled selection, active-run selection invalidation, and a direct unselected contact run
  create zero new contact jobs;
- launch creates queue tasks but zero provider, external-research, or channel operations; and
- the R7 migration downgrades to `4ff507129dd5`, upgrades to `02e552db75da`, and leaves exactly one
  Alembic head.

Verification completed:

- R7 isolated-database acceptance: 5 passed after a migration round trip;
- combined retained M8C C0–C7 and M8D R0–R7 regression matrix: 188 passed;
- scoped Ruff, repository mypy over 557 source files, and all 24 import contracts: passed; and
- Alembic downgrade/upgrade and one-head checks: passed.

No live or paid provider request was made or claimed as evidence for R7. That is intentional: a
selection/launch slice must prove authorization and zero premature spend. R8 and R10 retain their
roadmap gates unchanged.

The repository-wide `make check` diagnostic remains red outside R7: its formatting gate names 12
non-R7 files already present in the shared dirty worktree. A full-suite diagnostic also identifies
two stale account-deep tests and one targeted-enrichment wait that still expect the R1-quarantined
mechanical flow to start; they fail or wait on the intended `entity_research_agent_not_composed`
boundary. The retained R1/R2–R7 matrix passes, and those unrelated files were not modified to hide
the incompatibility.
