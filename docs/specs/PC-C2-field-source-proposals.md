# Phase C2 — Field/Source Proposals and Generic Tier-3 Web Resolution

**Status:** ready for implementation

**Parent:** [`PC-phase-c-agentic-layer.md`](./PC-phase-c-agentic-layer.md)

**Shared contracts:** [`PC-C0-step4-contract-freeze.md`](./PC-C0-step4-contract-freeze.md)

**Requirement:** harness REQ-03

---

## 1. Outcome

C2 lets the platform notice and investigate important concepts/sources the current registry did
not anticipate, without giving an LLM authority to declare durable schema or trust.

The split is binding:

```text
notice / nominate     agent or human may do
acquire at tier 3     governed generic resolver may do
assign trust          policy/human does
promote to registry   audited engine path does
```

No out-of-registry ICP/interview concept is silently discarded.

---

## 2. Scope

### Included

- field/source proposal stores and shared decision service;
- `propose_*` and `decide_*` tools;
- proposal projections;
- ICP-synthesis un-drop path;
- promotion into existing registries;
- human/policy authority matrix;
- a generic tier-3 web resolver behind existing source seams;
- yield-backed demotion/disable path for policy-promoted tier-3 sources.

### Excluded

- arbitrary provider SDKs in proposal code;
- agent-assigned tier 1/2 trust;
- coverage retry policy (C1);
- upload ingestion (C3);
- interview/readiness orchestration (C4);
- autonomous promotion of personal/sensitive field classes.

---

## 3. Durable proposal model

`field_definition_revision` stores the full proposed `FieldDef` plus registry-local validation,
corroboration, equality, description, pack, and version fields.

`source_manifest_revision` stores the full proposed `SourceManifest`/registry wrapper plus:

- discovery URL/domain;
- capability/yields;
- proposed rationale and evidence refs;
- policy-assigned tier;
- auth/rate-limit requirements;
- workspace/brand/product/project coordinates and nullable ICP lineage (proposals can precede ICP
  synthesis);
- yield/demotion metadata.

Both stores carry:

```text
status
proposed_by_actor
proposed_by_ref
proposed_at
required_authority
decided_by
decided_at
decision_reason
applied_version
```

Proposal payloads are immutable. Decisions transition status with a locked compare-and-set;
re-proposal is idempotent on a canonical payload hash + scope.

---

## 4. Authority matrix

### Fields

| Proposal | Minimum authority |
|---|---|
| non-personal canonical/pack field within policy | policy or human |
| `contact.*` / `contact.facet.*` | human |
| sensitive/special-category field | human, and promotion still defaults disabled for outreach |
| undeclared `<pack>.*` reuse scope | invalid; cannot stage as promotable |

### Sources

| Proposed tier/use | Minimum authority |
|---|---|
| tier 3 public web, policy allows | policy with complete audit |
| tier 1 or tier 2 | human |
| personal-data source | human plus compliance policy |
| provider requiring credentials | human/admin setup; proposal may exist but cannot become runnable |

The agent can suggest a tier in rationale, but it is not persisted as the assigned tier.

---

## 5. Generic tier-3 web resolver

The resolver:

- implements the existing `Resolver` protocol;
- is bound to a registered generic tier-3 manifest at the API root;
- accepts an approved/temporarily governed URL/domain target;
- uses the existing scrape adapter and snapshot binding;
- target-locks queries to the resolved entity;
- runs behind `SourceGate` before network spend;
- emits ordinary typed claims with evidence spans;
- never promotes an unregistered field itself;
- never upgrades source trust from page content;
- never serves as a tier-1/2 resolver.

Discovery and durable registration are distinct. A one-off governed investigation may use the
generic tier-3 manifest while a reusable source nomination remains `PROPOSED`.

---

## 6. ICP/interview un-drop behavior

The current ICP synthesis path drops fields it cannot map to the registry. C2 changes only that
boundary:

```text
registered field        → ordinary ICP proposal slot
well-formed new concept → field proposal ref attached to co-confirmation
unsafe/malformed concept → rejected proposal record with a reason
```

The C4 interview routes unmapped statements through the same C2 proposal service by protocol. C2
does not own interview turns or readiness.

---

## 7. Tools and projections

Implement the four C0-frozen tools:

- `propose_field`;
- `decide_field_proposal`;
- `propose_source`;
- `decide_source_proposal`.

Decision inputs include an explicit decision and reason, never an arbitrary replacement payload.
A changed payload is a new proposal.

Implement:

- `field_proposals`;
- `source_proposals`.

Projection cards show the proposal summary, provenance refs, required authority, status, decision,
and applied registry version/key. They do not expose secret/auth material.

---

## 8. Owned and forbidden surfaces

### Owns

- `subsystems/research/clue_research/proposals/**`;
- C2 migrations;
- a distinct generic-web resolver package;
- the narrow out-of-registry branch in `stage0/icp_synthesis.py`;
- `platform/api/clue_api/proposal_tools.py`;
- `platform/projections/clue_projections/proposals.py`;
- C2 tests.

### Must not edit/finalize

- coverage, ingestion, onboarding, interview, readiness stores;
- C1/C3/C4 packages;
- central API/tool/projection aggregation;
- C4 Recipe #0.

---

## 9. Verification

Required tests:

1. out-of-registry ICP output becomes a visible proposal;
2. identical proposal is idempotent;
3. concurrent decisions apply at most once;
4. promotion makes a field/source immediately discoverable by its live registry;
5. agent/policy cannot promote `contact.facet.*`;
6. agent/policy cannot assign/promote tier 1/2;
7. `<pack>.*` without `reuse_scope` fails closed;
8. malformed field keys and invalid manifest yields reject loudly;
9. generic resolver snapshots evidence and returns claim refs;
10. generic resolver records `gate_decision` before network spend;
11. contact claims receive born binding/use classification;
12. target locking prevents same-name/entity drift;
13. cross-workspace proposal access fails closed;
14. yield demotion is audited and affects new plans only;
15. no provider SDK import escapes its resolver package.

Run the standing Phase-C and DB/migration gates.

---

## 10. Exit gate

C2 is complete when an agent can preserve and nominate a genuinely new field/source, investigate a
new public web source at governed tier 3, and make an approved proposal live without deployment—
while remaining unable to self-award authoritative trust or personal-data permission.
