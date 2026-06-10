# Phase C: Brand Kit And Design-System Maturity

Date: 2026-06-10

Status: implementation plan and current contract record for Phase C. The
`brand-kit/design-system-contract-v1` branch now implements the core Brand Kit
contract plus the first API, editor, agent-knowledge, and trace-evaluation
surfaces. Remaining work is called out explicitly as product integration or
deferred extraction/runtime work.

## Purpose

Phase C moves Lumen from "token resolution exists" to "brand-aligned design is
the default behavior of the product."

The ABM design engine must generate artifacts for many client brands. The
quality bar is not only whether a design compiles, fits, and exports. A useful
artifact must look like it belongs to the client's brand system: typography,
surface treatment, accent usage, spacing, radius, illustration style, logo
placement, light/dark behavior, print/digital constraints, and accessibility
rules must all work together.

Phase C should therefore build a real Brand Kit and design-system layer around
the existing token resolver. The resolver is the foundation. The missing product
layer is generation, governance, validation, knowledge, and repeatable design
guidance.

## Product Goals

Phase C should make these user-facing behaviors possible:

- A user can select or generate a Brand Kit and expect new artifacts to use it
  by default.
- A generated artifact uses semantic tokens rather than arbitrary colors,
  spacing, and type sizes.
- A design can be checked for off-brand choices before acceptance.
- A Brand Kit can describe logo variants, custom illustrations, surface
  treatments, typography roles, spacing, radius, stroke, opacity, and mode
  behavior.
- A Brand Kit can support light/dark, compact/comfortable, high contrast, large
  text, print, and digital modes.
- A template can declare which Brand Kit version it was authored against, and
  compatibility can be checked when the Brand Kit changes.
- Agents receive brand-specific guidance and can explain why a token or style
  was chosen.

## Gap References

This phase addresses gaps recorded in
`reference_docs/Brilliant-vs-Lumen-Product-Gap-Analysis.md`:

- **Product Improvement Plan / Design System**: Lumen needs a generative
  Brand Kit compiler/generator, semantic aliases, modes, ingestion, validation,
  and governance.
- **Design System Comparison**: Brilliant has a `.styles` compiler, OKLCH
  ramps, semantic aliases, scale generators, and mode-rich tokens. Lumen has the
  resolver foundation but lacks the product-grade style-governed layer.
- **Text And Typography Comparison**: Lumen needs reusable type roles instead of
  ad hoc raw font sizes.
- **Agent Loop Comparison**: agents need stronger brand knowledge and brand-fit
  critique, not just DSL syntax.
- **Demo failure: generic or inconsistent visual output**: richer Brand Kits
  should reduce generic model styling and make generated artifacts more
  client-specific.

## Current State

Lumen already has important Phase C foundations:

- `BrandKit` model in `crates/lumen-core/src/brand.rs`.
- Versioned kit identity and `BrandKitRef` on scenes.
- Token catalogs for colors, typography, numbers, spacing, radii, stroke
  widths, opacity, shadows, effects, assets, and aliases.
- Mode support through `BrandModeSpec` and `ModeValue`.
- Platform default Brand Kit fixture.
- Brand validation and scene token validation.
- Token resolution into canonical scene operations.
- Strict token modes that can flag bare paints, strokes, corners, opacity, and
  text styles.
- Typography style tokens and text token carriers.
- Font and logo asset metadata with licensing fields.
- A small `.styles` compiler surface through `compile_styles_brand_kit`.

The current gaps are not that tokens do not exist. The gaps are:

- the default Brand Kit is not yet rich enough to guide good design;
- the token taxonomy is not complete enough for real client brand systems;
- the `.styles` compiler is not yet a real design-system authoring language;
- there is no robust generator from seed colors, logo, website, or uploaded
  style guides;
- strict brand validation is not product-grade enough to identify off-brand
  choices;
- agents have limited brand knowledge and weak brand-fit critique;
- editor/API flows do not yet expose brand versioning, compatibility, approval,
  or overrides as product concepts.

## Non-Goals For Phase C

Phase C should not become a full brand-management SaaS product. It should avoid:

- production-grade website scraping pipelines;
- final legal/license enforcement for all asset/font edge cases;
- final Figma library import/export;
- every possible design token category;
- full visual identity approval workflows;
- trying to infer perfect brand systems from one logo with no user review.

Those can follow once the core Brand Kit and design-system model is strong.

## Architecture Principles

### 1. Brand Kit Is Canonical Brand Data

The Brand Kit should own brand semantics:

- token catalogs;
- mode rules;
- asset refs;
- logo rules;
- typography roles;
- brand constraints;
- source/provenance/confidence;
- compatibility metadata.

DSL should reference brand tokens, not define the full brand system inline.

### 2. Scene Still Owns The Design

The scene should store:

- authored token references;
- resolved concrete values after preflight;
- scene `BrandKitRef`;
- operation history for token materialization;
- compatibility diagnostics.

The scene should not duplicate the whole Brand Kit.

### 3. Resolution Must Remain Deterministic

Brand generation may use agents and heuristics, but token resolution must remain
deterministic and testable in `lumen-core`.

### 4. Brand Governance Must Be Explainable

Off-brand diagnostics should explain:

- which token or rule was violated;
- which node/page was affected;
- what token should be used instead;
- whether the issue is an error or warning;
- whether an explicit override is allowed.

### 5. Brand Inputs Need Provenance

Generated Brand Kits must preserve source and confidence:

- seed color;
- logo file;
- website;
- uploaded PDF/style guide;
- agent extraction;
- manual user edit;
- platform default.

## Target Brand Kit Model

The existing model should be expanded conservatively. The target Brand Kit
should express the following categories.

### Metadata

- `id`
- `version`
- `name`
- `description`
- `sources`
- `provenance`
- `approval_status`
- `compatibility_policy`
- `created_at`
- `updated_at`

Suggested approval states:

- `draft`
- `generated_unreviewed`
- `approved`
- `deprecated`

### Modes

Required mode axes:

- `theme`: `light`, `dark`
- `density`: `comfortable`, `compact`
- `accessibility`: `standard`, `high_contrast`, `large_text`
- `medium`: `digital`, `print`

The current model has `theme`, `density`, and `accessibility`. Phase C should
add `medium` because print and digital often need different color, type, and
asset behavior.

Mode behavior should support:

- default mode values;
- per-token mode overrides;
- validation that required mode branches exist for critical semantic tokens;
- fallback rules when a mode-specific value is missing.

### Color Tokens

The Brand Kit needs both primitive and semantic colors.

Primitive tokens:

- `palette.primary.50` through `palette.primary.950`
- `palette.secondary.50` through `palette.secondary.950`
- `palette.neutral.50` through `palette.neutral.950`
- optional `palette.accent.*`
- optional `palette.success.*`, `palette.warning.*`, `palette.danger.*`

Semantic surface tokens:

