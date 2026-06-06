# ABM Design Engine - Temporary Technical Spec Draft

> Temporary discussion draft. This is not an implementation contract yet. It reframes the current design-tool work as the Design Engine subsystem inside a larger AI-native ABM orchestration platform.

| Field | Value |
|---|---|
| Status | Temporary draft for discussion |
| Date | 2026-06-04 |
| Scope | Design Engine only |
| Out of scope | Account discovery, enrichment, research, content drafting, bulk personalization, campaign publishing |
| Related docs | `Brilliant-Rebuild-Technical-Spec.md`, `Brilliant-Reverse-Engineering-Report.md` |

---

## 1. Product Context

The overall product is an AI-powered ABM orchestration platform. In the full product, agents help discover target accounts, enrich account/contact data, perform deep research, draft personalized campaign content, generate brand-aligned campaign artifacts, scale those artifacts across contacts/accounts, and export or publish the resulting assets.

This document covers only one subsystem of that platform:

**The Design Engine**: an agent-powered artifact design system that can generate, edit, validate, preview, and export brand-aligned design artifacts.

The Design Engine is not a standalone Figma competitor. It is a design component that must eventually plug into downstream ABM workflows where finalized templates are duplicated and populated with account/contact-specific content.

That future downstream workflow is not part of the current sprint, but the Design Engine must preserve the right semantic hooks now so we do not have to redesign the scene model later.

---

## 2. Current Sprint Scope

### 2.1 In scope

- Generate a design artifact from a prompt.
- Optionally use a brand guide or brand kit as input.
- Support a minimal but usable editor for human tweaks.
- Represent artifacts as structured, replayable design documents.
- Support AI agents that can inspect, modify, and self-review designs.
- Support page/artboard-based artifacts such as letters, reports, brochures, mailers, and ads.
- Export artifacts to common formats: SVG, PNG, and PDF.
- Preserve semantic content slots that future ABM personalization can bind to.

### 2.2 Out of scope for current sprint

- Discovering target accounts.
- Finding contacts.
- Enriching accounts/contacts through Clay or similar systems.
- Running account/contact research agents.
- Drafting personalized ABM copy from research.
- Bulk-generating thousands of personalized variants.
- Publishing campaign assets to ad/email/direct-mail channels.
- Multi-user real-time collaboration.
- Full Figma replacement functionality.

### 2.3 Critical future-proofing that is in scope

Even though bulk personalization is out of scope, the design artifact must be able to answer:

- Which parts of this design are placeholders?
- What content type does each placeholder expect?
- How should inserted content behave if it is too long or too short?
- Which visual nodes belong to the same semantic field?
- Which fields are safe for downstream automation to replace?
- Which fields are locked after template finalization?
- How can a future workflow create many copies from this template without guessing from node names?

This means **semantic slots are part of the Design Engine MVP**, even if slot filling at scale is not.

---

## 3. Product Principle

The Design Engine should generate **campaign artifact templates**, not just static drawings.

A campaign artifact template has:

- Visual structure.
- Brand styling.
- Page/artboard configuration.
- Export settings.
- Editable nodes.
- Semantic slots for future personalized content.
- A stable revision history.

The key difference from a generic design editor is that a template must remain machine-readable after it looks visually complete.

---

## 4. Design Lifecycle

### 4.1 Draft creation

Inputs:

- User prompt.
- Artifact type, such as A4 letter, envelope, brochure, report, LinkedIn ad, banner, or one-off custom size, landing_pages.
- Optional brand kit or uploaded style guide.
- Optional target medium constraints, such as print, web, email, ad, or direct mail.
- Optional content schema, such as "needs doctor name, hospital name, specialty, CTA, logo, one quote".

Output:

- A draft design document with pages/artboards, nodes, layout, styles, and semantic slots.

### 4.2 Human/agent iteration

The user may:

- Edit visually in the minimal editor.
- Ask an agent to revise the layout, tone, styling, or content placeholders.
- Adjust page size, export settings, brand tokens, and slot behavior.

All changes become structured operations against the same scene model.

### 4.3 Template finalization

When the user finalizes the artifact, the system creates a versioned **template revision**.

Finalization means:

- The artifact is approved as a reusable master template.
- Slot definitions are validated.
- Export settings are validated.
- The template revision is stable and can be referenced by downstream ABM workflows.

Finalization does not have to mean that the design can never be edited again. Instead, edits after finalization should create a new draft or a new template revision.

### 4.4 Future personalization phase

Out of current scope, but important for architecture:

- A future workflow will take a finalized template revision.
- It will bind account/contact/content data to the template's semantic slots.
- It will produce many personalized artifact instances.
- Each instance may optionally be manually edited.
- Instances may be exported in bulk.

The current Design Engine should not implement this workflow, but it must make it possible.

---

## 5. Core Architecture

### 5.1 Recommended architecture stance

Keep the strongest idea from Brilliant:

**One deterministic design engine should be used by agents, the editor, export, and future automation.**

The current stance is:

