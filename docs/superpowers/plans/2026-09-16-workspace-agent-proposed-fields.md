# Workspace-local agent-proposed research fields — implementation plan

**Date:** 2026-09-16. **Status:** planning and documentation only; implementation not started.
**Baseline:** Irvine, `settings-page`, `c5092f276`. Recheck the head and Alembic head before coding.
**Requested outcome:** an agent's new research vocabulary belongs to the workspace that produced
it, and the Head of ABM and account/person agents are taught the same scope and lifecycle rules.
The founder requested this plan and the corresponding documentation update; recommendations
below are proposed implementation decisions, not a claim of product sign-off or deployed behavior.

Companions:

- [Settings design §9.4](../specs/archive/2026-09-15-settings-integration-design.md): existing
  workspace registry and the original Track R follow-up.
- [Settings completion plan](2026-09-16-settings-integration-completion.md): delivered Settings
  work and outstanding acceptance; this plan is a separately tracked extension.
- [Research-field agent documentation](../../agents/research-field-scope.md): current behavior,
  replacement operating instructions and the exact resource release checklist.
- [Agent resource authoring](../../agents/skill-and-profile-authoring.md): immutable versions,
  digests, profile pins and materialization rules.
- [ARV2 master plan](../../specs/ARV2-MASTER-PLAN.md), [Doc A](../../architecture/clue-hq-platform-agent-runtime.md)
  and [shared conventions](../../specs/_conventions.md): lenient observations, runtime authority
  and shared-substrate ownership remain binding.

## 1. Product behavior and completion boundary

An account or person research job in workspace A discovers a supported observation with no
existing field. It saves the observation and registers its field in A's registry. A's managers
can see its origin and edit its label/instruction or retire it through Research fields. B cannot
see that definition, its explanatory text, its results or its evidence. B may independently
create the same key with its own meaning. Platform-maintained fields remain shared and read-only.

Example: A's account agent proposes `account.procurement_cycle`. The definition and claim belong
to A. A's next account research job can use the field; B's next job does not receive it. Editing
the instruction affects subsequently composed jobs, not an already-running context. Retirement
blocks subsequent writes without erasing historical, authorized evidence.

Completion requires all three: **future registrations isolated**, **historical shared vocabulary
reviewed and contained**, and **agent instructions/materialized resources consistent with the
new behavior**. A write-path patch alone does not complete this issue. Historical findings with
unresolved ownership must be listed explicitly and contained; they must not be silently called
platform definitions or treated as safely migrated.

Out of scope: a new research engine, a second registry, a human approval inbox, automatic global
promotion, semantic field merging, new contact results UI, Pages, Billing, avatar/website work,
or changing claim-verification/outreach policy. No extra research or model call is required merely
to name/register a field. No environment flag is proposed; a compatibility mode that quietly
falls back to global registration would undermine the fix.

## 2. Code findings that constrain the solution