- `surface.canvas`
- `surface.page`
- `surface.card`
- `surface.elevated`
- `surface.brand`
- `surface.brand.subtle`
- `surface.accent`
- `surface.muted`
- `surface.inverse`

Semantic text tokens:

- `text.primary`
- `text.secondary`
- `text.muted`
- `text.inverse`
- `text.brand`
- `text.accent`
- `text.link`
- `text.danger`

Semantic border/stroke tokens:

- `border.subtle`
- `border.default`
- `border.strong`
- `border.brand`
- `stroke.illustration`
- `stroke.divider`

Interaction and focus tokens:

- `focus.ring`
- `selection.background`
- `selection.text`

Mode-sensitive color behavior:

- dark mode must invert or adapt surfaces and text;
- high contrast mode must raise contrast pairs;
- print mode should avoid low-contrast tints and unsupported transparency;
- digital mode can allow richer gradients and translucent accents.

### Accent And Texture Tokens

ABM artifacts often need branded texture without becoming generic decoration.
Phase C should model:

- `accent.primary`
- `accent.secondary`
- `accent.soft`
- `accent.bold`
- `texture.subtle`
- `texture.brand`
- `gradient.brand`
- `gradient.accent`
- `pattern.brand`

Implementation can begin with colors/effects/assets as the underlying carrier.
The product contract should still name these semantics so agents can use them.

### Typography Tokens

Typography must become role-based, not raw-size-based.

Required text roles:

- `type.display`
- `type.headline`
- `type.title`
- `type.subtitle`
- `type.body`
- `type.body.small`
- `type.caption`
- `type.eyebrow`
- `type.label`
- `type.cta`
- `type.stat`
- `type.legal`

Each typography token should cover:

- font family;
- font asset ref;
- fallback stack;
- font size;
- font weight;
- line height;
- letter spacing;
- text color token;
- max recommended lines;
- intended usage;
- medium/mode overrides.

Mode behavior:

- `large_text` should increase size and/or line height for key roles;
- `compact` can reduce spacing but should not make body copy unreadable;
- `print` may choose different sizes or weights than digital;
- `high_contrast` should select stronger color tokens.

Validation should flag:

- missing key type roles;
- type roles with invalid font assets;
- body text smaller than the product minimum;
- insufficient line height for body copy;
- unsupported font embedding for export contexts;
- unknown script coverage when the artifact language requires it.

### Spacing Tokens

Use a consistent scale:

- `space.0`
- `space.1`
- `space.2`
- `space.3`
- `space.4`
- `space.5`
- `space.6`
- `space.8`
- `space.10`
- `space.12`
- `space.16`

Also provide semantic aliases:

- `space.inline`
- `space.stack.tight`
- `space.stack.default`
- `space.stack.loose`
- `space.section`
- `space.page.margin`
- `space.card.padding`
- `space.button.padding.x`
- `space.button.padding.y`

The current scene only supports uniform padding token carriers. Phase C should
either:

- add per-edge padding token carriers, or
- explicitly defer per-edge token materialization and keep only uniform tokens.

For a product-grade design system, per-edge padding carriers are eventually
needed.

### Radius Tokens

Primitive scale:

- `radius.none`
- `radius.xs`
- `radius.sm`
- `radius.md`
- `radius.lg`
- `radius.xl`
- `radius.full`

Semantic aliases:

- `radius.card`
- `radius.button`
- `radius.badge`
- `radius.image`
- `radius.panel`

Validation should flag inconsistent use if strict branded mode is enabled.

### Stroke Tokens

Required:

- `stroke.width.hairline`
- `stroke.width.thin`
- `stroke.width.default`
- `stroke.width.firm`
- `stroke.width.bold`

Semantic aliases:

- `stroke.width.divider`
- `stroke.width.card`
- `stroke.width.illustration`
- `stroke.width.focus`

Phase C should keep stroke semantics compatible with the current `Stroke`
contract, while documenting future cap/join/position support.

### Opacity Tokens

Required:

- `opacity.disabled`
- `opacity.subtle`
- `opacity.muted`
- `opacity.overlay`
- `opacity.scrim`
- `opacity.emphasis`

Validation should prevent opacity tokens from becoming a substitute for proper
contrast. Low-opacity text should be warned in strict brand mode.

### Elevation, Shadow, And Effects

Required:

- `shadow.none`
- `shadow.sm`
- `shadow.md`
- `shadow.lg`
- `shadow.brand`
- `effect.blur.subtle`
- `effect.backdrop.subtle`

Phase C should model these in Brand Kit even if export support remains limited.
Adapters should warn when an effect cannot be faithfully exported.

### Assets, Logos, Illustrations, And Icons

Brand Kit should distinguish asset categories:

- primary logo;
- secondary logo;
- wordmark;
- mark;
- reversed logo;
- dark logo;
- light logo;
- app icon or favicon;
- custom brand illustrations;
- illustration fragments;
- icon set;
- texture/pattern assets;
- photography style examples.

Logo metadata should include:

- variant name;
- asset id;
- color mode;
- preferred width/height;
- minimum size;
- clearspace;
- allowed backgrounds;
- disallowed backgrounds;
- export/license constraints.

Illustration metadata should include:

- role;
- style tags;
- allowed contexts;
- preferred color tokens;
- source/provenance;
- license;
- whether it may be recolored;
- whether it may be cropped.

Agents should be able to ask for:

- "brand mark"
- "primary wordmark"
- "reversed logo for dark surface"
- "subtle background texture"
- "healthcare illustration style"

without guessing raw asset IDs.

### Brand Constraints And Guidance

The Brand Kit should include human-readable guidance:

- tone words;
- visual style notes;
- imagery rules;
- iconography rules;
- layout preferences;
- do/don't examples;
- accessibility notes;
- print constraints;
- legal restrictions;
- campaign-specific usage notes.

This is not only metadata. It is knowledge for agents and reviewers.

## Design-System Authoring Language

The existing `compile_styles_brand_kit` should evolve into a small
design-system authoring surface. It should remain deterministic and testable.

### Supported V1 `.styles` Concepts

Example target syntax:

```text
brand "Insight Health" id(brand_kit_insight_health) version(1)

mode theme(light,dark) default(light)
mode density(comfortable,compact) default(comfortable)
mode accessibility(standard,high_contrast,large_text) default(standard)
mode medium(digital,print) default(digital)

color primary = ramp(oklch(0.48,0.10,205), stops(50,100,200,300,400,500,600,700,800,900,950))
color neutral = ramp(oklch(0.36,0.02,230))
color accent = ramp(oklch(0.70,0.12,145))

alias surface.canvas = $neutral.950
alias surface.card = $neutral.900
alias surface.brand = $primary.700
alias text.primary = $neutral.50
alias text.secondary = $neutral.300
alias text.inverse = #ffffff
alias border.subtle = $neutral.800

spacing space = modular(0,4,8,12,16,24,32,48,64)
radius radius = tshirt(0,4,8,12,16,24,999)
stroke stroke.width = tshirt(0.5,1,1.5,2,3)
opacity opacity = scale(disabled:0.38,subtle:0.64,muted:0.72,overlay:0.88)

font brand = font("Inter", fallback("Arial","sans-serif"))

type headline = typography($font.brand,56,800,1.05,-0.01,$text.primary)
type body = typography($font.brand,22,500,1.35,0,$text.secondary)
type cta = typography($font.brand,20,800,1.0,0,$text.inverse)

logo primary = asset(account_logo, usage(primary), clearspace(16), min_size(48))
illustration healthcare_card = asset(healthcare_card_svg, role(spot_illustration), recolor(true))
```