- Build the compiler/scene/operation core in Rust from day one.
- Keep that core platform-independent and compatible with both native and `wasm32`.
- Use the native/server build first through the backend/agent/export workflows.
- Do not force the full browser editor or renderer into WASM in V1.
- Use React/TypeScript for the editor shell.
- Use React-Konva/Konva for V1 canvas editing and editor-level interactions.
- Keep the rendering/editor adapter replaceable so React-Konva can later be swapped for Vello/WebGPU, SVG-native rendering, or another precise renderer.
- Python/FastAPI can orchestrate agents and platform API, but should not own design semantics.

### 5.2 Why this still makes sense

The future ABM workflow will depend on repeatable template generation and slot filling. If the browser, agent service, and export service interpret a document differently, scaled assets will break in hard-to-debug ways.

The engine should therefore be deterministic and shared at the semantic layer.

The critical shared layer is:

- DSL parser.
- Diagnostics.
- Scene model.
- Operation types.
- Operation applier.
- Slot model and validation.
- Brand token resolver.
- Canonical serialization.
- Basic layout rules.

The critical shared layer is not necessarily:

- Browser input handling.
- Canvas widget implementation.
- WebGPU renderer.
- Server PDF implementation.
- Persistence adapters.
- Asset storage.

Those belong behind adapters.

### 5.3 What should not be overbuilt now

The first implementation should avoid treating the entire backend platform as required for the Design Engine MVP.

For the current sprint, the minimum viable stack can be:

- Rust `lumen-core` package that compiles for native and `wasm32`.
- Native wrapper used by backend/agents.
- Browser editor shell in React/TypeScript.
- React-Konva canvas adapter for V1 editing.
- Local or simple server persistence.
- Basic agent orchestration.
- SVG/PNG/PDF export path.

Full account/contact platform integration can be added later.

### 5.4 Recommended package boundaries

```text
crates/
|-- lumen-core/
|   |-- dsl
|   |-- diagnostics
|   |-- scene
|   |-- operations
|   |-- slots
|   |-- tokens
|   `-- layout
|
|-- lumen-wasm/
|   `-- thin browser wrapper around lumen-core
|
|-- lumen-python/
|   `-- thin PyO3 wrapper around lumen-core
|
`-- lumen-export/
    `-- server export adapters, using the core scene model

apps/
`-- editor/
    |-- React shell
    |-- React-Konva canvas adapter
    `-- future renderer adapter boundary
```

The golden rule:

```text
lumen-core knows nothing about:
  React
  Konva
  FastAPI
  databases
  WebGPU
  browser storage
  S3
  HTTP
