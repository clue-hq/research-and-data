# Design Agent V1: harness audit and evaluation reset

Date: 2026-09-13. Scope: current local branch `codex/design-agent-v1`, existing
runtime sources and archived platform runs. No new generation, model change,
production modification or brand-ingestion implementation was performed in this
audit. Proposed changes below are not implemented by this document.

Follow-up: the [skill family plan](design-agent-v1-skill-family-plan.md) refines
the migration boundary and supersedes this audit's proposed rollout and test
matrix. Its additional runtime findings do not replace the historical evidence
below.

## Conclusion

The result does not meet the founder's creative bar. The preceding work verified
several important mechanics, but tested them with an operator supplying reference
IDs, fixed copy, dimensions and skill names. That is a diagnostic control, not
proof of an autonomous ad product. Removing the stars while preserving the weak
composition was a narrow repair, not a successful creative.

The next unit of work should be a coherent set of capabilities tested end to end
across brands. Do not spend another cycle polishing this same artifact, and do
not multiply overlapping skill files before clarifying who owns each decision.

## Findings and evidence

### 1. The latest format came from the test brief

The archived wide input explicitly requests 1200×628 twice. The saved PNG is
1200×628. The editor did not arbitrarily transform a square into a banner.
Earlier controls were 1080 square. A valid landscape export is still the wrong
benchmark when the intended first product is a square feed creative.

The current dedicated Images API adapter has a second aspect boundary:
`image_provider._snap_aspect_ratio` maps 1.91:1 to 16:9 and 4:5 to 3:4, while
1:1 and 9:16 pass through. These mappings were executed directly from the
current helper without a provider call. The wide image returned 1536×864 and
was cropped into the requested scene. This proves the adapter's current
behavior, not the provider's complete current capability list.

The final canvas, provider request and returned raster must be separately
recorded. Recompose native content for each placement. Do not stretch a banner
or assume a cover crop is semantically safe. Background overscan can be planned;
product controls, faces and copy need protected regions.

Sources: `apps/api/lumen_api/image_provider.py:88`, `:100`, `:798`, `:834`;
ignored wide input, summary and exported PNG.

### 2. Skills are installed and were read; autonomous selection is unproven

There are 28 current `knowledge_docs/skills/*/SKILL.md` files. The materializer
copies the canonical tree into the runtime workspace and invalidates copies on
a content-stamp change. The author receives the parent skills directory; the
director receives a generated name/description index. Full files are read on
demand. No chat attachment is required to install a skill.

The wide run records two reads of `reference-image-direction`, and reads of
`generative-imagery`, `reference-conditioned-ads`, `linkedin-square-ad`,
`linkedin-banner` and `web-display-banners`. Thus the skill was not missing.
Reading a skill does not prove its judgments were applied correctly. Explicitly
naming it in the test also does not prove discovery from a normal user request.

Sources: `apps/agent_runtime/lumen_agent/materialize.py:68`;
`lumen_agent/harness.py:54`, `:438`, `:568`; archived wide LLM tool-call log.

### 3. Existing skills overlap and contain incompatible guidance

- `brand-imagery` says generation is for a photographic/painted need the kit
  cannot supply; `generative-imagery` says generation is not a fallback for
  missing assets. Their operation-selection authority is unresolved.
- The older brand-imagery instructions still suggest
  `condition_on_references=false`; that argument is absent from the public
  `asset` tool. The new public contract uses `reference_asset_ids`, including
  `[]` for no references. This is a real documentation/tool mismatch; the
  archived wide run does not prove it caused that particular failure.
- The square skill permits omitting a CTA for awareness, but its defaults
  table still says "Request a demo." The story skill has the same default.
- Format guidance mixes placement constraints with particular layout recipes.
  The square skill was relaxed, but story guidance still says to select a
  named skeleton. Adding more skills without shared precedence invites drift.
- `conversion-copywriting` is framed around pages and sections. It does not
  establish that ad-copy strategy, optional on-artwork CTA, channel copy and
  evidence handling work autonomously in the ad path.

These are confirmed source inconsistencies. Their individual contribution to
visual failure requires a controlled comparison; do not attribute every poor
image to any single one.

### 4. Automatic ad references already exist, but selection is fragmented

**[SUPERSEDED 2026-10-30 — reference ads spec, `docs/superpowers/specs/2026-10-30-design-reference-ads-design.md`
(repo root): nothing is auto-attached and style groups are gone; the agent gets every brand ad
in `ad-assets.md` and chooses for itself. The finding below describes the earlier code.]**

The ad-assets lane can attach up to four harvested ads when the user supplied
none. It selects a named style group using a bounded text call, or falls back to
the newest harvested creatives. One group skips that call. The selector uses
the first 1,200 characters of the composed prompt; a long frozen brief can
therefore dominate newer steering. The lane also supplies a prose description
and eligible pre-generated grounds.