| Seam / file | Current behavior | Consequence |
| --- | --- | --- |
| `platform/api/clue_api/arv2/claim_writer.py` | `UnknownFieldError` leads to `_register_proposed_field` → global `register_field`; claims are separately stamped `tenant_private` | Scope the definition, not just its claim. Preserve strict mode and never catch retirement/erasure as unknown. |
| `platform/api/clue_api/arv2/account_research_claims.py` | Structuring proposals and direct agent claims normalize keys; proposed `why` becomes `field_description` | Normalization accepts more than account/contact prefixes; raw, subject-specific rationale must not become shared or automatically trusted instructions. |
| `platform/api/clue_api/arv2/account_research_tools.py` | `write_drafts_individually` applies contact compliance and returns per-draft failure receipts | Registration and claim insertion must be atomic for each draft; a bad draft must not discard successful siblings. |
| `subsystems/research/clue_research/claimstore/registry.py` | Global/effective readers, workspace registration, key locks, retirement and erasure already exist | Put reusable registry policy here; do not build a second API-owned registry. |
| `alembic/versions/3a75cb367c2b_workspace_research_fields_settings.py` | Research rows require `settings-v1`, `human:%`, JSON shape, account/contact class, label and description | An agent row cannot be inserted by simply calling the human helper or changing its actor string. Facet class needs explicit handling. |
| `register_workspace_research_field` | Human-only, generates key from label, rejects existing/retired keys | Add a distinct idempotent agent entry point while sharing locks/validation. Human creation stays strict. |
| `read_account_catalog` / `read_person_catalog` in `account_research_store.py` | Read scoped effective menus; person menu preserves `contact.facet.*` and `core.work_email` | Extend the existing readers; test account, child-person and direct-person composition. |
| `frontend_read/research_fields.py::field_rows` | Creator names assume `human:` IDs; API exposes platform/workspace origin | Do not pretend an agent-created field has a human creator. Small contract/presentation amendment required. |
| `apps/frontend/src/features/settings/components/research-fields-settings.tsx` | A missing creator name renders “Workspace member” | Adding only an agent backend row would misattribute creation; update this fallback with the typed creation source. |
| `frontend_read/v1_shared.py`, `contacts.py`, `account_detail.py` | Scoped custom values and claim-based evidence exist | Keep these readers consistent with new origins and legacy reconciliation. |
| `platform/agents/clue_agents/manual/fields_snapshot.py` | SELECTs every global definition into committed `catalog/manual/fields.json` | Global runtime proposals can enter a shared agent manual; claims remaining private does not protect definition text. |
| `manual/build.py::build_fields_chapter` | Describes the snapshot as the vocabulary of every stored fact | The snapshot cannot enumerate dynamic workspace vocabulary. Correct the description and read procedure. |
| `agent_registry_wiring.py`, `manual/build.py` | Current Head of ABM profile `v57`; manual `v4` | Publish new immutable manual/profile versions; do not edit v4 or assume the older authoring-guide table is current. |
| `arv2/account_research_catalog.py` | Both account/person bundles are `v1`, five files each, digest-pinned | Revise both bundles and their pin/launch compatibility tests together with the backend. |

Other callers include discovery and the answer-key loader, both using `LenientClaimWriter`.
Inventory all callers and deterministic seed loaders before changing its signature. A known
platform seed must remain platform vocabulary; an incidental runtime write must not become a
platform-definition author merely because its extraction method is `api` rather than synthesis.

## 3. Decisions to review before implementation

The central decision—workspace ownership instead of automatic global registration—is the requested
direction. The following defaults make the rest concrete. Record accepted choices before coding
the affected behavior, especially changes to what managers see in Settings.

| ID | Recommendation | Alternative and tradeoff | Gate |
| --- | --- | --- | --- |
| P1 | Auto-register usable local fields and admit them to that workspace's subsequent research menus; label their agent origin | A pending approval state keeps menus curated but adds a queue, lifecycle and new UI. Do not introduce it silently. | Product behavior |
| P2 | Managers can edit/retire these fields using existing controls; members remain read-only; show “Research agent” for creation | Hide fields or make them read-only, leaving managers unable to govern growing vocabulary | Settings contract |
| P3 | A proposal supplies evidence for an observation, not authority to change instructions. Store its rationale in scoped provenance; derive a bounded neutral default instruction from the field label without a new LLM call | Reuse raw `why`, risking subject-specific conclusions or injected instructions in future menus | Agent/field contract |
| P4 | Reuse existing active definitions; do not overwrite human edits or an earlier definition on subsequent observations | Last writer wins would silently change meaning during concurrent research | Engineering default |
| P5 | Unknown account/contact observations get subject-bound local keys; preserve facet classification; never remap a retired/erased/known forbidden key to evade its policy | Accept arbitrary new `core.*`/pack fields locally, broadening registry and privacy contracts | Namespace contract |
| P6 | Audit and contain historical automatic globals, then migrate only definitions with proven workspace ownership and safe reference handling | Future-writes-only leaves old metadata in other workspaces and shared manuals; insufficient for full completion | Data rollout |
| P7 | Keep current lenient evidence/schema annotations; enforce tenancy, lifecycle and subject checks even in lenient mode | “Never refuse any key” would undo retirement, erasure and namespace safety | Existing authority boundary |

No agent can promote a field to the platform registry, edit another field's definition, relax
permissions, or bypass a retired name. A manager choosing to edit a definition does not make the
existing claims verified. The scope change must not imply either approval or evidential quality.

## 4. Target data and authority contract