```

This gives us future compatibility with a richer Rust/WASM browser engine without forcing the hardest dual-runtime rendering problems into V1.

---

## 6. Canonical Source Of Truth

The previous draft has ambiguity between DSL, scene JSON, and operation log. This draft recommends:

### 6.1 Canonical runtime model

The **Scene** is the canonical in-memory model.

It contains:

- Document metadata.
- Pages/artboards.
- Node graph.
- Layout constraints.
- Style/token references.
- Slot metadata.
- Export settings.

### 6.2 Canonical history model

The **Operation Log** is the canonical history model.

Operations mutate the scene. They support:

- Undo/redo.
- Replay.
- Snapshots.
- Audit.
- Future collaboration.

The operation log should not be the mechanism for bulk personalized-instance derivation. At scale, personalized instances should derive from:

```text
finalized template snapshot + binding set + export settings
```

not from replaying the template's entire historical operation log for every recipient.

### 6.3 DSL role

The DSL is an agent-friendly and human-inspectable authoring format.

It should not be the only source of truth. It should be treated as:

- An import format.
- An export/debug format.
- An agent write format.
- A compact patch format for generated design changes.

The engine must be able to compile DSL into scene operations. The engine may also pretty-print a scene back to DSL, but this does not mean the DSL owns all state.

This matters because slot metadata, export settings, page settings, and future ABM binding metadata may not fit cleanly into a terse one-line visual DSL.

---

## 7. Conceptual Domain Model

This is conceptual only, not a database schema.

### 7.1 Workspace

A workspace represents a client's environment or internal project space.

It can own:

- Brand kits.
- Design documents.
- Assets.
- Template revisions.
- Future campaign objects.

### 7.2 Brand Kit

A Brand Kit is a versioned collection of brand inputs and generated tokens.

It can include:

- Logo assets.
- Color palette.
- Typography.
- Spacing and radius scales.
- Tone/style notes.
- Approved imagery or iconography.
- Extracted tokens from uploaded style guides.
- Source provenance, such as manual input, uploaded PDF, website scrape, or default template.

The design engine consumes a resolved Brand Kit, not arbitrary raw brand files during every compile.

### 7.3 Design Document

A Design Document is the editable working file.

It contains:

- One or more pages/artboards.
- Scene nodes.
- Design tokens or brand kit reference.
- Semantic slots.
- Export settings.
- Draft/finalization status.
- Operation history.

### 7.4 Page / Artboard

A Page or Artboard is an exportable design surface.

Examples:

- A4 letter page.
- US Letter page.
- Envelope front.
- 4-page brochure page.
- LinkedIn ad creative.
- Email header.

The model should allow multiple pages/artboards in one design document.

### 7.5 Node

A Node is a visual object.

Examples:

- Frame.
- Group.
- Text.
- Rectangle.
- Ellipse.
- Line.
- Vector path.
- Image.
- Auto-layout container.
- Component instance.

Nodes should be visually precise, but also able to carry semantic metadata.

### 7.6 Slot

A Slot is a stable semantic placeholder for future content mapping.

Examples:

- `contact.full_name`
- `contact.title`
- `account.name`
- `account.logo`
- `account.industry`
- `campaign.cta`
- `research.key_insight`
- `offer.primary_message`
- `sender.signature`

A slot may be represented by one node or multiple nodes. For example, a "hospital profile" slot group might include a logo image, hospital name text, specialty text, and location text.

### 7.7 Template Revision

A Template Revision is a finalized, reusable version of a design document.

It should be immutable or append-only once finalized. New edits create a new draft or a new revision.

Future ABM workflows should reference template revisions, not mutable drafts.

### 7.8 Personalized Instance

Out of current scope, but conceptually important.

A Personalized Instance is a copy derived from a finalized template revision plus a content/data binding set.

The current Design Engine should not implement large-scale instance generation, but the template model should be compatible with it.

---

## 8. Scene Model Requirements

The scene model should support:

- Multiple pages/artboards.
- Stable node IDs independent of display names.
- Stable page IDs.
- Stable slot IDs.
- Parent-child tree structure.
- Z-order.
- Layout constraints.
- Design token references.
- Export metadata.
- Derived/computed layout bounds.
- Human-readable labels for editor UX.
- Machine-readable metadata for downstream automation.

The model should separate:

- Visual identity: what appears on the canvas.
- Semantic identity: what business/content role it plays.
- Layout behavior: how it reacts to size/content changes.
- Export behavior: how it is emitted into SVG/PNG/PDF/Figma bridge.

---

## 9. Slot Model Requirements

Slots are the most important addition to the previous spec.

### 9.1 Slot fields, conceptually

A slot should carry:

- Stable key.
- Human label.
- Content type.
- Scope, such as document, page, group, or node.
- Bound node IDs.
- Required/optional flag.
- Default placeholder value.
- Overflow behavior.
- Formatting constraints.
- Cardinality constraints.
- Conditional visibility rules.
- Repeater behavior, if the slot represents a variable-count region.
- Validation fixtures, such as realistic samples, max-length examples, and worst-case content.
- Editability constraints.
- Validation rules.
- Image fit/crop policy for image-like slots.
- Future binding hints.

### 9.2 Content types

Initial slot content types:

- Text short.
- Text long.
- Rich text limited.
- Number/stat.
- Date.
- Image.
- Logo.
- URL/QR.
- List.
- Repeater group.
- Table-like data, possibly post-MVP.

`List` means a content value that renders inside one existing region. `Repeater group` means the design may clone a sub-layout for N items and reflow the surrounding layout. These are different and must not be conflated.

### 9.3 Overflow behavior

For future personalization, the template must define what happens when replacement content does not fit.

Possible policies:

- Shrink font within min/max bounds.
- Wrap text.
- Clip text.
- Truncate with ellipsis.
- Expand container.
- Trigger validation error.
- Ask agent to repair layout.

This is essential for ABM artifacts because different accounts/contacts will have different name lengths, titles, company names, quotes, and research insights.

Image/logo slots need their own equivalent policies:

- Fit contain.
- Fit cover.
- Crop with focal point.
- Preserve transparent background.
- Enforce minimum DPI for print.
- Enforce aspect-ratio constraints.
- Reject if too low resolution.

### 9.4 Conditional and repeated regions

ABM artifacts frequently need conditional and variable-count content.

Examples:

- Show a quote block only if a quote exists.
- Show an industry-specific module only when `account.industry == healthcare`.
- Render exactly three key insights if available.
- Render one service card per recommended service.
- Hide an empty location field without leaving a visual gap.

These behaviors affect layout, not just data binding. The slot model should therefore support:

- Conditional presence.
- Fallback content.
- Empty-state behavior.
- Repeated child template regions.
- Min/max item counts.
- Reflow policy after hiding or repeating regions.

The MVP can implement only simple cases, but the model should not block these needs.

### 9.5 Slot validation

Before finalization, the engine should validate:

- Every required slot has a placeholder.
- Slot keys are unique and stable.
- Slot content types are known.
- Bound nodes exist.
- Slot overflow behavior is defined.
- Conditional slots have defined empty/fallback behavior.
- Repeater slots have min/max item counts and a repeatable sub-layout.
- Text slots have sample fixtures or max-length constraints where possible.
- Image/logo slots have fit/crop/focal-point/min-DPI policies where relevant.
- Export-critical slots fit within safe areas.
- Placeholder copy does not accidentally remain unbound unless intentionally allowed.

---

## 10. DSL Recommendation

### 10.1 Keep a DSL, but do not make it carry everything

The terse one-line DSL is valuable for agents. It should be kept.

But the DSL should be limited to what it is good at:

- Creating visual structure.
- Making targeted edits.
- Describing layout.
- Referencing tokens.
- Assigning lightweight slot marks in a compact way.

The full scene JSON should remain available for complete fidelity.

Rich configuration should live in the scene/document metadata, not be duplicated in the DSL:

- Brand Kit configuration.
- Export profiles.
- Full page/artboard settings.
- Slot validation fixtures.
- Conditional/repeater behavior.
- Font licensing metadata.
- Future ABM binding metadata.

This prevents two divergent representations of the same configuration.

### 10.2 Add slot annotations

The DSL needs a lightweight way to mark placeholders.

Possible syntax to discuss:

```text
name t("Dr. Priya Sharma","Inter",18,600,left) slot(contact.full_name)
hospital t("Apollo Neuroscience Center","Inter",24,700,left) slot(account.name)
logo image(src=$asset.logo) slot(account.logo)
cta t("Schedule a consultation","Inter",16,700,center) slot(campaign.cta)
```

Alternative:

```text
name t("Dr. Priya Sharma","Inter",18,600,left) meta(slot="contact.full_name")
```

The richer slot definition should live in scene metadata:

```json
{
  "key": "contact.full_name",
  "type": "text_short",
  "required": true,
  "overflow": "shrink",
  "samples": ["Dr. Priya Sharma", "Dr. Maximilian Alexander Whitmore"],
  "bound_nodes": ["node_123"]
}
```

I prefer a generic `slot(...)` or `meta(...)` annotation rather than encoding slots into node names.

### 10.3 Keep page/artboard config mostly out of DSL

The previous draft has a single root. We need page/artboard primitives.

The DSL may need a minimal way to create or reference a page:

```text
page letter
  header fr ...