The wide run's reference manifest contains a published Marketplace creative.
Separately, the test tells the agent to generate from an orange/teal brand
background. The director's reference brief explicitly takes composition/mood
from the former and treatment from the latter. That mixing can be legitimate,
but it was not an autonomous test of finding one coherent reference family.
The manifest calls its references "user attached" even for automatic references,
which obscures their origin in audits.

Ordinary scene-library discovery is another path, capped at 24 recent ready
assets from a bounded scan. Kit assets and the ad lane are additional paths, so
24 is not the total number of assets the run can see. The new reference selector
chooses among already available, authorized assets; it is not a search interface
over the full brand library.

Recommended seam: one run-scoped selection record identifying composition
references, artwork references, authentic product evidence and logo variants,
with provenance and a reason for each. Make retrieval queryable by the visual
job and use the existing scoped asset/description substrate. The separately
planned brand agent may improve that substrate later; it is not implemented here.

Sources: `apps/api/lumen_api/ad_runtime.py:1`, `:93`, `:311`;
`lumen_api/main.py:9085`, `:11323`, `:11552`; archived reference briefs.

### 5. Delivering reference bytes is not preserving their visual system

The successful provider receipt proves that the explicitly selected original
raster was sent. But generation prepends a style-only/new-image instruction,
including an instruction not to copy, crop or edit the source. This does not
require visual failure, but it is a weak contract for tasks that need to retain
particular shapes, texture scale, spatial relationships or product identity.

Choose the operation explicitly: exact reuse, placement crop, supported source
edit, companion generation, or new concept. The public tool already exposes
generation, source editing and placement. Reconcile their instructions before
adding another service. Reference-role instructions must reach the actual
provider request and the final critique, rather than being flattened into a
generic style paragraph.

The current source-edit path is not proof of lossless layer extraction, exact
alpha cutouts or reliable native vector generation. Those are separate cases.
Authentic UI and logos remain independent source images; native text and button
geometry remain editable. No blanket ban on creative lighting belongs in a
brand-neutral skill: the reference and task determine the treatment.

### 6. Review accepts work that the user rejects

The baseline reviewers accepted weak contrast. The wide author self-audit and
director both accepted the invented luminous network. Human code/build checks
cannot judge visual quality, and a model awarding itself a fidelity score is
not independent evidence of usability.

The reference-fidelity finalization check currently depends on turn references
being present, not on every possible library asset selected later for generation.
Automatic ad attachments activate it, as in the wide case; a kit-only generation
without turn references needs separate coverage. Selecting a source for
generation does not itself register a new final-composition review target.

The system needs objective checks for dimensions, crop, text bounds, logo
identity, supported claims, asset availability and editability, plus a visual
comparison of the complete artifact with its selected reference family. Review
must reject the whole ad when composition is poor even if a repaired component
now looks better. Human comparison should calibrate the evaluator outside the
production agent loop.

Source: `lumen_agent/tools/substrate.py:4618`; archived critiques and user review.

### 7. The runtime has not become the proposed single design agent

The scene path still uses a director and a DSL author; fast-loop mode removes
the separate reviewer by default. The website code has a `web_solo` path that
gives one agent authoring tools and skills. The analogous scene route was not
implemented by the preceding skill work.

The wide run used 34 reasoning calls: 22 author and 12 director, with 26 file
reads and three compiles. The background-only repair used 29 reasoning calls.
The logged soft target is 900 seconds, not the requested 180–240 seconds. Merely
cutting that timeout would truncate work; it would not establish faster quality.
The actual run models were Grok 4.6 for reasoning and GPT Image 2 for artwork.
Codex's model is not automatically the platform's model.

A compact single-owner loop is a justified experiment: one agent derives the
brief, chooses skills/assets, writes copy, calls the image tool, composes through
the existing engine, inspects and performs a bounded repair. Preserve engine
operations, scoped data, persistence and provider receipts. Do not replace the
editor with flattened HTML screenshots. Single ownership is a hypothesis about
latency and consistency, not a proven visual-quality improvement.

Sources: `lumen_agent/harness.py:450`, `:568`; `lumen_agent/harness_web.py:304`,
`:545`; archived per-role metrics. Reported input-token totals include repeated
context and are not unique tokens or a billed-cost calculation.

## Recommended skill organization

Design the full taxonomy now; implement one coherent core and a few creative
families before expanding to 15–20. Refactor/reuse existing skills rather than
adding six more competing authorities. Skills teach decisions; brand assets and
examples remain scoped data, not executable instructions or new global skills.

