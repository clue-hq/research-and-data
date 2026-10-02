# Editable Ad Quality Control

Project design for a two-day sprint. Planning and ticket preparation are authorized; this document does not report generation results. User clarification on September 7 supersedes the earlier strict-vector interpretation.

**Outcome:** produce modern, brand-directed ads with multiple generated image variants, while preserving editable copy, logos, buttons, placement, and independent artwork layers. First controlled comparison and a usable editor demonstration are the tonight target; repeatability and broader coverage are the second-day target. Universal perfection across brands is not a credible two-day acceptance criterion.

**Team:** Product Engineering, in the existing Clue HQ Linear workspace. Preferred identifier PE, subject to availability. **Project:** Editable Ad Quality — Control Test. **Window:** September 7–8, 2026, America/Los_Angeles. No advertising campaign, two-week engagement, or scheduled automation is requested. Work stays in the existing checkout/branch; no new worktree, remote publication, or production deployment.

## Product contract

- Generated backgrounds and illustrations may be raster assets. Their pixels need not be editable.
- Headline, supporting copy and CTA labels remain native text, not text baked into generated artwork or outlined paths that lose text editing.
- Logo identity is preserved; logo placement, size and visibility remain independently editable. Existing logo/vector artwork does not require editing its individual paths.
- Buttons are independent shapes/groups with editable text and style. Awareness concepts can omit an in-image button when the brief permits it.
- Every meaningful artwork component delivered separately remains an independently selectable image/vector layer. Its position, dimensions and appropriate crop/appearance controls survive save and reload.
- Generated vector ornaments are optional separate assets or native paths. Do not represent raster-to-vector placeholder output as real tracing.
- Exact product screenshots and UI illustrations may remain original images/vector assets. Generated UI must not silently invent product functionality, metrics, or customer evidence.
- Brand-specific palettes, typography, logos, audience and claims come from pinned inputs. Brand names or reference layouts are not production-code branches.

## Existing responsibilities, verified in this checkout

Head of ABM currently uses profile `head-of-abm@v40`, prompt v7, and Stage-0 skill v20. Its `open_design_leg@4` input carries free-text brief, brand-kit/version pins, governed claim refs, and optional binding/template refs. It creates the durable handoff and an empty scene; it does not render the ad or automatically start generation. The next user message starts a design turn. While a design leg is open, messages route directly to Design. On close, Head of ABM receives the exit summary rather than the entire design transcript.

Within Design, the director interprets the brief and chooses the creative direction; the author writes copy and builds the DSL scene using real tools. The current fast loop uses author self-review and director judgment; a separately enabled scene reviewer already exists. Content-drafter delegation is available elsewhere but is not mandatory in this ad path. We should not add another agent just to give copywriting a name.

The proposed responsibility boundary: Head of ABM transfers the complete business intent, exact user constraints and source refs; Design owns creative strategy, proposed copy, composition, image requests and editable construction. A concept/copy plan is an inspectable output inside Design, not a new ungoverned content store. Fable's Head-of-ABM resource work must be coordinated through immutable catalog versions and explicit pin promotion, not edits to published v7/v40 bytes.

Sources: `platform/api/clue_api/design_leg_tools.py`, `design_leg_wiring.py`, `chat/router.py`, `agent_registry_wiring.py`; `platform/agents/catalog/prompts/head-of-abm/v7/SYSTEM.md`; design `lumen_agent/{config,harness,prompts}.py`.

## Four concurrent treatments

Use four independent Clue chats/documents under a control project, with one active run per document. Freeze code revision, effective prompt/tool manifests, models, brand kit, case brief, reference bytes/digests, limits and artifact provenance before starting. Never edit global environment or skill files while runs are in flight.

| Treatment | Configuration | Question |
|---|---|---|
| A — current control | Current creative policy and normal asset selection | What does the current system produce from this brief? |
| B — reference control | A plus curated, relevant ad references | How much does supplying the right references help? |
| C — editable creative harness | B plus concept/layer plan, broader format policy, generated artwork variants and native overlays | Does the proposed harness improve quality and editability? |
| D — reviewed candidate | C plus the existing independent scene reviewer with reference-aware criteria and one bounded repair | Is the extra review worth its quality, time and cost? |

This is a staged ablation of change packages, not a statistical proof that any one prompt sentence causes the improvement. Four creative concepts alone are not four control treatments. Use the same case across A–D, compare blind, then repeat on another case or with another replicate. Do not declare a universal winner from four outputs.

Tonight: one matched case across A–D, at most four concurrent design runs. C and D request two distinct artwork variants, retaining rejected variants as inspectable assets. After inspecting the first batch, repeat the most useful comparison on a different concept if time permits. Day two: the chosen candidate plus control on another brand, a no-ad-history case and multiple aspect ratios. If another real brand is unavailable, use a clearly synthetic fixture to test mechanics and state that cross-brand visual quality remains unproven.

