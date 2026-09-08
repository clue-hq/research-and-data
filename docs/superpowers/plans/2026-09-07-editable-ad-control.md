# Editable Ad Quality Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** run a reproducible four-treatment comparison and deliver modern ads whose required copy, logos, buttons and artwork placement remain editable.

**Execution update, September 7:** Start with two matched current-engine reference/no-reference pairs before implementing mixed C/D treatments. See [the plain-language execution guide](2026-09-07-ad-control-execution.md). Task 2 remains required before mixed candidate/reviewer dispatch, not before this initial input comparison. Head-of-ABM implementation and skill changes are outside this project; Task 8 records the existing handoff and observations for the separate Fable work only.

**Architecture:** preserve the current Head-of-ABM → durable Design handoff → Fleet → scene engine. Introduce a scoped immutable experiment manifest and candidate creative policy, reuse existing image generation and native scene tools, and evaluate both visual quality and real editing behavior. Ordinary turns retain baseline behavior until explicit promotion.

**Tech Stack:** existing Python/FastAPI/deepagents, Postgres/Fleet/Redis, Rust DSL/native helper/WASM, Next.js editor, existing Grok and GPT Image 2 provider adapters. No new hosting or evaluation service.

**Spec:** [editable-ad-control-design.md](../specs/2026-09-07-editable-ad-control-design.md)

**Tickets:** [Linear ticket pack](2026-09-07-editable-ad-control-tickets.md). Planning keys are not external issue IDs.

**Path convention:** root platform paths are repository-relative. Design runtime, API, skills, knowledge, scripts and their tests live under `subsystems/clue-design/`; `lumen_agent` is under `apps/agent_runtime/`, `lumen_api` and `lumen_ingestion` are under `apps/api/`. New module/test paths below are proposed implementation targets, not claims that those files already exist.

## Global Constraints

- Same checkout `/Users/shashank/Documents/clue-latest-pull-sept7`, branch `shashank/local-setup-sept7`; local commits only.
- Two-day project, September 7–8, 2026, America/Los_Angeles; tonight is the first-comparison target.
- Raster artwork is allowed. Native editable headline/support/CTA text, separate logo and button layers, and independently editable artwork placement are required.
- Preserve exact source assets and claim provenance; no brand-specific production branches or invented customer proof.
- Maximum four concurrent experiment runs; separate document, chat, run, checkpoint and generated-asset lineage for every run.
- Freeze code, model, prompt/tool and input hashes before launch. Never change process-global policy while a comparison is running.
- The planning checkpoint contained no generation results. Execution status and evidence are recorded separately; never infer completion from this checklist.
- External project/ticket creation should use Linear MCP as requested; browser is for read-back, unless the user authorizes a fallback.

## Task 1: Freeze experiment ownership, inputs and Fleet evidence

**Files:** create ignored `.local-setup/ad-control/cases.json`, `treatments.json`, `run-manifest.json`; extend the existing local readiness evidence. Read `platform/api/clue_api/{design_leg_tools,design_leg_wiring,design_fleet}.py` and `platform/fleet/clue_fleet/{queue,lease,work_worker}.py`.

**Interfaces:** case records identify the same-workspace brand kit/version, business brief, source claim refs and input asset digests. Treatment records identify A/B/C/D and exact code/resource/model pins. The run manifest maps each case+treatment+replicate to real project/chat/document/run IDs returned by governed app operations; no fabricated IDs.

- [ ] Capture the clean starting commit and available provider/model settings without secrets.
- [ ] Curate one matched case and at most four relevant reference images per attached set. Tag exact logo/product inputs separately from style references. Use supplied references through the normal custody path; never treat a Codex attachment as already present in Clue.
- [ ] Check queue, worker registration, Redis and same-database connections. Readiness has been verified; retain a fresh timestamp at launch.
- [ ] Create the local Clue control project and four separate chats/documents through authenticated product APIs/UI. Create no production campaign.
- [ ] Verify returned ownership and brand pins, and that editing one document cannot mutate another.
- [ ] Commit only generic fixtures/contracts; keep private inputs and generated media ignored.

## Task 2: Isolate treatment configuration through the durable envelope

**Files:** proposed new `subsystems/design/clue_design/experiments.py` for the scoped artifact contract; modify `platform/api/clue_api/design_leg_wiring.py` at offer-time freezing, design API `main.py` at `AgentRuntimeConfig.from_env`, and `apps/agent_runtime/lumen_agent/config.py`. Add `tests/design/test_design_experiment_pins.py` and design API `tests/test_ad_experiment_config.py`.

**Interfaces:** `resolve_experiment_manifest(conn, *, workspace_id, project_id, experiment_ref) -> dict` reads a server-owned versioned artifact and validates ownership. The immutable envelope carries the resolved manifest by value. Runtime only accepts allowlisted treatment values; it never accepts arbitrary filesystem paths or user-authored system prompts. Missing experiment manifest preserves today's defaults. C uses candidate creative policy; D additionally sets the existing `scene_reviewer` option for that run.