The actual syntax can be smaller at first, but the plan should aim toward this
expressiveness.

### Compiler Responsibilities

The `.styles` compiler should:

- parse deterministic style declarations;
- generate primitive scales;
- generate semantic aliases;
- attach provenance;
- validate token key names;
- validate mode references;
- validate required semantic tokens;
- produce a `BrandKit`;
- return diagnostics with line numbers and fix hints.

### What It Should Not Do

The `.styles` compiler should not:

- scrape websites;
- call LLMs;
- mutate scenes directly;
- infer copyrighted assets;
- silently invent missing logo/font files;
- decide product approval status without user confirmation.

## Brand Kit Generation

Phase C should add a generator layer that produces a draft Brand Kit from seed
inputs.

### Generator Inputs

Supported now or soon:

- seed colors;
- logo asset;
- manually entered company name and tone;
- website URL summary;
- uploaded style guide text or PDF extraction;
- uploaded examples/screenshots;
- platform defaults.

### Generator Output

The generator should return:

- draft `BrandKit`;
- source map;
- confidence per token group;
- missing information report;
- suggested user review checklist;
- diagnostics for weak or incomplete token sets.

### Generator Strategy

Recommended staged approach:

1. **Seed generator**: deterministic generator from primary color, optional
   secondary/accent color, font family, and logo asset.
2. **Logo-aware generator**: derive color candidates from logo metadata or
   manually supplied sampled colors.
3. **Website/style-guide extractor**: use external retrieval/parsing to collect
   colors, fonts, logos, examples, and brand text, then feed the deterministic
   generator.
4. **Approval workflow**: generated kit is not treated as approved until a user
   or trusted workflow accepts it.

### Deterministic Core Function

Add a pure core function such as:

```text
generate_brand_kit(seed: BrandSeed) -> BrandGenerationReport
```

Where `BrandSeed` contains:

- brand name;
- primary color;
- optional secondary/accent colors;
- optional neutral color;
- preferred font families;
- logo asset refs;
- tone words;
- desired mode defaults;
- source/provenance.

The report contains:

- generated Brand Kit;
- diagnostics;
- warnings;
- missing inputs;
- confidence.

## Strict Brand Validation

Phase C should add product-grade brand validation beyond today's token
existence checks.

### Validation Categories

Required:

- missing required semantic tokens;
- missing key typography roles;
- unresolved token references;
- bare raw colors in strict branded mode;
- bare raw typography in strict branded mode;
- off-brand color distance from palette;
- unsupported logo usage;
- logo too small;
- logo on disallowed background;
- insufficient contrast for key text/surface pairs;
- weak body text readability;
- missing mode coverage for critical tokens;
- print mode using unsupported transparency/effects;
- template Brand Kit version mismatch.

### Off-Brand Diagnostics

Diagnostics should include:

- severity;
- code;
- subject page/node/token;
- offending value;
- suggested token;
- explanation;
- override policy.

Example:

```text
LUMB0804 node cta_bg fill #2463eb is not part of Brand Kit brand_kit_insight_health.
Use $surface.brand or $accent.primary, or mark this node with an approved override.
```

### Override Policy

Support intentional overrides with audit metadata:

- reason;
- user or agent;
- timestamp;
- affected node/token;
- whether override survives template finalization.

This can be a later API/editor concern, but the core diagnostic model should
reserve the concept.

## Brand Kit Versioning And Compatibility

Brand Kit versioning must be meaningful for template safety.

### Compatibility Checks

When a template references Brand Kit version `N` and a newer version exists,
the system should check:

- removed tokens;
- changed token type;
- changed semantic role;
- changed typography role metrics;
- removed logo/font assets;
- changed mode axes;
- changed export constraints;
- contrast regressions.

### Compatibility Result

Return:

- compatible;
- compatible with warnings;
- migration required;
- incompatible.

### Migration Support

Future migrations should support:

- token alias remap;
- missing token replacement;
- brand ref update operation;
- preview before/after comparison.

Phase C should at least define the compatibility contract and implement token
presence/type checks.

The core/helper bridge should expose this as a semantic operation instead of
making API or editor code diff Brand Kit JSON directly. The current helper
contract is:

```json
{
  "action": "compare_brand_kit_compatibility",
  "from": { "id": "brand_kit_old", "version": 1 },
  "to": { "id": "brand_kit_new", "version": 2 }
}
```

The response includes the core `BrandCompatibilityReport` under
`brand_compatibility`, with diagnostics and token changes suitable for API
persistence and editor display.

## Agent Knowledge And Brand-Aware Critique

Brand Kit maturity is not only core code. Agents need the right knowledge.

### New Knowledge Documents

Add focused agent knowledge docs:

- `knowledge/design-systems/token-taxonomy.md`
- `knowledge/design-systems/brand-generation.md`
- `knowledge/design-systems/brand-validation.md`
- `knowledge/design-systems/modes.md`
- `knowledge/design-systems/logo-and-assets.md`
- `knowledge/design-systems/brand-fit-critique.md`

These should be short, example-heavy, and aligned with the current DSL/scene
capabilities.

Current agent-runtime knowledge docs live under
`apps/agent_runtime/knowledge/design-systems/`. They are now included in the
primary knowledge retrieval list, and `design-systems` is a required task
category for design authoring so BrandKit guidance is loaded before DSL
generation and visual critique.

### Author Agent Behavior

The author agent should:

- prefer tokens over raw values when an effective Brand Kit exists;
- choose semantic tokens by role, not by visual guess;
- use typography roles for hierarchy;
- use spacing/radius tokens for layout rhythm;
- use correct logo/asset token semantics;
- avoid unsupported brand features unless the tool reports support.

### Critic Behavior

The visual critic should check:

- brand color fit;
- typography hierarchy fit;
- logo usage;
- off-brand raw colors;
- inconsistent spacing/radius;
- dark/light mode mismatch;
- print/digital mismatch;
- generic model-art appearance;
- whether the design would plausibly belong to the selected client.

Critique issues should map to product gap categories:

- design_system;
- typography;
- layout;
- preview_export;
- assets;
- agent_protocol.

## Editor And API Product Surfaces

Phase C should define the product surfaces, even if not all UI is built at once.

### API

Required API concepts:

- create Brand Kit;
- get Brand Kit;
- list Brand Kits;
- validate Brand Kit;
- generate Brand Kit from seed;
- update Brand Kit version;
- attach Brand Kit to document;
- run brand validation on document;
- get template compatibility report.

