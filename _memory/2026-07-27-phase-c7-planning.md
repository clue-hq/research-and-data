# Phase C7 planning checkpoint — structured research views

**Date:** 2026-07-27
**Branch:** `platform/c7-research-views`
**Base:** completed C6 head `7755bea`
**State:** planning/documentation complete and committed locally; implementation has not started

## Outcome

- Created the dedicated C7 branch requested by the founder.
- Added the binding child spec:
  `docs/specs/PC-C7-research-views-derivations-and-handoff.md`.
- Added the cross-session implementation plan:
  `docs/superpowers/plans/2026-07-27-phase-c7-research-views.md`.
- Updated the Phase C index/parent, harness REQ-05/O11 ruling, architecture map, and old C6→C7
  handoff pointer.

## Product ruling captured

“Dossier” is a structured, provenance-resolving research view for normal account/contact pages,
not a canonical Markdown/HTML/file body. The frontend renders typed sections/items and evidence
actions. A saved version is a reference-only composition receipt. The nine-block vocabulary and
`compose_dossier` name remain compatibility surfaces over the same references.

The account view preserves separate identity, scoring, research, committee, activity, and coverage
authorities. The contact view separates display eligibility, outreach eligibility, and explicit
personalization selection. The downstream plan/approval screen is not owned by C7.

## Binding decisions

- Add an immutable `ClaimFlavor.DERIVED`; derivation evidence is normalized support-claim edges.
- Derived claims never win factual `current_value`; research views select direct current values
  and accepted derivations separately.
- Entailment uses the existing governed gateway behind a verification protocol; the engine owns
  promotion, policy, confidence, and state.
- New entailment rows store bounded reason codes, not raw model rationale.
- Dependency eligibility is resolved live; superseded/rejected/expired/erased supports invalidate
  dependents.
- Snapshots store ids, pins, order, reachable subjects, and hashes only.
- Evidence actions go through one API-root authorization service; no route/tool calls
  `StorageBackend.presign` directly.
- Re-check is additive and may request research only through existing C5/C6 durable operations.
- `HandoffCommitteeReader` production implementation is composed at the API root.
- Legacy dossier routes/events/tools share the research-view service and persistence.

## Current substrate findings

- Merge conflict already uses field `equality_mode`; C7 adds joint consumption tests rather than
  duplicating logic.
- Retention sweep currently tombstones expired personal claims, but C7 still needs a fail-closed
  selector/composition test.
- `faithfulness_verdict.rationale` needs a one-way personal-text redaction path.
- `StorageBackend.presign` exists without a C7 access-policy consumer; add the policy before use.
- `Claim.product_id` already exists. Fit remains scoring-owned; contact class is an optional
  registered projection value, not a guessed enum.
- `narrative/handoff_store.py` materializes an `account_handoff.payload`; C7.4 must replace it with
  references or prove subject-indexed purge/rebuild for legacy rows before closeout.
- `HandoffCommitteeReader` has only a fake/injected seam; production composition is absent.

## Implementation sequence

1. C7.0 core contracts + executable frontend/adversarial fixtures.
2. C7.1 equality/expiry/rationale/presign/product prerequisite closure.
3. C7.2 derivation + entailment substrate.
4. C7.3 account/contact live composition.
5. C7.4 reference snapshots + evidence actions.
6. C7.5 additive re-check.
7. C7.6 production committee reader + real handoff.
8. C7.7 tools/API/projections/events/legacy adapters.
9. C7.8 adversarial/DSAR/full repository closeout.

## Verification performed

- Read the C6 closeout and Phase C planning memory.
- Audited Phase C C7/C8, harness REQ-04/05/14/15/16 and O11, Doc S boundary, compliance, M12
  handoff, coverage projections, toolbelt replay contracts, claim/current-value models, retention,
  storage presign, and current API composition gaps.
- Read the linked frontend plan contract/PRD and reconciled its older document-oriented dossier
  wording with the newer founder-provided account/contact screenshots and conversation.
- Checked all relative Markdown targets across the nine changed/new planning files; all targets
  exist.
- `git diff --check` passed after removing one trailing-whitespace marker.

## Next exact entry

The next implementation session starts at C7.0 in
`libs/clue-core/clue_core/research_view.py`; no migration or tool handler should land before its
contract and fixture gate is green.

## Preserve

Unrelated untracked `.claude/`, `.codex/`, and
`docs/architecture/clue-hq-research-model-surface.md` existed before this work and must remain
untouched.