- [ ] Write refusal tests for unknown manifest, wrong workspace/project, changed digest and unsupported treatment; assert no provider call or run mutation occurs.
- [ ] Write the concurrent isolation regression: schedule A and D in one process, construct their runtime configs, and assert A stays baseline/reviewer-off while D stays candidate/reviewer-on after both have been built.
- [ ] Write retry verification: modifying the currently active policy after offer does not alter an already frozen envelope.
- [ ] Run the new tests and observe failures before implementing the scoped resolver/config mapping.
- [ ] Implement only the resolver, by-value envelope field and `dataclasses.replace` config override. Do not modify global settings or add a parallel job queue.
- [ ] Run new tests plus existing Fleet/design checkpoint tests, then review/commit this shared seam before parallel edits begin.

## Task 3: Fix reference selection and preserve fallback truth

**Files:** `subsystems/design/clue_design/ad_assets.py`; design API `lumen_api/ad_runtime.py`; ingestion `ad_library/{onboarding,distill,pregenerate}.py`; `platform/api/clue_api/brand_kit_ingestion.py`. Tests: existing ad-reference/onboarding suites plus new `tests/design/test_ad_lane_brand_scope.py`.

**Interfaces:** selected references are derived only from the frozen selected brand/kit inventory. Manual references still win. Reference descriptors carry source role, creative concept, composition, relevance reason and asset identity; the preview bytes continue through the existing attachment manifest.

- [ ] Add a two-brand regression where the most recently ingested ad belongs to the other brand; assert it is never selected.
- [ ] Add a style-group regression asserting each pregeneration group receives its own references, not the first four workspace creatives.
- [ ] Add missing-library/empty/mismatch/provider-failure cases that preserve distinct existing outcomes and use website/brand inputs honestly.
- [ ] Implement brand/kit filtering, relevant group descriptors and group-specific inputs. Keep provider identity checks and manual-reference precedence.
- [ ] For tonight, use curated attachments and record auto-harvest coverage separately. Wire automatic onboarding on day two through the existing job-offer seam, with no duplicate provider jobs.
- [ ] Run focused tests and commit. Do not add Meta support in this two-day core scope; leave it as a separate provider extension if needed.

## Task 4: Add the candidate creative plan and editable composition policy

**Files:** design runtime `lumen_agent/{prompts,harness,frame}.py`, candidate skill resources beside existing design skills, and focused tests `tests/test_ad_creative_plan.py`. Existing starting points: `skills/{create-design,linkedin-square-ad,generative-imagery}/SKILL.md`, `knowledge/design/layout-recipes.md`, and `knowledge/lumen-dsl/grammar.md`.

**Interfaces:** a candidate plan records `concept`, `message`, `claim_refs`, `headline`, `composition`, `copy_zones`, `asset_roles`, `layers`, `variant_intent` and `format`. It is an inspectable run artifact consumed by author and reviewer. It does not claim platform authority or require another agent. Effective skill bytes are frozen by the experiment manifest.

- [ ] Test required layer roles and source refs on a product-demo, editorial and review/proof brief. Reject a proposed complete-ad bitmap carrying required headline/CTA.
- [ ] Preserve A/B's policy bytes. Candidate C/D removes mandatory split/three-skeleton selection, universal seven-word limit and universal button plate; retain legibility, source and layout constraints.
- [ ] Teach the author to generate a composition appropriate to the message and build native overlay layers; a focal group can contain multiple coordinated assets.
- [ ] Keep a concise concept/copy planning step inside the Design director. Avoid mandatory extra copywriter calls.
- [ ] Reuse native primitives and introduce only fragments needed by the first cases: CTA group, proof card, feature chip and device frame. Verify they compile and stay independently selectable.
- [ ] Test and commit candidate policy without changing the active Head-of-ABM catalog pins.

## Task 5: Generate and retain independently placeable artwork variants

**Files:** design `lumen_agent/tools/substrate.py`, `lumen_api/image_provider.py`, imagery skill/prompt resources; tests `tests/test_ad_artwork_roles.py` and existing provider tests.

**Interfaces:** image requests distinguish style-reference images from exact subject/source assets in prompt framing; the provider still receives only parameters verified for its endpoint. Variant records contain asset ID, digest, model/settings, source refs, prompt/resource version and intended layer role. Each output is custodied through existing asset tools before scene placement.

- [ ] Test that headline, logo and CTA instructions stay out of artwork generation, while exact source UI is preserved when requested.
- [ ] Test that two requested variants retain distinct records and neither overwrites the other's scene/image binding.
- [ ] Test cache keys differ when references, model/settings or intended artwork role differ.
- [ ] Implement role-aware prompt construction and variant retention using current tools; keep ordinary generation behavior unchanged for A/B.
- [ ] Generate at most two initial artwork variants per candidate run. Store refusals/errors explicitly; never substitute grey/placeholder art and call the case successful.
- [ ] Run provider/custody tests and commit. Transparent output, masks and exact pixel sizing are enabled only after model/provider capability verification proves support.

