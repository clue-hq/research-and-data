# Phase C0 — Step-4 Contract Freeze

**Status:** frozen for implementation

**Parent:** [`PC-phase-c-agentic-layer.md`](./PC-phase-c-agentic-layer.md)

**Authority:** this document governs shared contracts and worktree ownership for C1–C4. The four
child specs govern behavior inside their owned lanes. If a child spec conflicts with this document
on a shared type, table owner, tool name, projection name, or integration fixture, C0 wins until a
reviewed contract-delta changes it.

---

## 1. Outcome

C0 makes the four Step-4 lanes independently implementable without letting them invent competing
versions of coverage, proposal, ingestion, onboarding, or readiness state.

It freezes:

1. the shared vocabulary and reference shapes crossing C1–C4;
2. exact schema ownership;
3. exact tool and projection names;
4. shared integration fixtures and acceptance journeys;
5. the only files each worktree may own;
6. how C8's pre-spend and identity-binding prerequisites apply to new paths;
7. integration and parallelization rules.

C0 is a contract/documentation slice. It does not create tables, tools, projections, or agents.
Runtime implementation begins in C1–C4 after this freeze is reviewed.

---

## 2. Baseline verified before the freeze

The contracts below extend the live repository rather than restating hypothetical architecture:

- `Tool`, `ToolInput`, `ToolContext`, and reference-only `ToolResult` already exist in
  `platform/toolbelt`.
- concrete tools are thin adapters constructed at `platform/api`; the toolbelt is the only domain
  write path for humans and agents;
- `clue_projections` is read-only and already serves run overview, account progress, readiness,
  and manifest views;
- `FieldDef`, `SourceManifest`, the field/source registries, `Resolver`, `SourceGate`, and
  `ClaimTagger` are live shared seams;
- `StorageBackend`, the content-addressed `artifact` row, snapshot binding, and DSAR artifact
  lifecycle are live;
- the adapter pipeline and `ClaimExtractor` seam are live, including passthrough, PDF,
  transcription, and scrape adapters;
- `config_revision` already supplies the proposal → promote/reject precedent;
- the existing deep/account/contact/tier-4 claim-producing paths already route through
  `PreSpendGate.check`, with DB-backed integration tests proving that a gate decision precedes
  paid resolution;
- the current Stage-0 `client_kb.py` and CRM enrichment in `import_accounts.py` still call the
  waterfall without a pre-spend seam; C4 must close both before Recipe #0 is live;
- contact-facet claims already receive the authoritative per-claim identity-binding classification
  before immutable insert at the API composition root;
- Stage 0's current `ClientInput`/`VolunteeredMaterial` types are transient capability inputs, not
  the durable onboarding record required by Phase C;
- `project_run` pins workspace, project, brand, and ICP version, but does not yet pin the client-KB
  version, product id, or product-context version.

Two similarly named existing types remain distinct:

- discovery `CoverageReport` estimates open-ended discovery coverage;
- Phase-C research coverage records field attempts and terminal gaps.

C1 must not overload or reinterpret the discovery type.

---

## 3. Shared contract vocabulary

### 3.1 Identity and ID representation

New durable records use UUID primary keys and `NewType` wrappers at Python boundaries:

```python
CoverageAttemptId = NewType("CoverageAttemptId", UUID)
CoverageDecisionId = NewType("CoverageDecisionId", UUID)
FieldProposalId = NewType("FieldProposalId", UUID)
SourceProposalId = NewType("SourceProposalId", UUID)
IngestionJobId = NewType("IngestionJobId", UUID)
IngestionSegmentId = NewType("IngestionSegmentId", UUID)
OnboardingInputId = NewType("OnboardingInputId", UUID)
ReconRunId = NewType("ReconRunId", UUID)
VolunteeredStatementId = NewType("VolunteeredStatementId", UUID)
ProductContextVersionId = NewType("ProductContextVersionId", UUID)
ReadinessDecisionId = NewType("ReadinessDecisionId", UUID)
ReadinessOverrideId = NewType("ReadinessOverrideId", UUID)
```

IDs cross HTTP/tool boundaries as strings. Existing text spine ids remain unchanged:
`workspace_id`, `brand_id`, `product_id`, and `project_id`. Existing `EntityId`, `ClaimId`,
`ProjectRunId`, `RunId`, and artifact `storage_key` types are reused.