| Responsibility | What it owns |
|---|---|
| Brief and copy | Audience, objective, supported promise, headline, optional on-artwork CTA, separate platform copy |
| Asset and reference selection | Relevant brand family, image roles, exact product sources, correct logo variant, evidence gaps |
| Image operations | Reuse/crop/edit/generate decision, provider request, variants, input/output custody |
| Editable composition | Native type/buttons/geometry, separate image/logo nodes, proportions and protected crops |
| Placement adaptation | Final canvas, readable type at feed size, placement-specific overlay zones, recomposition |
| Visual review and repair | Actual component/final previews, reference comparison, objective checks and honest rejection |

Start with three compositional playbooks: typography with brand artwork,
authentic product demonstration, and sourced testimonial/proof. Each playbook
should include differing brand examples, counterexamples, allowed variation,
required evidence and evaluation cases. A playbook is not a fixed left/right
template, and a visually good scraped ad is not evidence of high ad performance.

All skill metadata can be discoverable while only relevant bodies and resources
load. This is already the runtime's intended mechanism and is consistent with
[Deep Agents skills documentation](https://docs.langchain.com/oss/python/deepagents/skills).
Skills do not fine-tune model weights or automatically grant missing tool access.

## Test plan before another broad expansion

1. **Freeze the comparison.** Keep model configuration and brand/asset snapshots
   fixed; record code and skill content versions. Preserve failed examples.
   Compare the present system with the coherent candidate as a system comparison,
   not a claim that a single prompt change caused every difference.
2. **Exercise normal requests.** Use three authorized brand workspaces with
   visibly different aesthetics, one with a thin ad library. Use two short
   briefs per brand: awareness and product consideration. Supply no skill names,
   asset IDs, prewritten headlines, image-model prompts or manual layout rules.
   An optional user attachment remains a valid separate use case, not a prerequisite.
3. **Compare 12 fresh outputs.** Six cases times two system versions. Start with
   square feed creatives, with at most two independent cases in flight locally.
   Save every first output before feedback; repaired versions cannot replace the
   first-pass score. This is an exploratory benchmark, not a reliable percentile
   or generality estimate.
4. **Instrument the decisions.** For each run retain brief/brand binding, skills
   actually read and their versions, retrieved/viewed/selected assets, actual
   provider inputs and outputs, image mode, final scene and first-pass review.
   Record full request-to-saved time, model/tool counts, failures, retries, cache
   use and operator assistance. A screenshot or a skill-load log alone is not enough.
5. **Review blind.** Compare against the brand's reference family at export and
   realistic feed size. Judge brand recognition, idea/copy, hierarchy, relevant
   imagery, truthful product evidence, crop, optional CTA and editability.
   Human acceptance is independent of the generating model's score. Diagnostics
   with manually supplied assets belong in a separate bucket.
6. **Repeat and then adapt.** Repeat the promising route and try a held-out brand
   before claiming reliability. Add 4:5 and 9:16 adaptations with native
   recomposition and placement previews. If both routes fail, isolate retrieval,
   image-operation semantics and composition using the saved artifacts; do not
   change models, skills and references simultaneously and call it an ablation.

Placement baseline: square is 1:1; portrait feed is 4:5; full-screen portrait is
9:16, not 16:9. LinkedIn supports square, landscape and portrait; square is our
initial product/test choice, not the platform's only accepted format.
[LinkedIn's current help page](https://www.linkedin.com/help/linkedin/answer/a427596/)
specifies 1200×1200 for square and lists the other ratios. Meta's
[Reels documentation](https://www.facebook.com/business/ads/facebook-instagram-reels-ads)
supports the 9:16 direction and placement-safe messaging. Meta's detailed feed
and Stories image guides required login during this audit; exact per-placement
safe-area values should be checked in the placement preview rather than asserted
from the current skill's deliberately conservative padding constants.

## Isolation and product experience

One browser tab per case helps compare results but does not isolate data. Bind
each run to the intended workspace, brand-kit version and fresh project/chat.
Do not switch a brand within a test thread or import another brand's history.
Multiple brands can be tested on one local code version with these bindings.
Concurrent different code strategies need separate runtime instances and isolated
DB/storage/agent-workspace/log/cache roots; the branch alone is insufficient.
The external image-model experiment folder remains read-only and separate.

The intended user request can be as short as: "Create three LinkedIn ads for
hospitality operations teams." The agent derives copy, visual plan, asset
selection and placement from the request and stored context. It asks only about
a material gap it cannot resolve. Internal art direction should be detailed;
the user should not have to write it. Head of ABM may supply campaign strategy
when present, but direct design chat must also work. The separately planned
brand-preparation agent remains outside this assignment.

## Immediate next checkpoint

Reconcile the existing skill authority, reference selection/review contract and
placement-to-provider mapping; then implement the small coherent candidate and
run the short-prompt cross-brand comparison. Gate expansion on acceptable fresh
creatives, not on the number or length of authored skill files. The 3–4 minute
goal remains a measured target, never a promised consequence of more skills.