Initial models remain the configured `x-ai/grok-4.6` and `openai/gpt-image-2` so harness and model changes are not confounded. A later model comparison is a separate experiment. Highest quality means selecting from measured results; no unmeasured promise that these pins are optimal.

## Required harness changes

1. **Experiment isolation.** Add a server-owned, project-scoped experiment manifest resolved into each immutable design envelope. Carry treatment, prompt/tool digests and reviewer setting per run. Existing configuration is built from process environment, so per-treatment concurrent overrides are not currently proven. Resolve this before mixed-treatment dispatch. Unknown/cross-project experiment refs refuse before any provider call; ordinary turns retain current behavior.
2. **Reference quality.** First use explicit supplied ad references through the existing attachment/custody path. Then connect the existing LinkedIn onboarding workflow to brand onboarding, pin retrieval to the selected brand/kit, and preserve existing successful/empty/partial/mismatch/failure outcomes. Describe concept, composition, image role and product relevance, rather than relying only on style-group names or recency. Keep manual references authoritative.
3. **Creative plan.** Record audience, objective, sourced message, headline, composition, exact asset roles, copy zones and layer map before generating. Use product demonstration, editorial statement, proof/review and launch/device group as extensible families. These are compositional vocabulary, not rigid layouts.
4. **Artwork requests.** Generate artwork with deliberate copy-safe areas; separate exact subject inputs from style references. Avoid generating main copy, logos or CTA inside the artwork. Preserve multiple variants and provenance. Reuse approved artwork where appropriate, with cache identity including brief/refs/model/settings/version. Do not call the generator for a simple native gradient that already meets the concept.
5. **Editable composition.** Use existing scene text, shape, group, image and vector primitives. Prefer small reusable native fragments for buttons, chips, cards and device framing only where repeated construction causes failures. Preserve deterministic compiler/operations authority; never write arbitrary scene JSON around it.
6. **Verification.** Inspect scene structure, actual browser editing and exported output. A critic cannot certify editability from a screenshot. Visual review compares reference intent and brand character, not pixel imitation. A failed quality gate stays visibly unaccepted even if a run finished.

## Acceptance and measurements

Hard failures: missing logo/assets/fonts, main copy baked into artwork, non-editable required layers, wrong brand/kit, invented proof claims, failed save/reload, clipping that obscures the message, cross-run contamination, or conflicting writes. A visually attractive image cannot override a hard failure.

For every candidate, actually edit a headline, change CTA copy/style, move and resize the logo, swap an artwork variant and adjust its crop; save, reload, and export. Verify the edits persist and unrelated layers stay intact. Preserve live text in the source scene. PNG/JPEG delivery export is expected to be flattened; it is not evidence that the editable source was lost. Check SVG/PDF behavior separately rather than promising universal export editability.

Score message/asset fit, brand character, hierarchy/readability, composition/craft and meaningful variation on an anchored 1–5 rubric. Proposed tonight bar: all hard gates pass, no dimension below 3, average at least 4, and human preference over A. This is an internal acceptance target, not a validated industry threshold. Calibrate the visual reviewer against the founder's examples and critiques.

Record first usable preview time, final time, LLM calls, generated assets, repair attempts, cached/uncached usage, actual reported cost when available, terminal status and layer-edit results. The earlier single run's 17m43s/57 calls is historical context; A is the fresh comparison baseline. Cap experiment concurrency at four even though four workers each advertise four slots. Respect existing runtime and provider limits; log throttling and cold/cache differences. Do not increase budgets to hide failure.

Fleet readiness currently verified: four live worker processes, established Postgres connections, current database activity, design handler registration and Redis PONG; queue idle. Fresh dispatch/lease/finish evidence remains an acceptance requirement for the experiment.

## Tonight and day two

Tonight's critical path: freeze manifest and inputs → isolate treatment configuration → prepare candidate policies and layer checks → dispatch matched A–D → browser edit/save/export walk → blind comparison and decision. Parallel implementation can cover references, creative policy and evaluators after the shared manifest/contract is fixed; one integration owner handles shared dispatch/config files. Run generation only after a stable checkpoint. A first usable result tonight is a target, not a promise to finish every generalization.

Day two: fix the measured failures, wire automatic harvesting and honest fallback, verify multiple formats and another brand, then finish the regression and handoff report. Website repairs follow this checkpoint as a separate project scope. No production rollout is implicit in the control test.

The standard evaluation pattern is a fixed dataset, versioned target configurations, objective checks plus calibrated human/visual judgments, and comparable recorded experiments. We can use existing local traces and evaluation modules without installing another evaluation service. See [LangSmith evaluation concepts](https://docs.langchain.com/langsmith/evaluation-concepts) and [evaluation guide](https://docs.langchain.com/langsmith/evaluate-llm-application).