Each ID factory lives with the package that owns the corresponding row. Only the ref models below
belong in `clue_core`; lane-internal row models stay in their lane.

### 3.2 Shared enums

These closed vocabularies cross lane or projection boundaries and therefore have one canonical
definition in `clue_core`:

```python
class ResearchAttemptOutcome(StrEnum):
    CLAIMS_PRODUCED = "claims_produced"
    NO_HIT = "no_hit"
    BLOCKED = "blocked"
    BUDGET_STOP = "budget_stop"
    FAILED = "failed"

class ResearchTerminalStatus(StrEnum):
    FILLED = "filled"
    UNFILLED_TERMINAL = "unfilled_terminal"
    BLOCKED_BY_POLICY = "blocked_by_policy"
    BUDGET_EXHAUSTED = "budget_exhausted"

class ProposalStatus(StrEnum):
    PROPOSED = "proposed"
    PROMOTED = "promoted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"

class ProposalAuthority(StrEnum):
    POLICY = "policy"
    HUMAN = "human"

class IngestionStatus(StrEnum):
    QUEUED = "queued"
    SNAPSHOTTED = "snapshotted"
    EXTRACTING = "extracting"
    COMPLETED = "completed"
    FAILED = "failed"
    ERASED = "erased"

class OnboardingInputKind(StrEnum):
    WEBSITE = "website"
    USER_TURN = "user_turn"
    UPLOAD = "upload"
    PASTED_TEXT = "pasted_text"
    CRM_REFERENCE = "crm_reference"

class ReadinessGate(StrEnum):
    ICP_SYNTHESIS = "icp_synthesis"
    DISCOVERY_SPEND = "discovery_spend"
    DEEP_SPEND = "deep_spend"

class ReadinessVerdict(StrEnum):
    READY = "ready"
    NOT_READY = "not_ready"
    OVERRIDDEN = "overridden"
```

Lane-local operational enums—adapter error codes, proposal reason codes, recon event names, or
goal-judge verdict details—stay in the owning package unless a later consumer proves they cross a
real seam.

The existing `Claim` contract receives one additive, immutable context field in C4:

```python
product_id: str | None = None
```

It is required for product-scoped `client.*` truth, nullable for product-neutral account/contact
truth and for legacy client-level claims. A non-null `product_id` requires a tenant-private
`workspace_id` and a same-workspace product FK. It is part of claim idempotency/scope reads and
cannot be attached after insert. This is the missing product dimension required by REQ-22; the
`product_context_version` manifest references claims but does not substitute for their scope.

The existing `ICPSpec` contract receives immutable nullable lineage fields in C4:

```python
client_entity_id: EntityId | None = None
client_kb_version: int | None = None
product_id: str | None = None
```

Legacy/manual specs may leave them null. Every C4 harness confirmation must populate all three
(with a confirmed product) so `start_confirmed_project_run` can validate the exact
Client-KB→ICP→product relationship instead of trusting tool inputs.

### 3.3 Cross-lane reference models

All models are frozen, `extra="forbid"`, and carry references rather than bodies:

```python
class ResearchGapRef(BaseModel):
    run_id: RunId
    project_run_id: ProjectRunId | None = None
    entity_id: EntityId
    field_key: FieldKey
    tier: str
    terminal_status: ResearchTerminalStatus | None = None
    latest_attempt_id: CoverageAttemptId | None = None

class FieldProposalRef(BaseModel):
    proposal_id: FieldProposalId
    field_key: FieldKey
    status: ProposalStatus

class SourceProposalRef(BaseModel):
    proposal_id: SourceProposalId
    source_key: str
    status: ProposalStatus

class IngestionJobRef(BaseModel):
    ingestion_job_id: IngestionJobId
    artifact_key: str
    status: IngestionStatus

class OnboardingInputRef(BaseModel):
    onboarding_input_id: OnboardingInputId
    artifact_key: str
    kind: OnboardingInputKind

class ProductContextRef(BaseModel):
    workspace_id: str
    brand_id: str
    product_id: str
    version_id: ProductContextVersionId

class ReadinessSnapshotRef(BaseModel):
    readiness_decision_id: ReadinessDecisionId
    gate: ReadinessGate
    verdict: ReadinessVerdict
    spec_version: int
    gap_refs: tuple[ResearchGapRef, ...] = ()
```