### Editor

Required editor concepts:

- selected Brand Kit visible in document inspector;
- mode selector;
- token picker for fills/type/spacing/radius;
- off-brand diagnostics panel;
- logo/asset variant picker;
- brand override note flow;
- before/after preview for Brand Kit version updates.

### Persistence

Store:

- Brand Kit JSON;
- Brand Kit version history;
- generated source/provenance;
- approval status;
- template compatibility reports;
- brand override audit entries.

Do not store renderer-specific interpretations as Brand Kit source of truth.

## Implementation Plan

### C0. Audit And Contract Lock

Deliverables:

- Compare existing `BrandKit` model against this plan.
- Create `docs/phase-c-brand-kit-design-system-maturity.md`.
- Create a Phase C memory file.
- Confirm which fields need schema additions versus knowledge/API additions.

Acceptance:

- Phase C scope is explicit.
- Existing token resolver behavior is not broken.

### C1. Rich Platform Default And Fixture Brand Kits

Deliverables:

- Expand `platform_default.json` into a realistic design system.
- Expand or replace `acme_full.json` with richer healthcare-oriented tokens.
- Add semantic tokens for surfaces, text, accents, borders, spacing, radius,
  stroke, opacity, typography, logos, and illustration assets.
- Add `medium` mode axis.
- Add tests for fixture validation and expected token coverage.

Acceptance:

- Platform default Brand Kit validates.
- Acme/healthcare fixture validates.
- Token coverage tests prove required semantic tokens exist.
- Existing preflight tests still pass.

### C2. Brand Kit Schema Extensions

Deliverables:

- Add approval status.
- Add compatibility policy metadata.
- Add richer asset categories where the current `BrandAssets` model is too
  thin.
- Add semantic role metadata where needed.
- Add mode requirement metadata if validation needs to know which modes are
  mandatory.

Acceptance:

- Old Brand Kit JSON remains backward-compatible through serde defaults.
- New fixture round-trips.
- Schema additions do not force renderer/API semantics into `lumen-core`.

### C3. Design-System Generator

Deliverables:

- Add `BrandSeed`.
- Add `BrandGenerationReport`.
- Add deterministic seed-based `generate_brand_kit`.
- Generate color ramps, semantic aliases, type roles, spacing/radius/stroke/
  opacity scales, and default constraints.
- Preserve provenance and confidence.
- Add generator tests.

Acceptance:

- A seed with primary color, font family, brand name, and logo ref produces a
  valid Brand Kit.
- Generated kit has required semantic tokens.
- Generated kit works in preflight with tokenized DSL.

### C4. `.styles` Compiler Expansion

Deliverables:

- Extend `compile_styles_brand_kit` toward a real authoring format.
- Add deterministic declarations for modes, ramps, aliases, typography, spacing,
  radius, stroke, opacity, fonts, logos, and illustrations.
- Add line-numbered diagnostics and fix hints.
- Add fixtures for valid and invalid `.styles`.

Acceptance:

- `.styles` can generate the same required semantic token coverage as the seed
  generator.
- Invalid token refs, invalid mode refs, and duplicate keys fail with clear
  diagnostics.

### C5. Strict Brand Validation And Off-Brand Diagnostics

Deliverables:

- Add required-token coverage validation.
- Add off-brand raw color diagnostics.
- Add typography role validation.
- Add logo usage validation.
- Add mode coverage validation.
- Add print/digital constraint validation.
- Add compatibility report skeleton.

Acceptance:

- A scene using raw colors in strict brand mode gets actionable diagnostics.
- A scene using unknown or removed tokens fails compatibility checks.
- A logo placed on a disallowed background gets a diagnostic where detectable.
- Diagnostics include suggested repairs or token alternatives.

### C6. Agent Knowledge And Brand-Aware Loop Integration

Deliverables:

- Add focused Brand Kit knowledge docs.
- Update agent knowledge retrieval to load brand docs for design tasks.
- Update author prompt to prefer semantic tokens.
- Update critic schema/categories to include brand-fit issues.
- Persist brand context used for each run.

Acceptance:

- Agent run traces show loaded brand knowledge.
- DSL generated by the agent uses Brand Kit tokens by default when available.
- Critic can reject off-brand output even if compile/preflight/export succeed.

### C7. API And Editor Integration

Deliverables:

- API routes for Brand Kit CRUD/generation/validation.
- Document brand attachment and mode selection routes.
- Editor inspector surface for current Brand Kit and mode.
- Token picker MVP for common style fields.
- Diagnostics UI for off-brand issues.

Acceptance:

- A user can attach a generated Brand Kit to a document.
- The editor shows the effective Brand Kit and mode.
- A strict brand validation report is visible without reading raw JSON.

Current implementation:

- API BrandKit routes exist for creation, generation, `.styles` compilation,
  validation, stored version lookup, document attachment, governance reports,
  and compatibility reports.
- API document persistence stores the normalized effective BrandMode separately
  from scene JSON, and preflight passes that mode into the Rust helper so
  `theme`, `density`, `accessibility`, and `medium` selections affect
  deterministic token resolution.
- The editor exposes a Brand Kit panel showing effective id/version,
  product-ready/approval state, medium selection, compact token counts, and a
  brand-governance action port.
- The editor local operation engine supports `update_document` for BrandKit and
  medium changes, matching the canonical operation surface.
- The node inspector provides token pickers for current scene fields with stable
  token carriers: text style token, layout gap/padding token, corner-radius
  token, and opacity token.
- The current editor still uses a local placeholder for live brand-governance
  execution. Wiring the panel to the HTTP API is integration/product work once
  the editor runs against the API server.

### C8. Conformance And Evaluation

Deliverables:

- Tokenized design fixtures for LinkedIn ad, one-pager section, email hero,
  and report cover.
- Brand variation tests: same DSL across multiple Brand Kits.
- Mode variation tests: light/dark, compact/comfortable, high contrast,
  large text, print/digital.
- Visual regression baselines where appropriate.
- Agent evaluation prompts requiring brand-specific output.

Acceptance:

- Same template resolves differently but coherently across Brand Kits.
- Mode switches preserve readability and export validity.
- Evaluation traces show fewer raw arbitrary styles and stronger brand fit.

Current core fixtures:

- `crates/lumen-core/fixtures/brand_templates/tokenized_linkedin_square.lumen`
- `crates/lumen-core/fixtures/brand_templates/tokenized_email_hero.lumen`
- `crates/lumen-core/fixtures/brand_templates/tokenized_one_pager_section.lumen`
- `crates/lumen-core/fixtures/brand_templates/tokenized_report_cover.lumen`

These fixtures intentionally use custom page dimensions and semantic BrandKit
tokens. They are concise enough to pass the current V1 slot-fit contract while
still exercising tokenized surfaces, type roles, spacing, radius, custom sizes,
and slot annotations. Richer personalized copy should be covered by the later
slot-runtime and targeted-repair phases.