```

But rich page settings should live in document metadata:

```json
{
  "page_id": "letter",
  "preset": "A4",
  "orientation": "portrait",
  "medium": "print",
  "bleed_mm": 3,
  "safe_margin_mm": 12
}
```

Exact grammar can be decided later. The architectural requirement is clear: one document can contain multiple exportable surfaces.

### 10.4 Keep artifact intent metadata in document metadata

A design artifact should know what it is for.

This helps agents and future workflows make better decisions, but the metadata should live in the scene/document model rather than in DSL directives.

Examples:

- Artifact type.
- Medium.
- Audience.
- Brand Kit ref.
- Export profile.
- Intended downstream workflow.

### 10.5 Indentation fragility and agent authoring

Indentation-based DSLs are compact but fragile under LLM authorship. A single indentation error can reparent a subtree.

Mitigations:

- Use structured operations as the primary agent patching surface after initial generation.
- Keep DSL blocks small and validated incrementally.
- Consider explicit parent references for patch operations.
- Consider a non-indentation JSON patch format for complex edits.
- Keep cascade-halt diagnostics so the agent can repair failed blocks.

---

## 11. Brand Kit System

### 11.1 Why Brand Kit is first-class

The ABM platform will often need to generate artifacts in a client's brand. Sometimes the client provides a brand guide. Sometimes they provide only a website or logo. Sometimes no brand guide exists.

The Design Engine should not treat brand styling as random prompt text. It should consume a normalized Brand Kit.

### 11.2 Brand Kit inputs

Possible inputs:

- Uploaded brand PDF.
- Uploaded style guide images.
- Website URL.
- Logo file.
- Manually entered colors/fonts.
- Existing platform defaults.
- Agent-extracted brand summary.

### 11.3 Brand Kit outputs

The Brand Kit compiler should output:

- Color tokens.
- Typography tokens.
- Spacing/radius tokens.
- Logo asset refs.
- Approved visual style notes.
- Constraints such as "do not use gradients" or "prefer blue/white clinical tone".
- Font source and licensing metadata.
- Font embedding/subsetting permissions for PDF/export.
- Script/language coverage for brand fonts.
- Provenance and confidence.

### 11.4 Versioning

Brand Kits must be versioned.

A design document should reference the Brand Kit version used to generate it. If the brand kit changes later, the document should not silently change unless the user requests a rebase/retheme operation.

---

## 12. Layout Requirements

The Design Engine needs layout that works for generated, edited, and later personalized content.

### 12.1 Taffy is only one layer

Using Taffy as the layout engine is a reasonable architectural decision because it gives a DOM-less Rust layout implementation compatible with WASM/server use.

But Taffy solves box layout. It does not solve the full document-layout problem.

Separate subsystems are needed for:

- Text shaping.
- Font metrics.
- Line breaking.
- Hyphenation.
- Bidirectional text.
- Non-Latin scripts.
- Pagination.
- PDF font embedding/subsetting.
- Print-raster DPI.

These should be explicitly tracked as real work, not treated as small details hidden under "layout".

### 12.2 Text and typography requirements

Text is central to ABM artifacts, so the engine needs a deliberate text plan.

Requirements:

- Deterministic font availability between server exports and browser previews.
- Brand font sourcing and licensing checks.
- Embeddable/subsettable fonts for PDF where allowed.
- Fallback font policy when a brand font is unavailable or not embeddable.
- Non-Latin and RTL support where the target campaign/contact data requires it.
- Text measurement consistent enough for slot-fit validation.
- Line-breaking and hyphenation strategy.

For V1, we can use pragmatic browser/Canvas/Konva text measurement for the editor while keeping export validation explicit. Long-term, text shaping may need a more controlled engine or a headless browser/PDF pipeline.

### 12.3 Add print/page constraints

ABM artifacts often need print fidelity.

The layout model should support:

- Fixed page sizes.
- Bleed.
- Safe margins.
- Print units.
- DPI-aware raster export.
- Font embedding or font-subsetting path for PDF.
- Overflow validation against page safe areas.

### 12.4 Pagination and print caveat

Multi-page reports and brochures introduce pagination. This is not the same as placing boxes on a fixed artboard.

The first MVP may avoid automatic pagination by requiring explicit pages/artboards. If automatic flowed reports become important, that should be scoped as its own subsystem.

Browsers/Chromium and mature PDF libraries already solve parts of this problem. The architecture should allow the export pipeline to use those tools if they give better fidelity than a custom renderer.

### 12.5 Add content-fit validation

The engine should validate not just whether the visual layout is currently valid, but whether it can survive future slot replacement.

Example:

- Contact name placeholder fits.
- Long realistic contact name still fits under the slot policy.
- Hospital name wraps within allowed lines.
- Logo slot preserves aspect ratio.
- CTA does not overflow button.

This can start with simple heuristics and become more advanced later.

---

## 13. Rendering And Export

### 13.1 MVP renderer recommendation

Do not make WebGPU the first critical path if it slows the MVP.

Recommended staged approach:

- MVP: SVG renderer/exporter as the fidelity baseline.
- MVP: React-Konva/Konva for canvas editing and editor-level interactions.
- MVP: The Konva adapter renders from the scene model; it does not own the scene model.
- Phase 2: WebGPU/Vello for high-performance large documents and advanced effects.

The important thing is not the renderer technology. The important thing is that the same scene model exports predictably.

### 13.2 Renderer adapter boundary

The editor must not hard-code business logic into Konva nodes.

Recommended split:

```text
Scene model
  -> renderer adapter interface
      -> React-Konva renderer for V1 editor
      -> SVG renderer/exporter for V1 export baseline
      -> future Vello/WebGPU renderer
      -> future Figma importer/exporter