The references deliberately do not contain claim values, interview text, uploaded content,
proposal payloads, recon prose, or readiness explanations. Those are resolved through scoped
projections. This preserves the existing “workers/tools return references, not blobs” rule.

`ResearchGapRef.run_id` is the generic research-run coordinate already stamped on claims. A
project/account gap also carries `project_run_id`; onboarding recon does not yet have a project and
therefore leaves it null. C1 must not require a C4 `recon_run` FK: C4 links its recon envelope to
the existing `RunId`, preserving C1 → C4 migration independence.

### 3.4 Coordinates shared by Stage 0

Every onboarding/recon/interview/readiness row carries:

```text
workspace_id                    required
brand_id                        required
product_id                      nullable only until product resolution
project_id                      nullable during workspace onboarding; required at project kickoff
client_entity_id                nullable until client identity resolution
```

Rules:

1. There is no workspace-global singleton Client-KB or onboarding record.
2. Product-level durable truth is keyed by the selected product when known.
3. A project may inherit brand/product context but project instructions remain project-scoped.
4. A cross-workspace reference fails closed and must not reveal whether the foreign object exists.
5. Raw bodies live in artifact storage; relational rows store hashes, offsets, and references.

### 3.5 Config shapes and ownership

Each lane adds one distinct module under `libs/clue-config/clue_config/`; shared export aggregation
is integration-owned. Config is frozen, `extra="forbid"`, versioned when persisted, and cannot be
overridden from prompt/tool inputs.

```python
class ResearchLoopPolicy(BaseModel):                 # C1 / coverage.py
    max_rounds_by_tier: dict[str, int]
    max_gap_fields_per_round: int
    marginal_yield_floor: float
    strategy_transitions: dict[str, tuple[str, ...]]

class ProposalPolicy(BaseModel):                     # C2 / proposals.py
    auto_promote_tier3_sources: bool
    human_field_classes: frozenset[FieldClass]
    human_source_tiers: frozenset[int]
    min_observations_for_yield: int
    demotion_yield_floor: float

class IngestionPolicy(BaseModel):                    # C3 / ingestion.py
    max_bytes: int
    allowed_media_types: frozenset[str]
    max_segments: int
    max_retries: int
    ocr_enabled: bool

class ReadinessFloor(BaseModel):                     # C4 / stage0.py
    required_field_keys: tuple[FieldKey, ...]
    min_coverage_ratio: float
    min_verified_claims: int
    max_open_policy_blocks: int
    require_product_id: bool
    require_confirmed_icp: bool

class ReadinessSpec(BaseModel):
    version: int
    floors: dict[ReadinessGate, ReadinessFloor]

class Stage0Policy(BaseModel):
    fast_budget_cents: CostCents
    background_budget_cents: CostCents
    recon_dedupe_ttl_seconds: int
    readiness: ReadinessSpec
```

Validation:

- ratios/yield floors are within `[0, 1]`;
- round/segment/retry limits and budgets are non-negative, with rounds/segments at least one;
- `ProposalPolicy.human_field_classes` must include `CONTACT` and `CONTACT_FACET`;
- `human_source_tiers` must include 1 and 2;
- all three `ReadinessGate` entries are present;
- readiness does not require CRM;
- `DEEP_SPEND` requires a product id and confirmed ICP by default;
- C1 strategy keys in transitions must exist in the registered strategy catalog.

Per-workspace overrides are versioned data read by the engines. Environment settings select
backends and absolute safety ceilings only.

---

## 4. Exact schema ownership