## Implementation Detail Contract

This section turns the roadmap above into a concrete implementation contract.
The goal is to reduce ambiguity before the first Phase C branch starts.

### Module Ownership

`lumen-core` owns deterministic brand semantics:

- `BrandKit` schema.
- `BrandSeed` schema.
- design token taxonomy.
- `.styles` parser/compiler.
- deterministic Brand Kit generation from structured seed inputs.
- token validation and token resolution.
- strict brand validation and diagnostics.
- Brand Kit compatibility reports.

`lumen-core` must not own:

- website crawling;
- object storage;
- upload endpoints;
- editor UI;
- LLM extraction;
- approval workflow UI;
- workspace permissions.

`apps/api` owns platform persistence and HTTP boundaries:

- Brand Kit records;
- Brand Kit versions;
- generated kit drafts;
- document Brand Kit attachment;
- validation/generation routes;
- compatibility reports;
- approval state changes.

`apps/editor` owns human-facing controls:

- Brand Kit selector;
- mode selector;
- token picker;
- diagnostics panel;
- override notes;
- visual display of effective tokens.

`apps/agent_runtime` owns agent behavior:

- brand knowledge retrieval;
- token-first prompt rules;
- brand-fit critique instructions;
- trace persistence of effective brand context;
- choosing when to ask for generation, validation, or repair.

`crates/lumen-export` owns adapter-level fidelity:

- warning if a brand effect cannot export;
- respecting resolved colors/type/assets;
- not silently changing brand values.

### Files Expected To Change

Core branch `brand-kit/design-system-contract-v1`:

- `crates/lumen-core/src/brand.rs`
- `crates/lumen-core/src/preflight.rs`
- `crates/lumen-core/src/diagnostics.rs`
- `crates/lumen-core/fixtures/brand_kits/platform_default.json`
- `crates/lumen-core/fixtures/brand_kits/acme_full.json`
- `crates/lumen-core/tests/brand_tokens.rs`
- new `crates/lumen-core/tests/brand_validation.rs`
- new `crates/lumen-core/tests/brand_generation.rs`
- new `crates/lumen-core/fixtures/brand_kits/insight_health_generated.json`
- new `.styles` fixtures under `crates/lumen-core/fixtures/styles/`

Agent branch `agents/brand-aware-authoring-v0`:

- `apps/agent_runtime/lumen_deepagent/knowledge.py`
- `apps/agent_runtime/lumen_deepagent/prompts.py`
- `apps/agent_runtime/lumen_deepagent/schemas.py`
- `apps/agent_runtime/lumen_deepagent/loop.py`
- `apps/agent_runtime/knowledge/design-systems/*.md`
- `apps/agent_runtime/skills/lumen-dsl-design/SKILL.md`
- `apps/agent_runtime/skills/lumen-visual-review/SKILL.md`
- `apps/agent_runtime/tests/test_lumen_deepagent_runtime.py`

API branch `api/brand-kit-management-v0`:

- `apps/api/migrations/*`
- `apps/api/lumen_api/models.py`
- `apps/api/lumen_api/dto.py`
- `apps/api/lumen_api/database.py`
- `apps/api/lumen_api/main.py`
- `apps/api/tests/*`
- `crates/lumen-api-helper/src/main.rs`

Editor branch `editor/brand-kit-controls-v0`:

- `apps/editor/src/app/*`
- `apps/editor/src/engine/*`
- `apps/editor/src/types/*`
- `apps/editor/src/components/*`
- `apps/editor/src/__tests__/*`

### Required Token Coverage Contract

The following token keys are the minimum required semantic surface for a Brand
Kit to be treated as product-ready. The exact values may vary by brand and mode.

Required color tokens:

```text
palette.primary.50
palette.primary.100
palette.primary.200
palette.primary.300
palette.primary.400
palette.primary.500
palette.primary.600
palette.primary.700
palette.primary.800
palette.primary.900
palette.primary.950
palette.neutral.50
palette.neutral.100
palette.neutral.200
palette.neutral.300
palette.neutral.400
palette.neutral.500
palette.neutral.600
palette.neutral.700
palette.neutral.800
palette.neutral.900
palette.neutral.950
surface.canvas
surface.page
surface.card
surface.elevated
surface.brand
surface.brand.subtle
surface.accent
surface.muted
surface.inverse
text.primary
text.secondary
text.muted
text.inverse
text.brand
text.accent
border.subtle
border.default
border.strong
border.brand
focus.ring
```

Recommended color tokens:

```text
palette.secondary.*
palette.accent.*
palette.success.*
palette.warning.*
palette.danger.*
surface.success
surface.warning
surface.danger
text.success
text.warning
text.danger
selection.background
selection.text
gradient.brand
gradient.accent
texture.subtle
texture.brand
pattern.brand
```

Required typography tokens:

```text
type.display
type.headline
type.title
type.subtitle
type.body
type.body.small
type.caption
type.eyebrow
type.label
type.cta
type.stat
type.legal
```

Required spacing tokens:

```text
space.0
space.1
space.2
space.3
space.4
space.5
space.6
space.8
space.10
space.12
space.16
space.stack.tight
space.stack.default
space.stack.loose
space.section
space.page.margin
space.card.padding
```

Required radius tokens:

```text
radius.none
radius.xs
radius.sm
radius.md
radius.lg
radius.xl
radius.full
radius.card
radius.button
radius.badge
```

Required stroke-width tokens:

```text
stroke.width.hairline
stroke.width.thin
stroke.width.default
stroke.width.firm
stroke.width.bold
stroke.width.divider
stroke.width.card
stroke.width.focus
```

Required opacity tokens:

```text
opacity.disabled
opacity.subtle
opacity.muted
opacity.overlay
opacity.scrim
opacity.emphasis
```

Required asset semantics:

```text
logo.primary
logo.reversed
logo.mark
logo.wordmark
asset.illustration.primary
asset.texture.subtle
asset.icon.primary
```

If a Brand Kit does not have the underlying asset yet, it may include a
diagnostic placeholder with low confidence, but approved Brand Kits should not
ship with missing required asset references when those assets are used by a
template.

### Required Modes Contract

Every product-ready Brand Kit must declare these axes:

```text
theme: light | dark
density: comfortable | compact
accessibility: standard | high_contrast | large_text
medium: digital | print
```

Mode-specific values are mandatory for:

- `surface.canvas`
- `surface.page`
- `surface.card`
- `surface.brand`
- `text.primary`
- `text.secondary`
- `text.inverse`
- `border.default`
- `focus.ring`
- `type.headline`
- `type.body`
- `type.cta`

Mode-specific values are recommended for:

- `surface.accent`
- `surface.brand.subtle`
- `type.display`
- `type.caption`
- shadows/effects;
- logo variants.

Validation should allow a fallback only when:

- the token is not critical for accessibility or export;
- the fallback does not violate contrast;
- the compatibility policy permits fallback.