```

React-Konva may own:

- Selection visuals.
- Handles.
- Drag/resize interactions.
- Editor hover states.
- Canvas pan/zoom.

React-Konva must not own:

- Slot semantics.
- Canonical node IDs.
- Export settings.
- Brand token resolution.
- Template finalization.
- Operation history.

This keeps Konva replaceable.

### 13.3 Export formats

Initial exports:

- SVG.
- PNG at configurable scale.
- PDF for print.

Future exports:

- Figma bridge.
- HTML/email-safe variant, if product direction requires.
- Bulk export after personalization workflow exists.

### 13.4 Figma export and round-trip import

Figma export should be treated as a separate capability, not assumed to be equivalent to SVG export.

Possible approaches:

- Export SVG and import into Figma. Simple but loses semantic editability.
- Build a Figma plugin that recreates nodes using Figma's plugin API. More work, better editability.
- Export a structured interchange format plus plugin importer. Most future-proof.

The user requirement includes a round-trip:

```text
Design Engine -> Figma for major edits -> Design Engine import after finalization
```

This is genuinely hard and should be flagged early because it constrains the interchange model.

The round-trip must preserve:

- Stable node identity where possible.
- Slot keys.
- Slot-to-node bindings.
- Page/artboard identity.
- Export settings or enough metadata to restore them.
- Brand token references where possible, or resolved styles plus provenance.

Likely mechanisms:

- Figma plugin stores Design Engine metadata in plugin data.
- Export includes a sidecar manifest mapping Figma node IDs to scene node IDs and slot keys.
- Import validates which slots survived and which were broken by manual Figma edits.
- Import creates a new draft/template revision rather than mutating the old finalized template in place.

For MVP, SVG/PDF/PNG are more important. Figma round-trip can be post-MVP, but the scene/interchange model must not make it impossible.

---

## 14. Agent Subsystem

### 14.1 Agent role

The agent should act as a design collaborator that uses engine tools.

It should not directly mutate internal server state through hidden paths.

### 14.2 Minimal agent tools

Initial tools:

- Read document summary.
- Read page/artboard summary.
- Read slot summary.
- Write or patch DSL.
- Apply structured operations.
- Query layout/geometry.
- Validate document.
- Validate slots.
- Export preview.
- Render preview image.
- Generate image asset.
- Generate SVG/vector asset.
- Vectorize uploaded image.
- Place/replace asset.
- Set or update Brand Kit reference.

### 14.3 Agent self-review

The agent should perform review loops against structural checks:

- Does the document compile?
- Are pages valid?
- Are required slots present?
- Is text inside bounds?
- Are exports generated?
- Is the design using brand tokens?
- Is the artifact type appropriate for the prompt?
- Are placeholder values realistic enough to test layout?

### 14.4 Visual critic loop

Structural checks are necessary but not sufficient. A design can compile, validate slots, and export successfully while still looking wrong.

The agent loop should include a rendered-preview critique step:

```text
generate/modify design
  -> compile/validate structurally
  -> render SVG/PNG preview
  -> feed preview screenshot to visual critic
  -> critique hierarchy, spacing, contrast, brand fit, composition, readability
  -> repair through tools if needed