| Table / schema change | Owner | Contract |
|---|---|---|
| `coverage_attempt` | C1 | Append-only attempt per full `(run_id, entity, field, tier, round, strategy)` key; `project_run_id` is nullable for pre-project recon; cost and produced claim refs are auditable. |
| `coverage_decision` | C1 | Append-only round/terminal decision; at most one terminal decision per `(run_id, entity, field, tier)`; terminal reasons are human-readable and machine-coded. |
| `field_definition_revision` | C2 | Workspace/context-scoped staged `FieldDef` payload and decision audit; ICP coordinates are nullable before synthesis; promotion alone calls the live registry. |
| `source_manifest_revision` | C2 | Workspace/context-scoped staged `SourceManifest` payload and decision audit; ICP coordinates are nullable before synthesis; trust tier is policy/human assigned, never proposer assigned. |
| `ingestion_job` | C3 | Durable upload/URL ingestion lifecycle keyed by content hash + declared context. |
| `ingestion_segment` | C3 | Stable segment coordinates into the stored artifact/canonical extracted representation. |
| `onboarding_input` | C4 | Brand-aware durable input metadata pointing to stored raw bodies. |
| `recon_run` | C4 | Fast/background recon envelope, lifecycle, dedupe key, cost, and Recipe-#0 compatibility refs. |
| `volunteered_statement` | C4 | Preserved unmapped user statement with evidence coordinates and routing/promotion state. |
| `product_context_version` | C4 | Immutable manifest of claim, memory, artifact, and identity refs used as the reproducible product-context pin. |
| `readiness_spec_revision` | C4 | Versioned floors/policy for the three readiness gates. |
| `readiness_decision` | C4 | Append-only evaluation result with spec/product/KB/ICP pins and typed gap refs. |
| `readiness_override` | C4 | Append-only human “just go” decision referencing the blocked decision it overrides. |
| `claim.product_id` additive product scope | C4 | Immutable, nullable product context; required on product-scoped `client.*` writes; same-workspace FK and scoped-read/idempotency updates. |
| `icp_spec` additive KB/product lineage | C4 | Add immutable nullable `client_entity_id`, `client_kb_version`, and `product_id`; C4 harness confirmations require them. |
| `project_run` additive pins | C4 | Add `client_entity_id`, `client_kb_version`, `product_id`, `product_context_version_id`, and `readiness_decision_id`; harness entry starts at `DISCOVERY`. |

### 4.1 Proposal ledger ruling

C2 reuses the existing `config_revision` lifecycle and service pattern, but does not force field
and source proposals into the current `config_revision` row shape. That table is specialized to
source-profile/scoring-rubric revisions and requires ICP lineage fields that do not model every
Stage-0 proposal cleanly.

`field_definition_revision` and `source_manifest_revision` therefore have specialized payload
tables, but share one proposal-decision service and the canonical `ProposalStatus` /
`ProposalAuthority` vocabulary. This is one mutation pattern with typed stores, not two
independent approval systems.

### 4.2 Current-state versus history

- attempts, proposal decisions, onboarding inputs, statements, readiness decisions, overrides,
  and product-context versions are append-only;
- ingestion/recon job rows may advance lifecycle status because they are resumable execution
  cursors;
- current projections select from durable history; rendered projection JSON is not a second truth
  store;
- corrections supersede claims or append corrected statements. They never overwrite evidence.

---

## 5. Exact tool contracts

Existing tools remain. New tools are version `1`, use `ToolContext.workspace_id` and
`ToolContext.actor`, declare loud precondition reason codes, and return only the listed references.
Lane worktrees define their input/tool classes in lane-specific API modules; central registration
in `build_toolbelt` is integration-owned.

### 5.1 C1

#### `research_account_gaps`

One bounded deterministic research round over an explicit gap set.

```text
input:
  project_run_id: str
  account_entity_id: str
  tier: str
  gap_fields: list[str]
  strategy_hint: str | null

references:
  project_run_id
  account_entity_id
  round
  coverage_decision_ids[]
  attempt_ids[]
  claim_refs[]
  remaining_gap_count
  terminal
```

`gap_fields` and `strategy_hint` are caller/agent planning inputs. The hint may select among
engine-permitted transitions, but it cannot select a trust tier, bypass a source plan, or set a
round above the deterministic cap. A goal evaluator may advise on sufficiency but may never supply
or override either input. Existing `run_deep_account` may call the same controller; it must not
reimplement the enforcement loop.

### 5.2 C2

#### `propose_field`

```text
references: field_proposal_id, field_key, status
```

#### `decide_field_proposal`

```text
references: field_proposal_id, status, applied_field_key | null
```

#### `propose_source`

```text
references: source_proposal_id, source_key, status
```

#### `decide_source_proposal`

```text
references: source_proposal_id, status, applied_source_key | null
```