## Task 6: Grade layer editability and reference-directed quality

**Files:** add `apps/agent_runtime/evaluation/ad_editability.py` and `tests/test_ad_editability.py`; reuse `evaluation/brand_fidelity.py` with explicit kit input; extend candidate reviewer prompt in `lumen_agent/prompts.py` and reference-viewing tools where necessary.

**Interfaces:** `evaluate_editability(scene, layer_roles) -> report` returns pass/fail plus named violations. The report checks actual node/asset types for required roles; image-layer transform editability is distinct from pixel editing. Visual review sees rendered pixels, case brief, relevant references and the structural report, and cannot override hard failures.

- [ ] Use real scene fixtures to test native headline + independent logo + CTA group passes; flattened headline image fails; outlined-only headline fails text editing; ordinary background image passes; wrong brand or missing required asset fails.
- [ ] Measure typography/brand binding with the existing evaluator's direct functions, avoiding its legacy implicit database lookup.
- [ ] Add reference-aware 1–5 rubric anchors for relevance, brand character, hierarchy, composition and variety; retain critic rationale and confidence.
- [ ] Configure D's existing scene reviewer per run with one bounded repair, and measure its incremental cost/time over C.
- [ ] Run focused tests, review and commit before launching the experiment.

## Task 7: Dispatch the matched A–D control and inspect it in the browser

**Files:** add `scripts/run_ad_quality_control.py` using the existing authenticated product dispatch seam and experiment manifest; tests `tests/design/test_ad_control_runner.py`; ignored `.local-setup/ad-control/results/`.

**Interfaces:** the runner consumes the frozen case/treatment manifest; dispatch returns real job/run references. Concurrency uses a semaphore of four over normal Fleet offers, not direct calls around Fleet. It records offer, claim owner/generation, lease renewal, terminal state, scene version, image assets and metrics for every case.

- [ ] Add tests for max-four concurrency, unique per-case document/checkpoint ownership, idempotent retry, cancellation and partial batch failure. One failure must not label the whole batch successful or lose other results.
- [ ] Run those tests with stubbed provider boundaries before live dispatch.
- [ ] Freeze the code and resource digests, then start A–D concurrently. Do not edit shared code or restart workers during the batch.
- [ ] Verify fresh Fleet claims and renewals from persisted state, then materialize every completed run using `subsystems/clue-design/scripts/run_view.py`.
- [ ] In Codex browser, change headline and CTA copy/style, move/resize logo, swap/crop an image variant, save, reload and export. Verify each action independently; keep screenshots and source scene versions.
- [ ] Record blind A–D scores and all failures. The first comparison is exploratory; repeat the useful contrast before claiming improvement.

## Task 8: Harden the selected candidate and close the two-day project

**Files:** focused fixes in the owning modules above; extend regression fixtures and generic `_memory/` closeout; project result document and Linear issues.

**Interfaces:** the decision report links each case to its exact run/artifact IDs, scores, edit checks, timings and known gaps. Promotion consumes a reviewed winning config; it is not automatic on highest average score.

- [ ] Test the selected candidate on a different concept and another available brand. If no second real brand exists, explicitly limit the claim to mechanical fixture coverage.
- [ ] Recompose a selected creative into square, portrait and landscape; check copy fit, subject crops, logos and CTA per format. Add a story safe-area case if that placement is in scope.
- [ ] Verify no-ad-history behavior remains useful and honest rather than assuming missing LinkedIn ads are rare.
- [ ] Document Head-of-ABM handoff ownership and any observed brief gaps for the separate Fable work. Do not change its prompts, skills or profile pins in this project.
- [ ] Run required checks on changed surfaces. Engine changes require full Rust workspace → release helper → WASM handshake → agent suite → API suite. Use a fresh disposable test database/storage pair to avoid the diagnosed stale public-asset candidate-limit failure; do not weaken that test.
- [ ] Verify final editor behavior and record what passed, what failed, cost/latency and the selected next step. Mark tickets Done only with evidence; leave unresolved work open.
- [ ] Close the control project only when its hard editability gates and agreed comparison evidence are complete. Keep website work separate and production deployment explicit.

## Delivery checkpoints and dependencies

Task 1 → Task 2 fixes the shared contract. Tasks 3, 4 and 6 can then proceed independently; Task 5 consumes Task 4's layer roles. Task 7 waits for the frozen integrated checkpoint. Task 8 follows measured results. Shared files `main.py`, `config.py` and `design_leg_wiring.py` have one integration owner to preserve this same checkout.

Linear milestones: **Control ready**, **First comparison tonight**, **Editability and generalization**, **Decision and handoff**. Issue contents are provided in the adjacent ticket pack. Project setup is distinct from a successful experiment; no generated output or test result may be fabricated to fill a ticket.