### 4.1 One registry, explicit creation provenance

Reuse `workspace_field_definition`, `workspace_field_retirement` and the current erasure seam.
Extend the research-row contract to distinguish human creation from agent registration. Prefer
the existing immutable policy/actor metadata for the creation category, plus structured,
workspace-scoped run/job attribution where current metadata is insufficient. Settle concrete
columns after inspecting real run identifiers/FKs; do not store unverifiable free-form user names
as agent provenance or fabricate a Client-KB `field_definition_revision` approval.

The migration must encode conditional constraints for human versus agent research rows:

- Human: existing `settings-v1` authority and behavior remain unchanged.
- Agent: a new explicit policy version, trusted research attribution, private reuse, account or
  contact ownership, immutable key/type/scope, bounded label/description and generic JSON values.
- Contact facets: preserve `FieldClass.CONTACT_FACET` and the existing contact-use/compliance
  treatment. The current research CHECK permits only account/contact classes, so widen it
  deliberately rather than relabel facets as ordinary contacts to pass it.
- Existing `client.*` extended-field promotion is unaffected, including its proposal FK.

Do not add a separate model-generated approval status just because the legacy marker says
`proposed_field`. Under P1 the row is an active local definition with agent provenance. Policy,
verification status and evidence quality retain their separate meanings.

### 4.2 Registration seam

Add a substrate-owned operation, provisionally `ensure_workspace_proposed_research_field`,
separate from human `register_workspace_research_field`. Inputs: trusted workspace/actor/run
context, subject kind, normalized key and bounded definition metadata. Output: the resolved
definition and `created`/`reused` disposition. Names are proposed; use existing public type
conventions rather than create parallel DTOs.

The API composition root establishes job → run → workspace → subject ownership from durable
records. The model may suggest a field label/key and value; it cannot supply registration
authority, another workspace, an actor ID or policy version. Keep API-specific job-store imports
out of the shared research substrate. Authorized import/replay code needs its own explicit
attribution path; do not silently grant every `ClaimDraft` a fabricated live job.

Registration and `insert_claim` share the caller's transaction. Follow a single lock order across
human creation, agent creation, global seed registration, retirement and erasure: workspace
guard, key advisory lock where needed, then definition row lock. Recheck existence after locks.
Test the real order against existing helpers before publishing it as final.

For an existing active local or platform key, use the current definition and validation. First
committed registration wins its descriptive metadata. A subsequent observation reuses it without
resetting a manager's label, instruction or definition version. Retirement/erasure produces a
lifecycle refusal; it never results in a renamed replacement or global fallback.

### 4.3 Keys and metadata

Reuse and extend `normalise_proposed_key`; do not write a second normalizer in the registry/API.
Normalization is about spellings, not silently deciding two observations mean the same thing.

1. Resolve exact known keys and lifecycle state first. A known wrong-subject or protected key
   receives a typed refusal; it is not made acceptable by changing its prefix.
2. For genuinely unknown keys, use the trusted subject (`account` or `contact`), never a
   model-supplied workspace or subject. Preserve a contact facet's more specific classification.
3. Unnamespaced labels use that subject's namespace. An unknown reserved/foreign prefix needs a
   deterministic subject-local proposed key retaining enough of the original prefix plus a
   stable digest to avoid collision. Specify concrete examples/tests before enabling this case.
4. Preserve raw spelling and mapping policy in scoped provenance/write markers; no claim value
   or evidence quote belongs in a key, label, global log or shared manual. Bound and escape text.
5. For same-key/different-meaning proposals, reuse the definition without overwriting it and
   expose the mismatch for review; do not silently merge schemas or invent synonym resolution.
6. Never convert unknown `client.*` content into a research field to bypass Client-KB approval,
   and never infer a less restrictive privacy/use class merely from a new key name.

P3's initial instruction can be deterministic, for example: “Find source-backed information about
Procurement cycle for this account. Leave unknown information blank.” Keep raw `why` on the
originating claim/provenance, not in the instruction. Manager-authored instructions retain their
existing authority. Treat all field text as bounded task data, subordinate to system/tool policy.

## 5. Execution phases and checkpoints

### Phase A — inventory and contract freeze