The proposer supplies a capability description, not authoritative trust. Decision tools compute
required authority from field class/source tier and reject insufficient authority loudly.

### 5.3 C3

#### `submit_ingestion`

Accepts an already captured `artifact_key` plus declared context. The external upload transport is
an API concern; the tool owns durable ingestion after bytes exist.

```text
references: ingestion_job_id, artifact_key, status
```

#### `retry_ingestion`

```text
references: ingestion_job_id, status, retry_count
```

No tool returns extracted text, OCR bodies, or claim values.

### 5.4 C4

#### `submit_onboarding_input`

Persists one artifact-backed input with brand/product/project coordinates.

```text
references: onboarding_input_id, artifact_key, kind
```

#### `start_recon`

Starts or reuses the fast/background recon pair for one onboarding identity.

```text
references: recon_run_id, fast_run_id, background_run_id, client_entity_id | null
```

#### `record_interview_answer`

Classifies one verbatim user turn into mapped claim refs, memory refs, project-state refs, and/or
preserved statement refs.

```text
references:
  onboarding_input_id
  claim_refs[]
  memory_refs[]
  project_state_refs[]
  volunteered_statement_ids[]
  superseded_claim_refs[]
```

#### `confirm_project_product`

Human-only selection of a same-workspace product for the project. Recon/agent output may propose a
product, but may not silently update the project.

```text
references: project_id, brand_id, product_id
```

#### `evaluate_stage0_readiness`

```text
references: readiness_decision_id, gate, verdict, spec_version, gap_count
```

#### `override_stage0_readiness`

Human-only.

```text
references: readiness_override_id, readiness_decision_id, gate, verdict="overridden"
```

#### `start_confirmed_project_run`

> **Active-flow amendment (2026-08-16):** the input below is the immutable historical `@1`
> contract. The active successor is backend-derived and has no model-authored lineage, receipt,
> readiness, ICP, or budget identifiers. See
> [`FI-stage0-confirmed-discovery-run-contract.md`](./FI-stage0-confirmed-discovery-run-contract.md).

The harness-only post-confirmation entry; the legacy `start_project_run@1` keeps its full fixed
phase sequence for Recipe #1 compatibility.

```text
input:
  project_id
  client_entity_id
  client_kb_version
  icp_key
  icp_version
  product_id
  product_context_version_id
  readiness_decision_id
  budget_cap_cents | null

references:
  project_run_id
  entry_phase
  client_kb_version
  icp_key
  icp_version
  product_id
  product_context_version_id
  readiness_decision_id
```

Its preconditions validate same-workspace spine coordinates, the exact KB→ICP relationship, a
matching `DISCOVERY_SPEND` ready/overridden decision, and an immutable context manifest before
creating the run at `ProjectPhase.DISCOVERY`, the first post-confirmation execution phase.

Existing `reverse_profile`, `synthesize_icps`, `confirm_icp`, and legacy `start_project_run`
remain capabilities Recipe #0/Recipe #1 compose as appropriate.

---

## 6. Exact projection contracts

Projection module names are also route names. Reads are workspace-scoped, MVCC-only, and return
`None`/404 for absent and foreign records alike.

| Projection | Owner | Minimum response |
|---|---|---|
| `research_coverage` | C1 | Per-entity fields, latest/terminal status, round count, cost, attempt refs, claim refs, human-readable reason. |
| `research_attempt_history` | C1 | Ordered attempt metadata and stop reasons; no claim values. |
| `field_proposals` | C2 | Scoped proposal cards, payload summary, authority requirement, status, decision audit. |
| `source_proposals` | C2 | Scoped source cards, proposed capability, policy-assigned tier, status, decision/yield audit. |
| `ingestion_status` | C3 | Job lifecycle, media type, adapter, segment/claim counts, durable failure code, progress. |
| `recon_brief` | C4 | Cited brief blocks, product/client refs, current gaps, fast/background state. |
| `stage0_readiness` | C4 | All three gates, pinned inputs, deterministic floor result, agent sufficiency status slot, overrides, typed gap refs. |
| `stage0_progress` | C4 | Real recon/ingestion/interview events and their durable source refs; never synthetic checklist ticks. |

`research_coverage` must be distinguishable from the existing `run_readiness` projection and the
existing discovery coverage-confidence band. C4 composes C1–C3 projections by reference; it does
not query their tables directly.