```

The visual critic should evaluate:

- Visual hierarchy.
- Layout balance.
- Spacing consistency.
- Contrast and accessibility.
- Brand fit.
- Print-safe margins.
- Text readability.
- Whether placeholder content looks credible.
- Whether imagery feels appropriate rather than decorative filler.

This restores one of Brilliant's important ideas: agents should inspect the rendered output, not only the data structure.

### 14.5 Asset generation and acquisition

Real ABM artifacts often need imagery, icons, logos, textures, charts, or generated visuals.

The Design Engine should support asset workflows through tools:

- Upload asset.
- Search/select existing workspace asset.
- Generate raster image.
- Generate SVG/vector illustration.
- Vectorize image.
- Remove background or normalize logo, if later needed.
- Place asset into a node or slot.

Generated or uploaded assets should carry provenance and licensing/usage metadata where possible.

### 14.6 Agent context boundaries

Brand guide text, uploaded files, website text, and future account research are data, not instructions.

The agent orchestrator must keep system instructions, user instructions, and untrusted source material separate.

---

## 15. Minimal Editor

The editor should be practical, not exhaustive.

MVP editor capabilities:

- Open a design document.
- View pages/artboards.
- Select nodes.
- Move and resize nodes.
- Edit text.
- Inspect and edit basic visual properties.
- Inspect slot metadata.
- Mark/unmark a node as a slot.
- Change slot key/type/overflow behavior.
- Run validation.
- Ask agent for revisions.
- Export.
- Finalize template revision.

Non-MVP editor capabilities:

- Full vector editing.
- Advanced image editing.
- Full component system.
- Multi-user collaboration.
- Complex prototyping.
- Plugin marketplace.

---

## 16. Persistence

### 16.1 Recommended persistence stance

Use an operation log and snapshots, but do not overbuild collaboration early.

For the Design Engine MVP:

- Save design documents.
- Save snapshots.
- Save operation history enough for undo/replay.
- Save assets.
- Save Brand Kit refs.
- Save template revisions.

Future:

- Multi-user collaboration.
- Bulk export audit.
- Campaign linkage.

### 16.2 Template finalization

Finalized templates should be versioned.

A future ABM workflow should be able to say:

```text
Use template_revision_id = X
Bind slot contact.full_name to value Y
Export one PDF per contact
```

The current sprint does not implement that command, but the data shape should make it obvious later.

### 16.3 Future instance derivation

Personalized instances should derive from immutable template snapshots and binding sets.

Conceptually:

```text
TemplateRevisionSnapshot
  + BindingSet(account/contact/content values)
  + ExportProfile
  -> PersonalizedInstanceRender