### Brand Validation Diagnostic Families

Reserve diagnostic families so future work does not create inconsistent codes.

Existing `LUMB` diagnostics should remain valid. Phase C can add:

```text
LUMB0800 missing required semantic token
LUMB0801 missing required typography role
LUMB0802 missing required mode axis
LUMB0803 missing required mode-specific token value
LUMB0804 off-brand raw color
LUMB0805 off-brand raw typography
LUMB0806 raw spacing/radius/stroke outside token scale
LUMB0807 insufficient brand contrast pair
LUMB0808 logo usage violates Brand Kit rules
LUMB0809 logo is below minimum size
LUMB0810 logo used on disallowed background
LUMB0811 print mode uses unsupported transparency/effect
LUMB0812 token role mismatch
LUMB0813 template references incompatible Brand Kit version
LUMB0814 token was removed in newer Brand Kit version
LUMB0815 token changed type in newer Brand Kit version
LUMB0816 missing provenance/confidence for generated token
LUMB0817 required brand asset is missing
LUMB0818 typography role is below readability threshold
LUMB0819 mode fallback used for critical token
```

Diagnostic severity rules:

- missing required token: error for approved kits, warning for draft kits;
- missing mode-specific value: error for critical tokens, warning otherwise;
- off-brand raw value: warning in normal mode, error in strict branded mode;
- logo too small: warning in draft, error in finalization/export;
- print violation: error for PDF/print export profiles;
- compatibility breakage: error when opening/finalizing with the newer kit.

Every diagnostic should include:

- code;
- severity;
- subject;
- message;
- suggested repair;
- token suggestion when available;
- override allowance where applicable.

### Brand Kit Generator Algorithm

The first generator should be deterministic. It does not need a model provider.

Input:

```text
BrandSeed {
  id,
  name,
  primary_color,
  secondary_color?,
  accent_color?,
  neutral_color?,
  preferred_fonts[],
  logo_refs[],
  tone_words[],
  source,
  default_modes,
}
```

Algorithm:

1. Validate seed:
   - brand name exists;
   - primary color is valid;
   - optional colors are valid;
   - font names are non-empty;
   - logo refs are valid IDs if present.
2. Convert seed colors to OKLCH.
3. Generate color ramps:
   - use perceptual lightness stops;
   - keep hue mostly stable for primary/accent;
   - reduce chroma at very light/dark stops;
   - ensure neutral ramp has low chroma;
   - emit CSS hex values in scene/export order.
4. Pick semantic colors:
   - light mode: light canvas/page, dark text, brand surface from primary 700;
   - dark mode: dark canvas/page, light text, brand surface from primary 300/400;
   - high contrast: raise text/background contrast;
   - print: avoid low-opacity/low-contrast surfaces.
5. Generate typography:
   - choose first preferred font or platform default;
   - create role scale for display/headline/title/subtitle/body/caption/cta;
   - set line heights and letter spacing by role;
   - attach font asset metadata.
6. Generate spacing/radius/stroke/opacity scales:
   - use a predictable base scale;
   - make compact mode overrides for spacing;
   - make large text mode overrides for typography.
7. Generate assets:
   - if logo refs exist, map primary/reversed/mark when possible;
   - otherwise add missing-asset diagnostics.
8. Generate constraints:
   - tone words;
   - gradient allowance;
   - imagery/iconography notes;
   - contrast pairs.
9. Validate generated kit.
10. Return report with diagnostics and confidence.

The generator must not silently produce an approved kit. Its first output should
be `generated_unreviewed`.

### `.styles` Authoring Grammar Targets

Phase C does not need to finish every grammar feature, but it should avoid
painting itself into a corner.

Minimum syntax to support:

```text
brand "Name" id(brand_kit_id) version(1)
mode theme(light,dark) default(light)
color primary = ramp(#005A66)
color primary = ramp(oklch(0.48,0.10,205))
color neutral = ramp(#1F2937,chroma(0.02))
alias surface.brand = $palette.primary.700
alias text.primary = $palette.neutral.950
spacing space = scale(0,4,8,12,16,24,32,48,64)
radius radius = scale(0,4,8,12,16,24,999)
stroke stroke.width = scale(0.5,1,1.5,2,3)
opacity opacity = named(disabled:0.38,subtle:0.64,muted:0.72)
font brand = font("Inter", fallback("Arial","sans-serif"))
type headline = typography($font.brand,56,800,1.05,-0.01,$text.primary)
logo primary = asset(account_logo, usage(primary), min_size(48), clearspace(16))
constraint tone = "clinical, calm, expert"
constraint gradients = allow
```

Required parser behavior:

- one declaration per line;
- comments allowed;
- deterministic line diagnostics;
- no silent ignored declarations;
- duplicate token keys are errors;
- aliases must point to existing tokens unless forward refs are explicitly
  supported;
- mode values must belong to declared mode axes;
- invalid colors/numbers/fonts fail with diagnostics.

### Brand Compatibility Contract

Add a report type:

```text
BrandCompatibilityReport {
  from: BrandKitRef,
  to: BrandKitRef,
  status: compatible | warning | migration_required | incompatible,
  diagnostics: Vec<Diagnostic>,
  token_changes: Vec<TokenChange>,
  suggested_operations: Vec<Operation>,
}
```

Token changes:

```text
added
removed
renamed
type_changed
role_changed
value_changed
mode_coverage_changed
asset_removed
font_license_changed
```

V1 compatibility only needs:

- token removed;
- token type changed;
- required mode removed;
- font/logo asset removed;
- typography role removed.

Later versions can add visual diffing.

### Current API Contract

The API exposes DTO envelopes and keeps all Brand Kit semantics in
`lumen-core` via `lumen-api-helper`.

Implemented routes:

- `POST /brand-kits`
  - stores an inline Brand Kit after helper validation;
  - rejects duplicate `{id, version}` pairs;
  - returns compact summary, authoring rules, and diagnostics.
- `GET /brand-kits`
  - lists the latest version of each Brand Kit by default;
  - `?all_versions=true` returns all stored versions.
- `GET /brand-kits/{brand_kit_id}`
  - returns the latest stored version plus full Brand Kit JSON.
- `GET /brand-kits/{brand_kit_id}/versions/{version}`
  - returns a specific immutable version.
- `POST /brand-kits/generate`
  - accepts a `BrandSeed`;
  - calls deterministic Rust generation;
  - optionally persists the generated Brand Kit.
- `POST /brand-kits/compile-styles`
  - accepts `.styles` source;
  - calls the Rust `.styles` compiler;
  - optionally persists the compiled Brand Kit.
- `POST /brand-kits/validate`
  - validates either an inline Brand Kit or stored Brand Kit reference;
  - returns a report DTO instead of forcing callers to inspect raw helper JSON.
- `POST /brand-kits/compatibility`
  - compares inline kits or stored references;
  - persists a compatibility report when both sides are stored Brand Kit
    versions.
- `GET /brand-compatibility-reports/{report_id}`
  - loads a stored compatibility report.