---

## 7. Shared fixtures

All lanes use the same semantic ids/builders. UUID values may be generated by fixtures, but names
and relationships must not fork.

| Fixture key | Purpose |
|---|---|
| `c0_workspace_alpha` | Primary tenant with two brands. |
| `c0_workspace_foreign` | Cross-workspace fail-closed checks. |
| `c0_brand_alpha` / `c0_brand_beta` | Proves onboarding/client state is not a workspace singleton. |
| `c0_product_known` | Existing product with fresh and stale context refs. |
| `c0_product_new` | New product requiring full Stage 0. |
| `c0_project_surprise_me` | Discovery-oriented project. |
| `c0_project_known_accounts` | Import/deep-oriented project. |
| `c0_client_url_only` | Name + URL and no answers/uploads. |
| `c0_account_gap` | High-tier account with one filled field and one retryable gap. |
| `c0_contact_same_name` | Same-name contact trap for born identity-binding. |
| `c0_field_unmapped` | Valid new concept absent from the registry. |
| `c0_source_industry` | Credible unknown tier-3 industry website nomination. |
| `c0_upload_deck` | Client-about-self and client-about-target assertions in one document. |
| `c0_upload_corrupt` | Durable loud-failure fixture. |
| `c0_interview_correction` | Initial statement plus a later verbatim correction. |

### 7.1 Shared Step-4 journeys

1. **URL-only onboarding:** submit URL → fast recon brief → background progress → lower-confidence
   readiness with explicit gaps → ICP can still be confirmed.
2. **Known-product kickoff:** existing product context satisfies some floors → only stale/new gaps
   surface → pinned context is recorded.
3. **Open schema:** an unmapped interview/ICP concept creates a field proposal, remains visible,
   promotes through the authority gate, then becomes fillable without deployment.
4. **Open source:** a new industry site is investigated at tier 3, proposed, policy/human reviewed,
   and cannot self-award tier 1/2.
5. **Upload:** identical deck bytes dedupe; claims resolve to stable segment evidence; target
   assertions retain the tier-3 cap.
6. **Goal loop:** round 1 misses, round 2 uses a different strategy, then fills or records an
   honest terminal gap; replay is a no-op.
7. **Correction:** verbatim answer writes a claim; correction supersedes it; readiness and ICP
   recompute from current truth.
8. **Just go:** a blocked readiness decision can be overridden only by a durable human decision.
9. **Isolation:** every tool/projection returns the same not-found/refusal shape for a foreign
   workspace object as for an absent object.
10. **Run entry:** a confirmed ICP starts execution with matching Client-KB, ICP, product, and
    product-context pins and never implicitly reverse-profiles again.

---

## 8. C8 prerequisite disposition

### 8.1 Pre-spend gate — partially closed baseline, assigned closure

The current account, committee, contact, and tier-4 production paths already prove:

```text
external claim-producing spend
    → SourceGate / PreSpendGate.check
    → durable gate_decision
    → resolver/provider call
```

C1 and C2 may not create a second gate or call an external resolver directly. Every new paid
strategy and the generic tier-3 resolver must enter through the existing `SourceGate` /
`PreSpendGate` composition. Paid C3 OCR/extraction must use the same gate/budget authority rather
than treating “client upload” as free execution.

The live audit found two pre-existing Stage-0 callers without a gate:

- `stage0/client_kb.py::reverse_profile`;
- `stage0/import_accounts.py::_crm_enrich`.

C4 owns threading the injected API-root gate into both paths before Recipe #0 or the known-account
kickoff can spend. This is not optional cleanup: C4's exit gate includes it.

The Step-4 integration tests extend the existing
`tests/api/test_governance_integration.py` and `tests/api/deep/test_gate_routing_ac6.py` matrix.

The invariant is temporal, not merely eventual: the test probe must observe a matching
`gate_decision` before the fake provider records its call.

Add an integration/static inventory guard covering every production `resolve_field` caller and
every paid extractor. A new claim-producing spend path without either an injected gate or an
explicit proven-zero-spend exemption fails the build.

### 8.2 Identity binding — closed baseline, mandatory extension

The current contact-facet path already stamps the authoritative classifier result before immutable
claim insert. New C1 retry strategies, C2 generic web resolution, and C3 extraction must:

1. route contact claims through a `ClaimTagger`;
2. call the API-root production binding classifier before insert;
3. retain the tier-4 weak-binding drop rule;
4. retain appropriateness/use-class tagging;
5. fail closed when required binding context is unavailable.

No lane may “fix up” `claim.identity_binding` after insert.

### 8.3 Remaining C8 work

The other C8 items are not Step-4 blockers unless their consumer arrives. They keep the parent
schedule:

- merge equality, retention-aware merge, DSAR rationale cleanup, committee reader, and product-fit
  work must close before C7;
- presign scope policy must close before an evidence-serving consumer;
- hard lease fence tokens must close before multi-worker production deployment.

---

## 9. Worktree ownership treaty

### 9.1 Lane-owned surfaces

| Lane | Owns | Exact cross-lane exclusions |
|---|---|---|
| C1 | new `clue_research.coverage` package; coverage migrations; coverage/goal-judge tests; lane-specific coverage tools/projections | no proposal, ingestion, Stage-0, readiness, or product-context types |
| C2 | new `clue_research.proposals` package; proposal migrations; generic web resolver package; the out-of-registry handoff in `stage0/icp_synthesis.py`; lane-specific proposal tools/projections | no coverage controller, ingestion job, onboarding/interview/readiness state |
| C3 | new `clue_research.ingestion` package; new file adapters in new adapter modules; ingestion migrations/tests; lane-specific ingestion tools/projection | no proposal promotion, recon orchestration, interview/readiness state |
| C4 | new Stage-0 recon/interview/readiness modules; onboarding/product-context/run-pin migrations; Stage-0/import pre-spend closure; Recipe-#0 seam; lane-specific Stage-0 tools/projections | no direct reads/writes of C1–C3 tables; no alternate coverage/proposal/ingestion stores |

### 9.2 Integration-owned shared files

No lane should independently finalize these shared surfaces:

- `platform/api/clue_api/toolbelt_wiring.py` and central tool registration;
- `platform/projections/clue_projections/__init__.py` and projection HTTP router aggregation;
- `platform/api` construction that imports more than one Step-4 lane;
- root package lists/import-linter contracts;
- Alembic merge revisions;
- shared Step-4 end-to-end tests;
- `docs/specs/README.md` phase status.

Each lane may add a distinct API/projection module. Integration performs the one-line imports and
registrations after the lane lands.

### 9.3 Contract-delta rule

If implementation proves a frozen shared type insufficient:

1. stop before creating a lane-local substitute;
2. write a small C0 contract-delta naming every consumer and migration effect;
3. review/land it on the integration branch;
4. rebase all affected worktrees;
5. then continue.

---

## 10. Parallelization decision

After this C0 commit, **C1, C2, C3, and the C4-owned substrate may be developed concurrently** from
the same head.

The safe boundary is:

- C1–C3 implement and test their stores/engines/lane modules independently;
- C4 implements against the frozen ref/projection protocols and fakes;
- cross-package construction stays out of all four worktrees;
- integration lands C1 → C2 → C3 → C4.

C4 is parallelizable as code, but it is not independently releasable. Its final Recipe-#0,
readiness, progress, and run-entry acceptance gates depend on integrated C1–C3 behavior.

Later Phase C:

- C5 starts only after Step 4 integrates because it formalizes the Recipe-#0 seam and journals the
  complete tool surface;
- C6 starts only after C5's journal/recipe/executor contracts are real;
- C7's derivation/entailment/projection substrate may be developed alongside late C6 **after** C1
  and its C8 prerequisites are integrated, but C7 tool/run integration and the Phase-C exit gate
  remain after C6;
- C8 is scheduled with each consumer, not opened as an unbounded miscellaneous worktree.

---

## 11. C0 exit checklist

- [x] PC-C1 through PC-C4 child specs exist.
- [x] Shared types and lane-local types are separated.
- [x] Every new table has exactly one owner.
- [x] Tool/projection names and reference-only results are frozen.
- [x] Shared fixtures and journeys are frozen.
- [x] Existing governance coverage and remaining Stage-0 gaps are audited, owned, and test-bound.
- [x] Parallel worktree and integration ownership is explicit.
- [x] The parent/index/memory are synchronized.
