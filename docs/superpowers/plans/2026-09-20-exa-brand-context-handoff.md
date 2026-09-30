# Exa-led Brand Context Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement this plan task by task after the user approves implementation. This deliverable is the plan and prompt pack only; do not activate another pipeline or alter the preserved 3046 work.

**Goal:** Reproduce the useful company/product/messaging/audience coverage of the Conduit reference through the existing Exa-led platform pipeline without Codex research or answer editing.

**Architecture:** Extend ARV2's existing Exa requests, durable worker, evidence ledger, knowledge artifacts and pure Markdown mappers. Add brand/messaging research and a dependency-aware Exa ICP producer while preserving human confirmation, tenant scope and current asset seams.

**Tech Stack:** Python, Exa Agent and existing deep-reasoning client, Postgres/artifact storage, existing fleet/agent interfaces, Markdown/YAML; optional cheap format repair only.

**Spec:** [Pipeline design](../../brand-context-research-handoff-v1/02-pipeline-design.md), [backend change map](../../brand-context-research-handoff-v1/04-backend-change-map.md), [evaluation](../../brand-context-research-handoff-v1/05-evaluation.md).

## Global constraints

- Preserve the original experiment, localhost:3046, four existing workspaces and environment/database bindings.
- No production integration is authorized by creating this plan. All future scope/contract changes require review as established in the repository.
- Research via Exa; no Codex search or manual answer editing in acceptance runs. Grok remains unchanged until the new producer is explicitly selected.
- Knowledge documents have Markdown/provenance, not creative agent-context panels. Ads and website media remain Assets.
- No fixed product or ICP count; complete the selected scope and expose gaps/continuation.
- Preserve approved human edits, immutable versions and tenant/project boundaries; never promote hypotheses to policy automatically.
- New flags documented at introduction; migrations only if reviewed contracts require them, random IDs, one head, disposable DB checks.
- Local commits at coherent checkpoints; no remote push without explicit request.

## Review focus

- Sparse or inaccessible public evidence must produce useful gaps without invented ICPs (Tasks 1–3).
- Enterprise catalogs and similarly named offerings need bounded scope and correct identity (Tasks 1–2).
- Conflicting pricing, availability and projected outcomes must survive research and rendering (Tasks 1, 4).
- Mid-run source/user edits must not mix versions or overwrite owner decisions (Tasks 2, 4).
- A superficially polished document may fail the actual qualification or messaging task (Task 5).

## Task 1: Preserve identity and expand research contracts

**Files:** Modify `platform/api/clue_api/arv2/onboarding_requests.py`, `onboarding_driver.py`, and catalog lineage types only as necessary. Extend `tests/arv2/test_onboarding_requests.py`, `test_onboarding_driver.py`, `test_onboarding_lineage.py`. Reference proposed prompts/schema in this handoff; do not import experiment code.

**Interfaces:** Existing `product_research_query(product_name, company_name, official_url, sibling_names)` receives the actual catalog context. Existing catalog discovery/reconciliation retains ownership of canonical product IDs. New task output follows the reviewed version of `schemas/research-output.schema.json` on the Agent surface only.

- [ ] Add a regression around the existing builder and the driver call that asserts an official URL and sibling context reach Exa:

```python
query = product_research_query(
    product_name="Console", company_name="Example",
    official_url="https://example.com/products/console",
    sibling_names=["Console Classic"],
)
assert "https://example.com/products/console" in query
assert "Console Classic" in query
```

- [ ] Add contract fixtures for unresolved identity, pricing unknown, conflicting meters and current/historical names. Assert omissions remain gaps and do not become false negative statements.
- [ ] Thread resolved catalog URL/aliases/siblings through the driver/lineage instead of hardcoded empty values. Add richer task schemas after reviewing field names/kinds against the existing store.
- [ ] Run the focused request/driver/lineage tests; commit the coherent change locally.

```sh
.venv/bin/python -m pytest tests/arv2/test_onboarding_requests.py tests/arv2/test_onboarding_driver.py tests/arv2/test_onboarding_lineage.py -q
```

## Task 2: Make input readiness and task scope explicit

**Files:** Modify `platform/api/clue_api/arv2/onboarding_driver.py`, `onboarding_store.py`, and `platform/api/clue_api/onboarding_synthesis_wiring.py`. Tests: `tests/arv2/test_onboarding_driver.py`, `tests/api/test_onboarding_synthesis_inputs.py`, existing DB counterparts on a disposable DB.

**Interfaces:** A dependent task consumes an immutable list of document ID/version/hash refs for selected offerings. Every prerequisite has completed/empty/failed status; unresolved critical evidence is explicit. Existing task cancellation/final settlement remains enforced. No custom state enum is silently added.

- [ ] Add an asynchronous regression holding one selected product task open; assert no complete ICP publication occurs before it settles. Then fail that task and assert either withheld ICP or a clearly provisional result with the missing dependency.
- [ ] Add a fixture with an unselected slow product; assert it cannot block an unrelated selected scope. Add large-catalog continuation and duplicate-task idempotency cases.
- [ ] Reorder the worker to snapshot the selected evidence before launching ICP; retain fast identity delivery and independent asset ingestion. Make message-map/example jobs wait for audience inputs too.
- [ ] Test a source update during persona execution: the turn retains its exact pinned inputs, and refresh produces a separate candidate.
- [ ] Run focused tests below and the DB counterparts only with isolated test configuration; commit locally.