- `POST /documents/{document_id}/brand-kit`
  - attaches a stored Brand Kit to a draft document through a canonical
    `update_document` operation;
  - persists the selected effective Brand Kit as document context;
- can set the document `medium` from `mode.values.medium` while full
    BrandMode selection is persisted as API document metadata outside the scene
    JSON.
- `POST /documents/{document_id}/brand-governance`
  - runs strict/advisory/finalize governance against the effective or supplied
    Brand Kit;
  - stores the diagnostics under `brand_governance`.
- `POST /documents/{document_id}/preflight`
  - can now take `brand_kit_id` and `brand_kit_version` and resolve the stored
    Brand Kit before token/layout preflight.

Example: compile and store a `.styles` Brand Kit.

```json
{
  "source": "brand \"Insight Health\" id(brand_kit_insight_health) version(4)\n...",
  "brand_kit_id": "brand_kit_insight_health",
  "version": 4,
  "name": "Insight Health",
  "persist": true
}
```

Example: attach a stored Brand Kit to a document.

```json
{
  "brand_kit_id": "brand_kit_insight_health",
  "version": 4,
  "mode": {
    "values": {
      "theme": "light",
      "density": "comfortable",
      "accessibility": "standard",
      "medium": "digital"
    }
  }
}
```

Current scene-model boundary: the scene model only stores document `medium`,
not the full BrandMode axis object. The API persists the normalized effective
BrandMode as document metadata and passes it into preflight token resolution.
Adding full BrandMode selection to canonical scene JSON remains future
scene-schema work if we decide the mode selection itself should be part of the
portable scene contract.

### Editor UX Detail

Phase C editor UI can start small but should use final concepts.

Document inspector:

- selected Brand Kit name/id/version;
- approval state;
- mode selector;
- "validate brand" action;
- compatibility warning if newer Brand Kit exists.

Node inspector:

- fill token picker;
- text style token picker;
- spacing/radius/stroke token pickers where supported;
- display resolved value beside token;
- show whether field is tokenized or raw.

Diagnostics panel:

- filter by brand/layout/text/export;
- show affected node/page;
- show suggested token;
- allow "apply suggested token" when it can be represented as an operation;
- allow "record override" only for warnings and with a reason.

Asset panel:

- logo variants;
- illustration assets;
- texture/pattern assets;
- allowed background hints.

### Agent Prompt And Knowledge Detail

Agent authoring should receive a compact Brand Kit summary:

```text
Brand: Insight Health
Version: 1
Mode: theme.light, density.comfortable, accessibility.standard, medium.digital
Voice: clinical, calm, expert
Primary surfaces: $surface.canvas, $surface.card, $surface.brand
Text roles: $type.headline, $type.body, $type.cta
Spacing: use $space.card.padding, $space.stack.default, $space.section
Radius: use $radius.card and $radius.button
Logo: use $logo.primary on light surfaces, $logo.reversed on dark brand surfaces
Avoid: raw hex colors unless explicitly requested
```

Agent authoring rules:

- use `style($type.*)` for text;
- use `fill($surface.*)` and `stroke($border.*,$stroke.width.*)`;
- use `g($space.*)`, `pad($space.*)`, `rd($radius.*)`;
- use brand asset tokens or asset refs for logos/illustrations;
- do not invent token names;
- if a required token is missing, ask for generation/validation rather than
  guessing raw values.

Critic rules:

- compare visible colors against Brand Kit surfaces/accent roles;
- flag raw colors on major surfaces;
- flag typography that ignores role hierarchy;
- flag logo misuse;
- flag inconsistent radius/spacing;
- flag mode mismatch;
- classify whether the issue is brand, layout, text, asset, or export.

### Data Migration And Backward Compatibility

All Phase C schema additions must use serde defaults so older scenes and older
Brand Kits still load.

Compatibility rules:

- old Brand Kits without `approval_status` deserialize as `draft`;
- old Brand Kits without `medium` mode get default `digital`;
- old tokens without detailed role metadata still validate under legacy
  strictness but not under `product_ready`;
- existing scene token refs do not change names unless a migration function is
  provided;
- `platform_default.json` should be updated in one commit with tests.

### Risk Register

Risk: token taxonomy becomes too large for agents.

- Mitigation: retrieve only task-relevant summaries and examples; do not paste
  full Brand Kit JSON into every prompt.

Risk: generated Brand Kits look plausible but are off-brand.

- Mitigation: keep generated kits unapproved, preserve confidence, require
  validation and user review.

Risk: strict brand validation blocks useful exploration.

- Mitigation: support draft mode warnings and finalization/export strictness.

Risk: schema additions break existing fixtures.

- Mitigation: serde defaults, fixture round-trip tests, migration tests.

Risk: color distance/off-brand checks overreach.

- Mitigation: start with raw-value and required-token diagnostics; add
  perceptual distance thresholds only after fixtures prove useful.

Risk: agents invent nonexistent tokens.

- Mitigation: brand summary must include allowed token names; validation returns
  token suggestions.

### Phase C Exit Review Checklist

Before merging Phase C integration, verify:

- `platform_default.json` is no longer minimal.
- at least one client Brand Kit fixture is realistic and mode-aware.
- generator output validates and is not marked approved by default.
- `.styles` can express the required taxonomy.
- strict brand validation catches raw major surfaces and raw text styles.
- tokenized DSL fixtures use semantic tokens.
- visual output differs meaningfully by Brand Kit but preserves layout.
- run traces record Brand Kit id/version/mode.
- agent knowledge includes token taxonomy and brand-fit rules.
- API/editor surfaces use Brand Kit refs, not copied token maps.
- all old fixtures and operation logs still deserialize.

## Suggested Branching

Phase C is large enough to split, but small enough that the first branch should
establish the contract.

Implementation note: the current `brand-kit/design-system-contract-v1` branch
intentionally absorbed the first useful slices of the generator, `.styles`, API,
editor, agent-knowledge, and evaluation work so the full BrandKit contract could
be proven end-to-end before further branching. Future work should still respect
the ownership boundaries below and avoid adding alternate brand semantics in
API/editor/agent code.

Recommended order:

1. `brand-kit/design-system-contract-v1`
   - schema additions;
   - token taxonomy;
   - rich platform default fixture;
   - validation coverage.

2. `brand-kit/generator-v0`
   - `BrandSeed`;
   - deterministic generated Brand Kit;
   - `.styles` expansion.

3. `agents/brand-aware-authoring-v0`
   - knowledge docs;
   - author/critic prompt updates;
   - brand-fit critique categories.

4. `api/brand-kit-management-v0`
   - persistence/API routes;
   - validation/generation endpoints;
   - compatibility report storage.

5. `editor/brand-kit-controls-v0`
   - Brand Kit selector;
   - mode selector;
   - token picker;
   - off-brand diagnostics.

6. `integration/phase-c-brand-system`
   - cross-branch proof that generation, authoring, preflight, export, API, and
     editor all agree on the Brand Kit contract.

