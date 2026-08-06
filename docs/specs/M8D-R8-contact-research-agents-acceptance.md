# M8D R8 — Contact research agents on the shared fleet acceptance

**Status:** accepted 2026-08-06
**Roadmap authority:** `M8D-entity-research-agents-and-shared-fleet-refactor-roadmap.md`, R8

## 1. Accepted boundary

R8 executes a separately approved R7 contact selection on the same subject-neutral R2 fleet used
for account research. Each selected contact receives one role-configured
`langchain.agents.create_agent()` unit through the R3 runtime and the governed R4 research-result
services. It does not automatically follow account research and it does not widen a launch from
the exact selected contacts to the rest of an account or buying committee.

The contact agent owns runtime research decisions within its frozen target-local authority. Its
semantic tools are:

- read the locked contact identity, existing claims, requested fields, questions, facets,
  channels, budgets, and prior research state;
- perform bundled Exa contact research and independent structured enrichment;
- inspect complete research-result and evidence projections;
- reveal and independently validate an authorized email or phone channel;
- assess coverage and create governed review state;
- delegate no more than two optional depth-one facets; and
- propose typed finalization for engine validation.

No account-research tool, committee-enumeration tool, arbitrary contact lookup, or recursive facet
tool is present in the contact agent's allowlist.

## 2. Exact target and identity authority

`ContactResearchStateStore` derives the execution scope from the exact R7 job authority. Before
each agent step it verifies the active selection, exact contact/account/workspace/project/product
scope, allowed fields and sources, directional questions, facets, channels, policy pins, and
budgets.

The durable identity lock is calculated from stable identity anchors. LinkedIn is preferred;
verified email is an anchor only when no LinkedIn identity exists. A later authorized email reveal
therefore cannot mutate the subject identity and invalidate its own running job. The state view
still reads current verified channels and fresh, grounded current claims on every turn. Stale,
conflicted, or evidence-less claims remain explicit coverage gaps.

The execution guard refuses requests for an unselected contact, a different account, an
unselected field/source/question/facet/channel, an account tool, or a dependent decision made
before its prerequisite result is visible.

## 3. Facet execution

Optional facets are ordinary depth-one contact `create_agent()` children on the same checkpointed
runtime. A parent may delegate only a selected facet, to no more than two children, and cannot
delegate recursively. The facet factory receives a deliberately smaller surface: governed deep
research plus lossless result/evidence reads and typed finalization.

A facet can finish only with the exact field partition assigned to it. Its accepted result,
claims, evidence, and finalization must all be caused by the exact child agent turn. Started,
waiting, resumed, completed, and replayed facet events are durable and idempotent.

## 4. Channel operations, waits, and spend

Email and phone operations remain explicit and independently governed. Reveal/acquisition and
validation are separate semantic decisions and separate provider dispatches. A successful reveal
enters `ready_to_validate`; it does not silently run a validator. Either operation may return an
external-wait receipt, release its worker lease, and resume the same checkpoint after a durable
wake.

Channel causation is recorded before dispatch. Resuming an existing caused provider operation
joins that operation rather than creating a second request or charge. Provider settlement is
folded exactly once into both the contact job and contact run. R7 research-only budget semantics
remain stable for selection hashing, while R8 execution admission uses an explicit all-in cap:
research plus the selected reveal and validator caps.

## 5. Finalization, review, and user return

The engine, not the model, accepts finalization. It validates exact contact scope, identity lock,
field/source authority, result/claim/evidence lineage, independent channel verification, settled
spend, outstanding waits, and declared coverage. A complete result may cite newly persisted R4
evidence or fresh grounded evidence already present in current claims. Unresolved requested work
is finalized honestly as `needs_review`, never hidden as success.

Run aggregation reads every and only the selected R7 contact jobs. It exposes terminal and
suspended counts, finalization receipts, result references, channel state, spend, review items,
and exact contact identities. It rejects account research and any contact not in the selection.

## 6. Durable schema and production composition

Migration `7bb3178d7580` adds scoped, immutable state for:

- contact identity locks;
- facet lifecycle events;
- channel provider causation and exactly-once cost folds;
- coverage assessments and review items;
- finalization intents; and
- contact-fleet user returns.

Database triggers enforce exact R7 selection scope, selected facet/channel authority,
provider-operation causation, and append-only terminal evidence.

`build_contact_research_fleet_composition()` assembles R2 queue/lease execution, the R3
`create_agent()` runtime, the R4 governed tool factory, R7 launch authority, contact state,
facet/channel services, finalization, and exact-set aggregation. Production construction requires
run-scoped provider factories and rejects static job-to-action maps.

## 7. Acceptance evidence

The isolated Postgres R8 suite proves:

- a committee contact and a governed non-committee contact run on the shared fleet while an
  unselected contact remains untouched;
- the actual runtime constructs parent and facet units through
  `langchain.agents.create_agent()`;
- Exa contact compilation, acquisition, immutable snapshot, materialization, claim/evidence
  projection, agent observation, and zero-spend replay use the production plumbing with a
  deterministic provider-boundary transport;
- reveal and validation are separate decisions, external wait wakes the same checkpoint, and
  actual provider settlement is folded exactly once;
- facet output is accepted only under exact child-turn lineage;
- finalization and aggregation remain exact to the R7 selection and expose honest review; and
- production composition rejects static provider bindings.

The combined verification also includes the retained R0–R7 authority/runtime/fleet contracts,
C4 contact Exa materialization, C5 channel enrichment, and C6 selection regressions; a reversible
migration round trip and the single-head check; scoped Ruff, mypy, and import-contract checks.

Verification completed on the dedicated `clue_roseau_r8_20260806` Postgres database:

- combined R0–R8 and retained C4/C5/C6 matrix: **154 passed**;
- post-format R7/R8 and C5/C6 exact-set/channel matrix: **26 passed**;
- migration downgrade to `02e552db75da`, upgrade to `7bb3178d7580`, and one-head check: passed;
- scoped Ruff check and format check: passed;
- changed-source mypy: **11 files**, no issues; and
- import-linter: **24 contracts kept**, none broken.

No internet or paid provider request is claimed as R8 evidence. The provider-facing acquisition,
snapshot, materialization, channel, cost, wait, replay, and claim paths are exercised here with
deterministic transports. R10 retains the explicit bounded credentialed Exa/Sumble account and
contact canaries, provider-side receipts, paid-spend proof, and production cutover.

## 8. Exit decision

R8 is accepted when the recorded verification remains green. A separately approved contact run
profiles only its exact selected contacts on the shared fleet; contact agents can research,
delegate bounded facets, perform authorized channel operations, suspend/resume, finalize, and
return results without widening to the account or committee.