```sh
.venv/bin/python -m pytest tests/arv2/test_onboarding_driver.py tests/api/test_onboarding_synthesis_inputs.py -q
```

## Task 3: Add Exa messaging and ICP research tasks

**Files:** Modify `platform/api/clue_api/arv2/onboarding_requests.py`, `onboarding_driver.py`, `platform/api/clue_api/onboarding_synthesis_wiring.py`, `onboarding_evidence_tools.py`. Add next reviewed versions of `platform/agents/catalog/skills/icp-synthesis/` and `audience-persona/` with matching registry updates if these surfaces remain consumers. Extend existing request, driver, evidence-tool and synthesis-input tests.

**Interfaces:** Tasks return candidate documents/evidence/criteria; the host assigns scope and IDs. ICP adapter preserves `product_ids`, stable key and existing structured contract. Only justified policy-backed necessary conditions become hard gates; readiness/urgency/preferences remain distinct. Persona evidence continues through the existing deep-reasoning contract.

- [ ] Add fixtures for one supported motion, no supported motion, multiple distinct motions and redundant motions; assert no mandatory two-profile behavior.
- [ ] Add unknown-stack and absent-timing cases; assert they remain research questions in the final gate adapter. Test `proposed` status and rejection of provider-supplied confirmation/scope IDs.
- [ ] Implement the reviewed Exa producer using existing `agent_run`, provider accounting and raw-response persistence. Do not duplicate the HTTP client or write both Grok and Exa outputs as current.
- [ ] Add positioning/voice tasks; then audience-aware message-map/examples with versioned dependencies. Keep inferred voice and proposed copy visibly unapproved.
- [ ] Add source-injection and private-data scope tests. Run focused offline suites; commit locally. Any provider canary belongs to Task 5, not unit tests.

```sh
.venv/bin/python -m pytest tests/arv2/test_onboarding_requests.py tests/arv2/test_onboarding_driver.py tests/api/test_onboarding_evidence_tools.py tests/api/test_onboarding_synthesis_inputs.py -q
```

## Task 4: Render, register and expose the new document families

**Files:** Modify `platform/api/clue_api/arv2/onboarding_documents.py`, `onboarding_store.py`, `platform/api/clue_api/brand_knowledge_context.py`, `frontend_read/brand_knowledge.py`; frontend repository/schema adapters after explicit contract review. Tests: `tests/arv2/test_onboarding_documents.py`, `tests/api/test_frontend_read_brand_knowledge.py`, `test_frontend_write_brand_knowledge.py` and existing knowledge-context DB tests.

**Interfaces:** Validated candidate → Markdown bytes → artifact hash → versioned document record → exact-version reader references. Normal metadata remains; asset usage context is not added to documents. Existing confirmed edits win until explicit reconciliation.

- [ ] Create fixtures with citations inside tables, unknown pricing and a negated capability. Assert rendered meaning/citations/units match the input, and internal filenames do not appear as display titles.
- [ ] Add a formatting-repair negative case: any semantic change is rejected. Keep Python as the default path; do not require a parser model for valid input.
- [ ] Review and implement new document kind/display-folder mappings. Add conflict-preserving user-edit and tenant/project isolation tests. If a migration is needed, generate a random revision and run up/down/up against a disposable database.
- [ ] Extend the current pure mappers/store/reader seam. Run relevant frontend checks only if frontend changes land; use the repository's existing check gate.
- [ ] Commit backend/contract and frontend changes in independently reviewable checkpoints.

```sh
.venv/bin/python -m pytest tests/arv2/test_onboarding_documents.py tests/api/test_frontend_read_brand_knowledge.py tests/api/test_frontend_write_brand_knowledge.py -q
```

## Task 5: Prove autonomous quality and controlled cost

**Files:** Add a new isolated evaluation directory/runner under a reviewed location, not the protected experiment. Reuse provider/storage adapters through their public interfaces; no private cross-subsystem imports. Store the frozen evaluation configuration, output references, timings, receipts and review decisions.

**Interfaces:** Resolved brand + selected scope + frozen prompt/schema/policy versions → new run records → immutable candidates + ledger + evaluation report. Reference bodies are scoring material only and never model inputs.

- [ ] Freeze the rubric and test cases in `05-evaluation.md`; record any owner-approved changes before execution.
- [ ] Run one bounded Exa schema canary after explicit authorization. Confirm request semantics, structured output, actual costs and evidence retrieval. A failed canary does not trigger unlimited retries.
- [ ] Run Conduit from sources without curated reference passages or manual editing. Record any intervention as supervised, not a pass.
- [ ] Run at least three held-out companies with different evidence/portfolio characteristics. Compare accuracy/usefulness per company, product coverage, time to first useful output, complete-run time and cost by provider/task.
- [ ] Obtain human acceptance of representative company/product/messaging/ICP outputs. Only then enable the reviewed producer path in an isolated platform instance and verify refresh, retrieval and edit preservation. Keep 3046 intact.

## Handoff completion versus implementation completion

This plan and prompt pack can be complete when their files, reference mapping and preservation checks pass. Tasks 1–5 remain unchecked because no implementation or paid evaluation was requested here. Do not report an automated quality pass, per-brand production cost, finished migration or platform integration from this handoff.