- [ ] Recheck branch/head, tracked diff, applicable instructions and the single Alembic head.
- [ ] Record P1–P7, the scoped creator presentation and exact key examples in the Settings/API
  contracts before implementing their user-visible changes.
- [ ] Inventory all `LenientClaimWriter`, `register_field`, effective/global catalog and snapshot
  callers, including discovery, direct-person launch, import/replay and global seed loading.
- [ ] Inspect existing C2 proposal ledgers and Client-KB promotion seams before introducing any
  provenance storage. Reuse appropriate references without requiring an unrelated human
  approval lifecycle or adding a duplicate registry/proposal pipeline.
- [ ] Build a read-only inventory command for each intended database: platform-seeded definitions,
  suspected runtime proposals, workspace claim/run associations, existing local collisions,
  public/unscoped uses, retired/erased scopes and every incoming FK/reference.
- [ ] Compare committed `fields.json` with reviewed seed/migration vocabulary. Existing text such
  as “claimed on the unregistered key” is a candidate signal, never sufficient ownership proof.
- [ ] Report counts/keys/classification reasons without copying customer values, descriptions or
  evidence into shared docs. Keep any detailed audit export scoped to authorized storage.

**Exit:** caller/reference map, accepted contract and a reviewed historical classification policy.
No migrations or paid calls are needed for this phase. Code inspection alone cannot establish the
contents of the live database.

### Phase B — schema and shared registration

- [ ] Generate a random-hash Alembic revision from the then-current head. Add the narrowly scoped
  agent-origin constraints/provenance chosen in §4. Preserve the existing human and Client-KB
  paths. Define how creator erasure removes display identity without breaking provenance.
- [ ] Implement the shared idempotent registration helper and exports. Force scope/type/policy in
  trusted code; reject missing/mismatched runtime authority.
- [ ] Preserve global/local collision protection, same-key independence across workspaces,
  definition versioning and append-only retirement. Keep non-colliding seeds registerable.
- [ ] Add substrate tests with actual transactions for registration, races, rollback and direct
  SQL constraint bypass attempts. Include contact facets and erasure/retirement races.
- [ ] Run upgrade → downgrade → upgrade on a disposable Irvine database. On populated databases,
  downgrade must refuse when it cannot preserve agent-created data; never delete rows to pass.

**Exit:** service + database enforce the same scope contract; one Alembic head; reviewed migration.
**Checkpoint commit:** workspace agent registration substrate and tests.

### Phase C — writer and research runtime

- [ ] Replace the global registration branch in the lenient writer with the trusted local seam.
  Only `UnknownFieldError` is eligible. Preserve strict-mode behavior and refusal receipts.
- [ ] Carry trusted creation attribution from live jobs and explicitly authorized imports; do
  not allow model fields to override it. Test mismatch with an otherwise valid foreign run ID.
- [ ] Re-run the complete write gate after a registration race resolves to an existing field,
  including schema, reuse and product/subject policy. Preserve lenient schema annotations on
  that second validation too; winning a registration race does not weaken the existing field.
- [ ] Apply the reviewed normalization to structuring proposals and direct agent writes, with
  final stored key reflected in receipts and corrections/evidence lookups. No per-tool forks.
- [ ] Preserve tier stamping, private reuse, schema/source annotations and contact compliance.
  Correct `registered_field` to mean actual creation, including under a concurrent retry.
- [ ] Preserve source/proposal markers after the field is registered: a later observation can be
  agent-produced even though it did not create the definition. Do not overwrite trusted markers
  with arbitrary caller-supplied metadata.
- [ ] Reuse scoped account/person catalogs on every composition path. A newly created field joins
  subsequent jobs under P1; already-composed contexts remain stable and late writes still pass
  current lifecycle checks. Do not refresh an in-flight prompt behind the agent's back.
- [ ] Check discovery and answer-key loading; globally maintained seed keys must be seeded
  intentionally, not accidentally converted to private fields by a missing startup seed.

**Exit:** a deterministic account and person run creates only local definitions, preserves claims
and sibling failures, and exposes those definitions only to the correct next-job context.
**Checkpoint commit:** scoped writer/runtime integration and tests.

### Phase D — Settings, values and evidence