If speed matters, start with only the first two branches and keep API/editor
surfaces minimal until core behavior is proven.

## Required Tests

Core tests:

- Brand Kit fixtures validate.
- Old Brand Kit JSON remains backward-compatible.
- Generated Brand Kit validates.
- `.styles` fixtures compile or fail with expected diagnostics.
- Required semantic token coverage is enforced.
- Mode resolution works for `theme`, `density`, `accessibility`, and `medium`.
- Strict mode catches raw/off-brand style values.
- Token resolution still materializes scene operations deterministically.
- Compatibility reports catch removed/changed tokens.

Agent/runtime tests:

- Knowledge selection includes brand docs for brand-aligned artifact prompts.
- Author output uses tokens when a Brand Kit is supplied.
- Critic flags off-brand raw colors and weak brand fit.
- Run trace records effective Brand Kit id/version/mode.

API/editor tests:

- Brand Kit create/load/validate round trips.
- Document Brand Kit attachment persists.
- Mode selection persists.
- Off-brand diagnostics are returned through API.
- Editor token picker emits canonical operations.

Conformance tests:

- One tokenized DSL fixture renders acceptably with platform default and one
  client Brand Kit.
- The same fixture renders in light/dark and print/digital modes without
  unresolved tokens or severe contrast errors.

## Current Core Branch Status

As of `brand-kit/design-system-contract-v1`, the core `lumen-core` contract now
implements the first production-facing Brand Kit foundation:

- product-ready token coverage constants for colors, typography, spacing,
  radius, stroke width, opacity, and brand assets;
- `BrandApprovalStatus` and `BrandCompatibilityPolicy` metadata with
  backward-compatible serde defaults;
- required mode axes including `theme`, `density`, `accessibility`, and
  `medium`;
- preflight token resolution derives Brand Kit `medium` mode from scene medium
  when no explicit token-resolution mode is supplied (`print`/`direct_mail`
  select `medium.print`; `digital`/`email`/`ad` select `medium.digital`);
- richer platform default completion at runtime;
- product-ready validation, strict scene brand-governance diagnostics, and
  basic Brand Kit compatibility reporting;
- logo usage governance that detects Brand Kit logo variants placed on
  disallowed tokenized backgrounds and returns actionable diagnostics;
- logo minimum-size governance that detects Brand Kit logo variants rendered
  below their configured `min_size`, using computed geometry when available and
  fixed node dimensions otherwise;
- print/direct-mail governance that flags low-opacity node transparency,
  including opacity-token-driven transparency, as `LUMB0811` before print/PDF
  acceptance;
- compact `BrandKitAuthoringSummary` output for agent/API/editor consumers,
  including effective default mode, product-ready status, semantic token lists,
  asset tokens, tone/imagery/iconography guidance, and authoring rules;
- stricter scene brand-governance diagnostics for raw fills, strokes, corner
  radii, opacity, auto-layout gap/padding, and text styles, with repair hints
  that point to concrete Brand Kit tokens;
- deterministic `BrandSeed -> BrandGenerationReport` generation for draft,
  generated-unreviewed Brand Kits;
- expanded `.styles` authoring support for `brand`, `mode`, color ramps,
  semantic aliases, numeric scales, typography roles, fonts, logos, and brand
  constraints;
- `.styles` brand asset declarations for illustrations, icons, textures,
  patterns, images, and generic assets, lowering into `BrandAssets.images`,
  `AssetTokenValue::Asset`, style tags, allowed contexts, preferred color
  tokens, recolor/crop policy, MIME type, license, and provenance metadata;
- upgraded `acme_full.json` healthcare Brand Kit fixture with product-ready
  mode axes, semantic token coverage, approval status, logo/asset tokens,
  typography roles, and governance-ready constraints;
- `.styles` fixtures for a valid Insight Health healthcare Brand Kit plus
  invalid duplicate-token and invalid-mode cases;
- `lumen-api-helper` bridge actions for product-ready Brand Kit validation,
  `.styles` compilation, deterministic Brand Kit generation, authoring summary
  output, and scene brand-governance validation;
- HTTP API routes and persistence DTOs for Brand Kit CRUD, `.styles`
  compilation, deterministic generation, validation, document attachment,
  preflight with stored Brand Kits, scene brand-governance reports, and
  compatibility reports;
- API document metadata now persists normalized effective BrandMode values and
  uses them as preflight token-resolution overrides, while keeping canonical
  scene JSON limited to its existing `medium` field;
- agent knowledge documents for token taxonomy, brand generation, brand
  validation, modes, logo/assets, and brand-fit critique, with runtime retrieval
  categories updated so branded design tasks load design-system guidance;
- agent preflight and final run traces now persist normalized effective BrandKit
  context: source, id, version, name, and mode values, including scene-medium
  overrides that match core preflight behavior;
- agent loop tests now prove a structured `brand_fit` visual critique blocks
  acceptance, receives effective BrandKit context through the scene summary, and
  passes the critique verbatim into the next repair request;
- trace evaluation summarizes BrandKit version and mode distributions across
  runs so product/design quality can be measured against the design-system
  context used;
- SVG export conformance now includes a Phase C tokenized LinkedIn-square
  fixture after BrandKit preflight, proving custom dimensions, slot metadata,
  and resolved BrandKit paints survive into the export adapter without
  unresolved-token diagnostics;
- tests proving generated and `.styles` Brand Kits can reach product-ready
  coverage, drive tokenized preflight, round-trip through the helper surface,
  and persist through the API surface used by Python orchestration.

Still outside this core branch:

- website/style-guide extraction into `BrandSeed`;
- approval workflows and user review UI;
- API-backed editor BrandKit loading, live governance execution, compatibility
  warning fetches, and apply-suggested-token actions;
- full visual conformance across multiple artifacts and Brand Kits.

## Deferred Work

These are important, but should not block Phase C's first useful version:

- full website crawler for brand extraction;
- production asset upload/security pipeline;
- full PDF style-guide parser;
- exact font detection from websites;
- final legal review workflow for fonts/assets;
- full Figma style import/export;
- advanced generative illustration systems;
- complete design token parity with W3C Design Tokens spec;
- perfect cross-renderer color management.

## Completion Criteria

Phase C should be considered complete when:

- Lumen has at least one rich platform default Brand Kit and one rich client
  fixture Brand Kit.
- A seed generator can produce a valid draft Brand Kit with semantic token
  coverage.
- `.styles` can author a usable Brand Kit with modes and semantic tokens.
- Tokenized DSL can generate a branded artifact without raw styling guesses.
- Strict brand validation catches off-brand output with actionable diagnostics.
- Agent runs load brand knowledge and use tokens by default.
- Brand Kit id/version/mode is persisted in run traces and document metadata.
- Compatibility checks can detect basic token deletion/type-change breakage.
- Tests prove token resolution, preflight, export, and agent guidance still work
  with the richer Brand Kit model.
