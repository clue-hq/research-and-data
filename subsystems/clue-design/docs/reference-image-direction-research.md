# First Design Agent V1 skill: reference image direction

Date: 2026-09-12. Branch: `codex/design-agent-v1`.

## Scope and status

This assignment adds one skill to the existing deep design agent. The future
brand preparation agent belongs to a separate worktree and is not implemented
here. No new agent, provider integration, database schema, brand harvesting,
image-library expansion, model configuration or engine behavior is introduced.

The skill and supporting guide are authored and integrated into the existing
knowledge tree. Discovery/materialization is tested. **Live behavioral and
rendered creative acceptance are pending**; this document does not report an
improved ad or a measured 3–4-minute result.

The external image-model experiment remains separate and read-only. No files or
images from that folder are copied into this change. Worked examples describe
general visual decisions; they do not install one company's motifs as defaults.

## Why this skill first

The existing knowledge already contains `generative-imagery` (prompt/tool craft)
and `reference-conditioned-ads` (whole-ad interpretation). Adding another broad
ad generator would duplicate them. The narrower job is to translate inspected
inputs into an explicit image operation and a small number of properties to
preserve, before issuing a generation or edit request.

The prior component test recorded that a reference was actually delivered to
the provider while crop and speed acceptance still failed. Its final status
was a study with a crop gap, not a finished approved creative. This is useful
historical failure evidence, **not an A/B baseline for the new skill**. A fresh
matched comparison is specified in the evaluation cases.

Reference delivery, image quality, composition quality and editability are
different checks. A model can receive the right image and still choose the
wrong subject, lose the treatment, or place its result poorly.

## Research and resulting decisions

| Primary source, checked 2026-09-12 | Finding used | Application here |
|---|---|---|
| [OpenAI image-generation guide](https://developers.openai.com/api/docs/guides/image-generation) | Generation and editing are distinct operations; consistency and precise composition remain limitations | Select the operation by the preservation requirement; inspect actual results rather than promise fidelity |
| [OpenRouter image-generation documentation](https://openrouter.ai/docs/guides/overview/multimodal/image-generation) | Image references and optional controls depend on the model/endpoint's supported parameters | Distinguish provider capabilities from the arguments this app actually exposes |
| [Deep Agents skills](https://docs.langchain.com/oss/python/deepagents/skills) | Skills are progressively loaded folders; supporting resources must be discoverable | One concise entrypoint and an explicitly linked virtual-workspace reference |
| [Deep Agents context engineering](https://docs.langchain.com/oss/python/deepagents/context-engineering) | Focused skills avoid overlapping instruction/context growth | Keep this skill about image direction; reuse existing generation, composition and review skills |
| [Adobe effects overview](https://helpx.adobe.com/ca/photoshop/web/edit-images/color--tone--and-lighting/effects-panel-overview.html) and [bitmap methods](https://helpx.adobe.com/ca/photoshop/desktop/adjust-color/color-modes/convert-an-image-to-bitmap-mode.html) | Dither and halftone describe different methods/appearances; pattern scale and conversion matter | Describe visible texture and uncertainty instead of asserting exact algorithms from small images |

These sources support techniques and capability distinctions, not a claim that
this skill produces higher-converting ads. Public examples alone do not provide
conversion evidence. No paid campaign or performance test is part of this change.

## Verified local capability boundary

The current implementation is authoritative for what the skill may call:

- `apps/api/lumen_api/image_provider.py`: `STYLE_REFERENCE_FRAMING` explicitly
  treats generation attachments as style references. Provider documentation
  does not remove this local instruction. The current Images API branch sends
  automatic background; newer provider documentation listing transparency does
  not make alpha guaranteed through our current adapter.
- `apps/agent_runtime/lumen_agent/tools/substrate.py`: `asset` exposes generation,
  editing of a placed image, placement and kit-asset use. It exposes no per-call
  reference-selection/role argument. Placement cropping is a viewport, not an
  independently registered crop derivative.
- `apps/agent_runtime/lumen_agent/tools/view.py`: `reference:<n>` and `asset:<id>`
  provide visual inspection. Viewing is separate from provider-input selection.
- `crates/lumen-core/src/scene.rs`: native effects include shadows, glow and
  layer blur. The effect enum does not provide native dithering, halftone or
  backdrop blur. Custom native vector paths/icons are available through the DSL;
  a generated raster illustration is not an editable vector.
- `apps/agent_runtime/lumen_agent/materialize.py` and `harness.py`: new skill
  directories are copied into per-run virtual workspaces and appear in the
  materialized skill index without a new runtime registration mechanism.

No capability gap above is claimed fixed. The skill records such gaps and
chooses a supported operation when it can fulfill the brief. Further changes
to provider semantics, crop tooling or the one-agent harness need their own
implementation and tests.

## Files and integration

- Agent entrypoint: `knowledge_docs/skills/reference-image-direction/SKILL.md`.
- Supporting guide: `knowledge_docs/knowledge/images/reference-direction.md`.
- Routing: one task-map row and one skill-index row in `knowledge_docs/AGENT.md`;
  a narrow pointer in `generative-imagery` reuses the direction rather than
  adding another planning pass.
- Integration checks: `tests/test_reference_image_direction_wiring.py` verifies
  the real materializer, index and readable supporting resources.
- Live cases: `tests/evals/reference_image_direction.json` specifies eight cases,
  matched inputs, observations, failure examples and evidence to retain.

The main skill covers observation, operation selection, preservation versus
variation, layer planning, capability honesty, and bounded review. The guide
contains four worked applications, an effect vocabulary, a compact direction
record and the actual tool contract. It imposes no fixed background motif,
split-screen layout, CTA, arbitrary image count, or universal safe-area margin.

## Validation and next experiment

Before authoring the skill, both new integration checks failed because the
runtime could not discover or materialize it. They passed after authoring.
These are resource-delivery checks, not artistic or agent-behavior tests.
The focused skill/format/reference/materialization regression set passed all
263 collected tests. The new test file's import-order lint finding was corrected;
the evaluation-case file parses as JSON. No engine source changed, so no helper
or WASM rebuild was needed for this knowledge-only addition.

For the first live comparison, select `abstract-companions`,
`authentic-product-evidence` and `new-concept` from the case file. Pin the same
brief, source bytes, model configuration and capabilities in independent
baseline/candidate workspaces. Keep knowledge fixed while a run is active.

Inspect reference delivery, new-image provenance, generated pixels, the final
layered scene, save/reopen behavior and elapsed time. Record unsuccessful runs
alongside successful ones. Repeat a representative case and use another brand
before treating the technique as generalizable. Do not turn a missing crop or
reference-selection capability into a prompt-only workaround and call it fixed.

This skill's first integration does not replace the current multi-role harness
or silently supersede every older composition rule. Conflicting inherited
instructions and missing tools remain candidates for separately scoped work.