- [ ] Amend the frontend Settings contract for explicit creation source. Prefer an additive
  `creation_source` discriminator over overloading the human `created_by` name; exact values
  and compatibility defaults must be agreed with the UI. Keep `origin=workspace|platform` for
  registry ownership, a different concept from human/agent creation.
- [ ] Render “Research agent” for agent-created fields; keep creator-erased human rows distinct.
  Reuse existing rows, inline edits and retirement controls; do not design a new management page.
- [ ] Owner/admin can manage local agent fields. Member/viewer cannot. Platform fields stay
  read-only. An agent cannot invoke a human edit/retire path through an invented principal.
- [ ] Verify account custom columns, contact payloads and evidence resolve the same definition
  and workspace. No new contact UI is included. Empty definitions do not create empty columns.
- [ ] Verify retiring a field removes it from active catalogs/columns, refuses new writes and
  preserves historical evidence for an authorized subject/workspace until erasure applies.

**Exit:** origin is honest, manager governance works and scope/lifecycle survive all readers.
**Checkpoint commit:** creator presentation, contract and focused frontend/backend coverage.

### Phase E — historical global proposals and shared snapshots

This phase is required; do not hide it behind a generic “backfill later” entry.

- [ ] Classify each global definition as reviewed platform vocabulary, proven runtime-created,
  or unresolved. Cross-check seed sources, migrations, claim `proposed_field`/origin markers,
  run ownership and historical usage. A seed later reusing an agent-created key is a collision
  requiring review, not an automatic deletion candidate.
- [ ] For proven runtime definitions, derive recipient workspaces from durable provenance and
  claims. Do not copy one workspace's rationale into every workspace that later used the key.
  Preserve each workspace's own text when attributable; otherwise use neutral metadata and
  record the uncertainty. Skip erased workspaces; do not resurrect retired vocabulary.
- [ ] Inventory foreign keys beyond claims: for example `prespend_effective_source_plan` retains
  global-field references and C7 view rules can have cascading references. Claim history alone
  is insufficient to prove that deleting a global row is safe.
- [ ] Choose and document the reviewed reconciliation operation per class. For rows with safe,
  known references, archive original metadata and move definitions transactionally into scoped
  registry rows without changing claim IDs, values, evidence or provenance. Existing global/local
  collision checks require an ordered migration, not an INSERT followed by hopeful cleanup.
- [ ] Where historical references prohibit removal, retain the original row as **historical-only**
  metadata with explicit classification and audited workspace eligibility. Exclude it from shared
  menus, new global registration and manual export. Implement this through the existing registry
  seam and database guards; merely setting `active=false` does not establish isolation because
  some reads include inactive/global definitions. If a compatibility resolver is needed, it must
  require workspace authority and must not admit new claims through the legacy global path.
- [ ] Unresolved ownership is quarantined from shared runtime menus/manuals pending review;
  historical reads require attributable workspace authority. Preserve data and report any
  unavailable historical path explicitly rather than guessing ownership or silently losing it.
- [ ] Make the operation dry-run-first, resumable and idempotent with before/after counts,
  per-definition dispositions and an audit identity. Separate schema migration from an
  environment-specific data decision; never bake a machine's discovered customer rows into Git.
- [ ] Rebuild shared field snapshots only from a clean, fully migrated and seeded disposable
  database or another explicitly reviewed platform-only source. Audit seeding/history too:
  “present in the global table” is not adequate platform provenance. Never export local fields.
- [ ] Review the existing committed snapshot and generate a clean new manual version. Preserve
  historical resource integrity; if a review identifies sensitive bytes in old published resources,
  invoke the existing privacy/erasure response instead of casually rewriting all Git history.

**Exit:** current runtime menus and new shared manuals contain only reviewed platform vocabulary
plus the caller's local overlay; legacy cases have tested scoped resolution or explicit quarantine.
**Checkpoint commit:** audited reconciliation tooling, snapshot rules and tests (no customer export).

### Phase F — documentation the agents actually consume

Use the [companion operating instructions](../../agents/research-field-scope.md), not just a human
changelog. This is part of implementation acceptance, not an optional documentation follow-up.

- [ ] Update the manual generator's field introduction and source classification; a static shared
  snapshot describes platform vocabulary, not an exhaustive list for every workspace.