```

The system may store outputs, audit records, and per-instance manual overrides later. It should not replay the original template design operation log for every personalized instance.

---

## 17. API Surface, Conceptual

This is not an exact FastAPI schema.

The Design Engine should expose conceptual capabilities:

- Create design draft.
- Compile DSL to scene/ops.
- Apply operations.
- Validate visual document.
- Validate slot model.
- Export artifact.
- Finalize template revision.
- Read document summary.
- Read slot summary.
- Attach or update brand kit.

It should not expose account/contact/research/campaign APIs inside the Design Engine subsystem.

Those belong to higher ABM platform services later.

---

## 18. MVP Success Criteria

The current Design Engine MVP succeeds when:

- A user can prompt the system to create a branded artifact.
- The artifact appears in a browser editor.
- The artifact can contain multiple pages/artboards.
- The user can make basic visual edits.
- The agent can make revisions through engine tools.
- The document has stable semantic slots.
- Slot validation can catch missing or risky placeholders.
- The artifact can be finalized as a template revision.
- The artifact can export to SVG, PNG, and PDF.

The MVP does not need to:

- Fill slots from real account/contact data.
- Generate thousands of variants.
- Send campaigns.
- Support real-time multiplayer.
- Match every Figma editing feature.

---

## 19. Phased Roadmap

### Phase 0 - Architecture foundation

- Create monorepo or clear package layout.
- Define scene model with pages, nodes, styles, slots, and export settings.
- Define operation vocabulary.
- Define Rust `lumen-core` boundaries and ensure it compiles natively and for `wasm32`.
- Build basic snapshot/replay tests.

### Phase 1 - Static document engine

- Implement scene operations.
- Implement page/artboard model.
- Implement basic nodes: frame, group, text, rect, image, vector.
- Implement slot metadata and validation.
- Implement JSON serialization.
- Keep DSL out of rich document/page/export configuration.

### Phase 2 - DSL compiler

- Implement minimal DSL parser.
- Compile DSL to scene operations.
- Add diagnostics and partial failure handling.
- Add lightweight page references if needed.
- Add lightweight slot annotations.
- Prefer structured operations for complex agent patching.

### Phase 3 - Layout and validation

- Integrate Taffy for auto-layout.
- Add fixed page sizes and safe areas.
- Add text measurement.
- Add overflow policies for slots.
- Add basic fit fixtures for realistic slot replacement.
- Add initial image/logo fit policies.
- Add document validation and slot validation.

### Phase 4 - Rendering and export

- Implement SVG export baseline.
- Implement React-Konva editor renderer adapter.
- Implement PNG export.
- Implement PDF export.
- Add visual regression fixtures.
- Add browser preview path.
- Keep renderer adapter replaceable.

### Phase 5 - Minimal editor

- Build React editor shell.
- Load/render document through React-Konva.
- Select/move/resize/edit text.
- Inspect/edit slots.
- Run validation.
- Export.

### Phase 6 - Brand Kit

- Define Brand Kit input/output.
- Add brand token compiler.
- Attach Brand Kit to document.
- Generate artifacts using brand tokens.
- Version Brand Kit refs.

### Phase 7 - Agent design loop

- Add agent orchestration.
- Add design tools.
- Add structural self-review loop.
- Add rendered-preview visual critic loop.
- Add asset generation/vectorization/place-asset tools.
- Add prompt-to-artifact flow.
- Validate generated designs before showing/finalizing.

### Phase 8 - Template finalization

- Add finalize action.
- Freeze/version template revision.
- Validate required slots and exports.
- Prepare template revision for future personalization workflow.

### Phase 9 - Future ABM integration

Out of current sprint:

- Bind account/contact/content data to slots.
- Generate personalized instances.
- Allow per-instance editing.
- Bulk export.
- Campaign publishing integrations.
- Figma round-trip import, unless prioritized earlier.

---

## 20. Parallel Workstreams And Branch Plan

Development should split across stable architectural boundaries, not arbitrary feature groups. The shared rule is:

```text
scene + operations + slots are the shared contract.
Everything else is an adapter around that contract.
```

### 20.1 Foundation branch

Branch:

```text
contracts/scene-op-slot-v0
```

Purpose:

- Define scene model shape.
- Define page/artboard model.
- Define stable node/page/slot/paint IDs.
- Define slot metadata shape.
- Define operation vocabulary.
- Define renderer adapter interface.
- Define export interface.
- Add basic JSON fixtures.
- Include structured update operations so editor and agent changes remain in the operation log.
- Include finalization semantics: validation-gated, immutable template revisions.
- Include structural validation for tree integrity, ID consistency, slot scope targets, and export-profile sanity.

This branch should be short and contract-oriented. It should not implement the full compiler, editor, layout engine, renderer, persistence service, or agent runtime.

### 20.2 Rust core engine

Branch:

```text
engine/core-scene-ops
```

Owns:

- Scene structs.
- Operation applier.
- Serialization/deserialization.
- Snapshot tests.
- Native compile check.
- `wasm32-unknown-unknown` compile check.

This workstream stays pure Rust and must not depend on React, Konva, FastAPI, databases, browser APIs, or object storage.

### 20.3 DSL compiler

Branch:

```text
engine/dsl-compiler
```

Owns:

- Minimal DSL parser.
- Token normalization.
- Structured diagnostics.
- DSL-to-operation compilation.
- Lightweight slot annotations.
- Good/bad DSL fixtures.
- Cascade-halt and resume behavior.

Depends on:

- Scene contract.
- Operation contract.
- Slot contract.

### 20.4 Slot validation and layout

Branch:

```text
engine/slots-layout
```

Owns:

- Slot validation beyond structural checks.
- Required/optional slot rules.
- Overflow policy behavior.
- Basic Taffy layout adapter.
- Safe-area checks.
- Text-fit fixture checks.
- Sample/worst-case content fixtures.
- Initial image/logo fit-policy validation.

Depends on:

- Scene contract.
- Page/artboard contract.
- Slot contract.
- Operation contract.

### 20.5 React-Konva editor

Branch:

```text
editor/konva-v1
```

Owns:

- React shell.
- Canvas surface.
- Scene-to-Konva renderer adapter.
- Selection.
- Move/resize interactions.
- Basic text editing.
- Inspector skeleton.
- Slot inspector.

The editor must not own design semantics. It consumes the scene contract, emits operations, and keeps Konva replaceable.

### 20.6 SVG/PNG/PDF export

Branch:

```text
export/svg-pdf
```

Owns:

- Scene-to-SVG exporter.
- PNG rendering path.
- Early PDF export path.
- Export profiles.
- Export diagnostics.
- Visual/export fixtures.

This workstream should share the same scene contract as the editor, but should not depend on Konva.

### 20.7 Brand Kit and tokens

Branch:

```text
brand-kit/tokens-v0
```

Owns:

- Brand Kit model.
- Color token model.
- Typography token model.
- Logo and font asset refs.
- Token resolution.
- Brand Kit version reference on documents.

Can proceed mostly in parallel after scene style/token refs are stable.

### 20.8 Agent orchestration

Branch:

```text
agents/design-loop-v0
```

Owns:

- Agent tool contracts.
- Read document summary.
- Apply operations.
- Compile/validate loop.
- Render-preview visual critique loop.
- Asset generation tool stubs.

Can start with mocked engine/export calls, then wire into Rust core and export workstreams.

### 20.9 Persistence and API

Branch:

```text
api/persistence-v0
```

Owns:

- Document save/load.
- Scene snapshots.
- Operation history.
- Asset metadata.
- Template revision records.
- Minimal FastAPI routes.

This workstream stores the engine model. It must not redefine design semantics.

### 20.10 Asset pipeline

Branch:

```text
assets/pipeline-v0
```

Owns:

- Asset upload.
- Asset references.
- Image metadata.
- Logo/image placement inputs.
- Provenance/licensing fields.
- Future image generation/vectorization hooks.

This is separated because imagery touches editor, agents, export, and brand kits.

### 20.11 Testing, conformance, and CI

Branch:

```text
qa/conformance-ci
```

Owns:

- Shared fixtures.
- Rust native tests.
- `wasm32` compile checks.
- Scene snapshot tests.
- Export visual-regression skeleton.
- Contract tests for editor/export/agent boundaries.

This should run in parallel from the start and should harden the shared contract as other streams land.

### 20.12 Spike branches

Keep the following as short research branches, not mainline dependencies:

- `spike/figma-roundtrip`
- `spike/pdf-rendering-options`
- `spike/text-shaping-fonts`
- `spike/wasm-browser-core`
- `spike/vello-webgpu`

### 20.13 Practical order

1. `contracts/scene-op-slot-v0`
2. Parallel: `engine/core-scene-ops`, `editor/konva-v1`, `export/svg-pdf`, `qa/conformance-ci`
3. Parallel: `engine/dsl-compiler`, `engine/slots-layout`, `brand-kit/tokens-v0`
4. Parallel: `agents/design-loop-v0`, `api/persistence-v0`, `assets/pipeline-v0`

---

## 21. Key Decisions To Discuss

### 21.1 Is the Design Engine scene model slot-first?

Recommendation: yes.

Slots should be first-class because the future ABM platform depends on them.

### 21.2 Is DSL the source of truth?

Recommendation: no.

Scene plus operations should be canonical. DSL should be an agent/human authoring surface.

### 21.3 Do we need multi-page/artboard support in MVP?

Recommendation: yes.

ABM artifacts are often reports, brochures, mailers, and ad sets. Single-root documents will hurt quickly.

### 21.4 Is WebGPU/Vello required for MVP?

Recommendation: no.

Keep it as a target architecture, but make SVG/export correctness and React-Konva editing the first milestone.

### 21.5 Should FastAPI and full persistence be built immediately?

Recommendation: only as needed.

The engine/editor contract matters more at this stage than the final backend shape.

### 21.6 How should Figma export be treated?

Recommendation: post-MVP bridge unless user workflow demands it immediately, but design the interchange model now.

SVG import is easy but lossy. A real Figma plugin/importer is better but should be scoped separately. Round-trip import must preserve slots or explicitly report broken slot bindings.

### 21.7 How strict should brand guide support be in MVP?

Recommendation: support a basic Brand Kit abstraction immediately, even if extraction from uploaded guides is simple at first.

The design engine should consume normalized brand tokens rather than raw style-guide text.

### 21.8 How much of the Rust core should be used in-browser in V1?

Recommendation: the core should compile to WASM from day one, but the browser does not need to depend on WASM for all editor interactions in V1.

V1 can use React-Konva for editing while the server uses the native Rust core. Browser WASM can be introduced when local compile/layout responsiveness is needed.

### 21.9 Are personalized instances derived from the op-log?

Recommendation: no.

Instances should derive from finalized template snapshots plus binding sets. The op-log is for template history, undo/replay, audit, and future collaboration.

---

## 22. Proposed Changes Versus Previous Spec

- Reframe the project as ABM Design Engine, not standalone Lumen design app.
- Add explicit ABM platform context.
- Add explicit current-sprint non-goals.
- Add pages/artboards instead of single-root-only documents.
- Add semantic slots as first-class model objects.
- Add slot support for repeaters, conditionals, fit fixtures, and image/logo policies.
- Clarify scene plus operations as canonical, DSL as authoring/import/export surface.
- Clarify that personalized instances derive from finalized template snapshots plus binding sets, not template op-log replay.
- Adopt Rust `lumen-core` as the portable deterministic core while keeping full browser WASM optional for V1.
- Add React-Konva/Konva as the V1 editor renderer with a replaceable renderer adapter boundary.
- Add Brand Kit as a first-class concept.
- Move WebGPU/Vello out of MVP critical path.
- Add print/page/export constraints and explicitly flag text, typography, pagination, and font licensing as real subsystems.
- Add rendered-preview visual critic loop to the agent process.
- Add image/SVG generation, vectorization, and asset placement tools to the agent surface.
- Add Figma round-trip import as a future but architecture-constraining capability.
- Add template finalization and revisioning.
- Move bulk personalization to future scope but preserve compatibility.
- Simplify backend requirements for the first implementation.

---

## 23. Working Definition

The Design Engine is successful if it can produce a visually polished, brand-aligned, exportable artifact that is also structurally meaningful enough for future ABM automation.

In short:

**It should not just draw the brochure. It should know where the doctor's name, hospital logo, account insight, CTA, and offer message live inside the brochure.**