- [ ] Copy the full manual chapter set to the next available immutable version (currently v5
  would follow v4). Update fields, claims, accounts-research, humans-screens and glossary; render
  generated chapters from their sources. Update all cross-links and avoid editing v4 in place.
- [ ] Create the next Head-of-ABM profile (currently v58 would follow v57), pin exact new chapter
  hashes, preserve tool grants/models/budgets and remeasure the manifest digest. Search all active
  profile IDs, recipe bindings and mount references; do not update only one version constant.
- [ ] Copy both ARV2 account/person five-file bundles to new versions (currently v2). Teach local
  proposals, subject binding and lifecycle refusals in prompt/manual/audit guidance. Keep the
  existing research charter; replace blanket “unknown key never refused” statements with the
  precise unknown-versus-retired/erased distinction.
- [ ] Update `account_research_catalog.py` selectors, profile/manifest pin tests and launch/replay
  behavior. Finish/drain existing jobs or use the existing explicit relaunch contract; do not
  resume an old authorization with silently different resource bytes.
- [ ] Amend structuring prompt text where appropriate; generation must use the supplied scoped
  menu and put genuinely unmatched observations in proposals. No new ability to mutate registry
  definitions is granted to the Head of ABM or researcher.
- [ ] Verify the actual capability map and materialized `.deepagent` files on a fresh turn.
  Historical resources remain evidence only; no runtime workspace is edited manually.
- [ ] Update the ARV2 README/master-plan amendment, Settings contracts, authoring guide and plan
  status together. The active instructions must describe implemented behavior, not future intent.

**Exit:** exact released bytes, profile pins, active selectors and fresh runtime materialization
agree. Replayed historical executions retain their old resource identity.
**Checkpoint commit:** versioned manuals/research bundles and activation checks, shipped with code.

### Phase G — controlled live acceptance and release

- [ ] Name the exact isolated target, database, ports, code/migration/profile revisions and worker
  ownership. Prior Irvine port numbers are historical evidence, not permission to touch siblings.
- [ ] Back up the intended DB; stop/drain only affected workers for the old-global-writer cutover.
  Migrate schema, deploy scoped writer/readers, reconcile approved legacy cases and activate new
  catalogs as one coordinated release. Verify no old worker can keep registering globally.
- [ ] Use two controlled workspaces and authorized identities. A bounded account job in A and a
  person job must create a genuinely new field with real evidence. Record run/job/field/claim
  refs, receipt and definition attribution. No manually inserted claim proves agent behavior.
- [ ] A's Settings displays the field and “Research agent”; B's Settings, research catalogs,
  claims/evidence routes and fresh agent context do not. B can independently create the same key.
- [ ] A's next job uses its local definition. Edit its instruction, compose another job and prove
  the new text is consumed. Follow the existing spend/launch authorization rules.
- [ ] Retire the controlled test field with the required at-action authorization; verify write
  refusal, no renamed/global resurrection and preserved historical evidence. Test erasure on a
  disposable fixture workspace, not customer data.
- [ ] Inspect the shared materialized manual and both entity bundles: no A/B definitions or raw
  rationales appear in shared resources. Live returned field families are authoritative for reads.
- [ ] Record implementation, automated checks, data-reconciliation disposition, live evidence and
  actual deployment separately. Provider unavailability is a named live-test blocker, not a pass.

**Exit:** future writes, existing data exposure, governance and actual agent knowledge all pass.
**Checkpoint commit:** non-sensitive acceptance record and any bounded fixes; no automatic push.

## 6. Required test matrix

| Case | Assertion |
| --- | --- |
| Unknown account/person key, lenient mode | One workspace row plus claim; zero new global rows; correct subject and private reuse |
| Unknown key, strict mode | Refusal and no definition/claim side effects |
| Same key, workspaces A/B | Independent definitions/instructions; neither can read the other's metadata, claims or evidence |
| Known platform key | Uses platform contract; no local shadow and no automatic schema/description edit |
| Existing human local key | Agent reuses it without changing manager text/version or impersonating its creator |
| Concurrent proposals in one workspace | Exactly one definition; both legitimate claims survive; truthful creation receipts |
| Agent versus human/global registration race | Deterministic collision policy; no shadowing or cross-tenant error disclosure |
| Registration then claim failure | Transaction leaves no orphan definition; successful sibling drafts remain |
| Retirement/erasure racing with writes | Committed lifecycle refusal wins; no global fallback, alternate spelling or alias resurrection |
| Malformed/reserved/cross-subject key | Stable reviewed normalization or typed refusal; raw spelling stays scoped |
| Facet proposal | Facet classification, binding/use defaults and compliance/display gates retained |
| Mismatched workspace/run/subject | Rejected before registration; model-provided attribution cannot authorize it |
| Raw rationale contains instructions or customer facts | Not promoted into shared docs or future trusted research instructions |
| Direct person, committee person, discovery, import | Each uses its explicit trusted scope; deterministic seeds remain platform-owned |
| Historical seed/proposal collision | Reviewed disposition; no platform deletion or field shadowing by inference |
| Legacy FK / cascade / public claim | No destructive cleanup; safe scoped compatibility or recorded quarantine |
| Replay and repeated migration | No duplicate definitions, no rewritten evidence; rerun inventory converges |
| New instruction and cached context | Later job sees update, in-flight context stays stable, cache keys include workspace/version |
| Settings permissions/origin | Honest creator labels; owner/admin only edits; plain read-only member view |
| Snapshot/materialized manual | Only reviewed platform definitions; dynamic scoped fields absent; exact hashes and links resolve |

Extend existing suites: `tests/claimstore/test_workspace_research_fields.py`,
`tests/arv2/test_claim_writer.py`, `test_account_research_claims.py`, `test_structuring_client.py`,
`test_account_research_catalog.py`, relevant account/person driver/launch tests,
`tests/auth/test_research_fields_settings.py`, scoped custom-value/evidence and privacy suites,
`tests/agents/test_manual_builder.py`, `test_manual_drift.py`, and
`tests/api/test_agent_registry_wiring.py`. Add focused historical-reconciliation tests rather than
testing migrations only on empty databases.

Verification gates: focused DB/API/runtime tests → import contracts and touched-code lint/type
checks → `make manual-check` and resource pin checks → frontend design-system/lint/build and
relevant tests if its contract changes → `make check` → isolated `make db-smoke`. Attribute
pre-existing failures with evidence rather than suppressing them. Never run migration smoke on
the live or shared DB. Run no paid research as part of ordinary unit tests.

## 7. Release ordering, rollback and operational evidence

The schema can be deployed compatibly before the new writer; activation cannot leave a mixed
fleet indefinitely. Inventory current jobs, drain/stop old writers, perform reviewed data
reconciliation and deploy new writer/readers/resources before resuming affected work. If an old
writer remains possible, enforce a database-level registration restriction until cutover; do not
pretend a prompt alone prevents global insertion. Verify shared-key locks against that guard.

Rollback means preserving data and isolation: pause affected jobs and use a compatible forward fix
or release. Do not roll back to the old writer while letting it create new global proposals. A
schema downgrade on populated agent fields must refuse safely unless the explicit preservation
procedure has run. Keep audit archives private and reversible; never delete claims, overwrite
immutable resource bytes or re-export tenant vocabulary merely to make an old version work.

Record counts of created/reused/refused proposals and refusal categories through existing
observability. Reuse run/job/claim references; do not log raw descriptions, values, customer keys
as unbounded metric labels, or full prompts. A new env setting is unnecessary; if one becomes
necessary during implementation, `.env.example` parity applies immediately.

## 8. Current checklist and handoff

- [x] Trace the current registration, registry, Settings/read and agent-documentation seams.
- [x] Identify human-only DB constraints, facet/namespace cases, historical global references and
  the shared snapshot exposure.
- [x] Prepare the phased implementation plan, proposed decisions and replacement agent guidance.
- [ ] Review product/contract decisions P1–P7.
- [ ] Implement phases A–F and pass their automated gates.
- [ ] Complete historical classification/reconciliation on the intended target.
- [ ] Complete phase G live proof and record the actual deployed revision.

No backend code, migrations, active resource pins, runtime services or customer data changed as
part of this planning task. The documentation update prepares the instructions that must ship
with the implementation; it does not falsely teach the running agent that isolation already
exists. “Plan written,” “code implemented,” “data reconciled” and “live accepted” are distinct.
