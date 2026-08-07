# Branch 3 Spec: Agent Artboard Frame Generation V0

Status: planning spec  
Branch: `agents/artboard-frame-generation-v0`  
Worktree: `/Users/aryankeshri/Documents/brilliant-design/agents-artboard-frame-generation-v0`  
Date: 2026-06-14

## Purpose

This branch teaches the Lumen agent runtime to author and repair export-safe
artifacts against the canonical artboard geometry contract introduced by
`engine/canonical-artboard-geometry-v0`.

The branch is not a renderer rewrite and not an editor UI branch. It is the
agent-facing layer that makes the new geometry contract usable:

- generated DSL should use canonical point-based artboard-local coordinates;
- generated pages should be structured as bounded artboards with root frames,
  page/artboard fills, clipping, auto-layout, padding, gap, fill, hug, fixed, and
  wrap;
- repair should escalate from text-only surgical edits to bounded
  `layout_cluster` repair when diagnostics prove that the parent/artboard
  layout is the failure, not one isolated text node;
- evaluation should catch oversized background rectangles, parent overflow, and
  A4/custom-size unit mismatch before the agent claims success.

## Grounding References

This spec is grounded in the current project architecture and the local
Brilliant research. The important references are:

- `design/reference_docs/ABM-Design-Engine-Temporary-Spec.md`
  - one deterministic design engine should be used by agents, editor, export,
    and future automation;
  - `Scene` is the canonical in-memory model;
  - `Operation` is the canonical mutation/history model;
  - DSL is an agent/human authoring surface and compact patch format, not the
    whole source of truth;
  - agents should repair through engine tools and visual/structural checks.
- `design/reference_docs/Brilliant-Reverse-Engineering-Report.md`
  - Brilliant's agent writes through the same compiler/editor model as the
    human;
  - Blueprint has normalize, parse, validate, interpret, and lint phases;
  - valid prefixes are applied and failures halt with a single-point diagnostic;
  - frames and auto-layout are first-class;
  - backgrounds are fills on parents, not fake child rectangles;
  - screenshot/self-review feedback drives the next repair block.
- `design/reference_docs/Brilliant-vs-Lumen-Product-Gap-Analysis.md`
  - Lumen already has good deterministic contracts, but the prompt runtime must
    expose a Brilliant-like authoring and repair protocol;
  - layout and text reliability require auto-layout-first recipes, all-text
    overflow diagnostics, computed geometry, and repair operations;
  - targeted editing and repair semantics are required to avoid whole-page
    regeneration.
- `docs/artboard-workspace-geometry-plan.md`
  - Branch 3 deliverables and exit gate;
  - `layout_cluster` repair policy and prohibitions;
  - point-based authoring and artboard-as-frame recipes.
- `docs/canonical-artboard-geometry-implementation-plan.md`
  - Branch 1 downstream implication: agents can now author against canonical
    artboard dimensions and use page fills/root frames instead of oversized
    background rectangles.
- Current runtime docs:
  - `apps/agent_runtime/knowledge_docs/AGENT.md`;
  - `apps/agent_runtime/knowledge_docs/skills/create-design/SKILL.md`;
  - `apps/agent_runtime/knowledge_docs/skills/repair-design/SKILL.md`;
  - `apps/agent_runtime/knowledge_docs/knowledge/lumen-dsl/layout.md`;
  - `apps/agent_runtime/knowledge_docs/knowledge/lumen-dsl/diagnostics.md`;
  - `apps/agent_runtime/knowledge_docs/knowledge/loop/authoring-and-repair.md`.

## Existing Contracts This Branch Must Respect

### Scene and Operation remain canonical

The agent must not mutate Python-side scene dictionaries by hand. Every scene
change must still flow through one of the checked mutation surfaces:

- `compile_dsl_block` for DSL-to-operation compilation;
- `apply_operations` for explicit core operation lists;
- `apply_structured_edit` for typed targeted edits with strict scope;
- core/API edit routes that themselves lower to canonical operations.

DSL remains an authoring and patch format. This branch may update DSL knowledge
and examples, but it must not make DSL the sole source of page/export metadata.

### PageGeometry is the source for layout bounds

Branch 1 introduced canonical page geometry:

```text
PageGeometry {
  layout: Rect,              # canonical pt artboard bounds
  source: PageSizeSource?,   # user-declared source size/unit
  physical: PhysicalPageSize?,
  raster: RasterPageSize?,
  canonical: bool
}
```

For new generated artifacts:

- child `p(...)` and `s(...)` values are canonical layout points;
- they are never physical millimeters;
- they are never renderer pixels;
- source physical/raster metadata is retained on page geometry/export metadata;
- export adapters consume the normalized geometry, not inner-node dimensions.

Examples:

```text
page a4 preset(a4,portrait)
  # layout is approximately 595.276 x 841.890 pt
  # source/output metadata preserves 210mm x 297mm

page square size(1080,1080,px)
  # layout is 1080 x 1080 pt
  # raster default preserves 1080 x 1080 px

page letter size(8.5,11,in)
  # layout is 612 x 792 pt
  # physical metadata preserves 8.5in x 11in
```

### Bounds diagnostics already exist

Branch 1 added canonical bounds checks:

- `LUMV0800`: node exceeds exportable page/artboard bounds;
- `LUMV0801`: node exceeds parent bounds;
- `LUMV0802`: node outside trim bounds but inside bleed;
- `LUMV0803`: invalid canonical layout bounds;
- `LUMV0805`: legacy non-pt page advice.

This branch does not need to invent bounds preflight from scratch. It needs to
route these diagnostics into better agent behavior and repair choices.

### Current repair is too surgical

The current agent loop has a targeted repair guard:

- if a preflight/compile/visual diagnostic names a node and the edit surface is
  `structured_ops`, the coordinator marks it as surgical;
- surgical repair currently requires modify-only DSL if the author emits DSL;
- non-surgical DSL is rejected before compile so it cannot wipe the good scene.

That solved destructive whole-scene repairs, but it is too narrow for parent
layout failures. A node-specific text edit cannot fix a cluster where a parent
card was resized but its header/divider/CTA descendants stayed at the old width.

Branch 3 extends, rather than removes, that protection.

## Brilliant-Inspired Design Principles

### 1. Repair is a controlled edit loop, not a hidden cleanup pass

Brilliant does not appear to expose a public standalone "repair engine." Its
repair behavior emerges from a controlled loop:

```text
load knowledge
  -> write one block
  -> compile/validate/lint
  -> on error: exact failing line + hint + applied count
  -> on success: screenshot + self-review checklist
  -> repair the smallest region through the same edit surface
```

Lumen should mirror the control-loop shape:

- diagnostics are structured and targetable;
- repairs use canonical mutation surfaces;
- successful draft scenes are preserved;
- repair attempts are traceable;
- unsupported repairs become explicit product gaps.

### 2. Frames and auto-layout are the repair substrate

Brilliant's repair story depends on its design primitives:

- frames and auto-layout parents are real containers;
- children are parent-local;
- fills belong on parent frames;
- `hug`, `fill`, `fill:N`, fixed size, padding, gap, and wrap are first-class;
- parent resize and child resize are layout operations, not renderer hacks.

Lumen should teach the agent to author in the same spirit:

- page/artboard is the export surface;
- root frame is the bounded layout cluster on that surface;
- background is page/artboard fill or root-frame fill, not a loose oversized
  rectangle;
- content is grouped into auto-layout stacks and rows;
- variable text gets `s(fill,hug)`, `wrap_text(true)`, and realistic `max_lines`;
- dense clusters are made taller/wider or reflowed, not endlessly shrunk.

### 3. Diagnostics should route repair class

Brilliant's compiler/linter separates hard errors from lints and provides fix
hints. Lumen should use the same pattern at the runtime level:

```text
diagnostic -> repair class -> bounded target -> allowed actuator
```

The branch should not rely on vague prompt text like "fix layout." It should
turn page/parent diagnostics into explicit `layout_cluster` repair requests.

### 4. Undo/scope is part of repair safety

Brilliant scopes sessions and undo so agent work does not collide with user work.
Lumen's equivalent is:

- best compiled scene preservation;
- checked structured edits;
- strict `scope` on repairs;
- runtime rejection of destructive DSL;
- trace evidence for every rejected and accepted repair.

Branch 3 must preserve this property while permitting larger bounded repairs.

## Target Authoring Model

### Page/artboard is the exportable surface

The page line declares the exportable artboard:

```text
page appointment_card preset(a4,portrait)
```

The page's canonical layout bounds define child authoring space. The agent must
use those bounds, not source physical units.

### Background is a page/artboard fill or root-frame fill

Preferred for page-wide background:

```text
page appointment_card preset(a4,portrait) background($surface.page)
```

If the grammar/runtime supports only page modification for background, the
author may emit an immediate page modify line after page creation:

```text
page appointment_card preset(a4,portrait)
#page:appointment_card background($surface.page)
```

Fallback when page background is unavailable in a specific authoring context:

```text
page appointment_card preset(a4,portrait)
  artboard_root al(v,x(s),g(24),pad(40)) p(0,0) s(595,842) fill($surface.page) clip(true)
```

This fallback is still a bounded root frame, not a fake background rectangle with
unrelated children scattered outside it.

### Root artboard frame owns the layout cluster

For generated export-safe pages, the recommended structure is:

```text
page page_id ...
  artboard_root al(v,x(s),g(...),pad(...)) p(0,0) s(page_width_pt,page_height_pt) clip(true)
    section_or_card al(v,x(s),g(...),pad(...)) s(fill,hug)
      ...
```

The root frame may be:

- a fixed-size frame/auto-layout node whose size equals the artboard layout
  bounds;
- clipped when content must stay inside the export surface;
- filled only when the page background cannot carry the background directly;
- the repair target for page-wide layout changes.

### Children are artboard-local

Every generated child position is local to its parent:

- children of the page/root frame are measured from the artboard top-left;
- children of cards/sections are measured from their parent;
- no child coordinates should encode page physical size;
- no child should use a raster output dimension unless the page is a digital
  raster artifact whose canonical layout itself is that size.

### Fill/hug/fixed semantics are authoring obligations

Agent examples should use the following rules:

- Use fixed root/artboard shells for known export surfaces.
- Use `fill` width for body/prose text inside auto-layout columns.
- Use `hug` height for variable text.
- Use fixed width/height only for bounded cards, buttons, logos, and images.
- Use `wrap(true)` for rows with variable-count children.
- Use `pad(...)` and `g(...)` before manual child offsets.
- Use `clip(true)` only when clipping is intentional and diagnostics remain
  visible in preflight.

## Artboard-As-Frame Recipes

### A4 appointment card

Purpose: fix the run class where A4 stored `210 x 297 mm` but children were
authored as if the page were `595 x 842 pt`.

Expected generated shape:

```text
page appointment_card preset(a4,portrait) background($surface.page)
  artboard_root al(v,x(c),g(24),pad(42)) p(0,0) s(595,842) clip(true)
    header al(v,x(c),g(8),pad(0)) s(fill,hug)
      eyebrow text "Appointment Reminder" s(fill,hug) style($type.eyebrow) wrap_text(true) max_lines(1)
      headline text "Your visit is confirmed" s(fill,hug) style($type.headline) wrap_text(true) max_lines(2)
    card al(v,x(s),g(16),pad(24)) s(fill,hug) fill($surface.card) rd($radius.lg)
      patient_row al(h,x(sb),y(c),g(12),pad(0)) s(fill,hug)
        patient_label text "Patient" s(hug,hug) style($type.label)
        patient_name text "Dr. Priya Sharma" s(fill,hug) style($type.body) wrap_text(true) max_lines(1) slot(contact.full_name)
      divider fr s(fill,1) fill($stroke.subtle)
      instruction text "Please arrive 15 minutes early..." s(fill,hug) style($type.body) wrap_text(true) max_lines(4) slot(appointment.instructions)
```

Notes:

- The example uses `595 x 842` rounded canonical point bounds for readability.
  Tests should tolerate exact A4 geometry from `PageGeometry`.
- There is no `bg s(595,842)` under a `210 x 297` mm page.
- The card and descendants use `fill` relative to parent width.

### Digital square ad

```text
page linkedin_square size(1080,1080,px) background($surface.brand)
  artboard_root al(v,x(s),g(32),pad(72)) p(0,0) s(1080,1080) clip(true)
    copy_stack al(v,x(s),g(22),pad(0)) s(620,hug)
      headline text "Let neurosurgeons focus on surgery." s(fill,hug) style($type.display) wrap_text(true) max_lines(3)
      body text "Insight Health handles calls, scheduling, and routing." s(fill,hug) style($type.body) wrap_text(true) max_lines(3)
      cta al(h,x(c),y(c),pad(16,28)) s(230,58) fill($surface.inverse) rd($radius.md)
        cta_text text "Book a Demo" s(fill,hug) style($type.cta) max_lines(1) slot(campaign.cta)
```

Notes:

- Since the source is `px`, the canonical layout is also `1080 x 1080 pt`.
- This is not a square frame inside a default page.

### Wide social ad

```text
page linkedin_wide size(1200,628,px) background($surface.page)
  artboard_root al(h,x(s),y(c),g(42),pad(56)) p(0,0) s(1200,628) clip(true)
    copy al(v,x(s),g(20),pad(0)) s(fill:2,hug)
      headline text "Answer every patient call." s(fill,hug) style($type.headline) wrap_text(true) max_lines(2)
      body text "AI phone agents route, schedule, and follow up." s(fill,hug) style($type.body) wrap_text(true) max_lines(3)
    proof_panel al(v,x(s),g(14),pad(24)) s(fill:1,hug) fill($surface.card) rd($radius.lg)
      proof text "Built for specialty clinics" s(fill,hug) style($type.label) wrap_text(true)
```

## Repair Classes

Branch 3 should make repair classification explicit.

### `syntax_continuation`

Use when:

- `LUMD02xx`/`LUMD03xx`/`LUMD04xx` points to a failed DSL line;
- the scene has only partially applied valid prefix lines.

Allowed:

- corrected continuation from the failed line;
- no whole-scene regeneration;
- no existing page re-declaration.

### `targeted_node`

Use when:

- one text/slot/brand diagnostic names one concrete node or slot;
- parent/artboard bounds are otherwise coherent.

Allowed:

- one or more `#node ...` modify lines;
- `apply_structured_edit` scoped to the target node/slot;
- immediate container size change only when named by diagnostic or explicitly
  required by the text fit.

### `layout_cluster`

Use when:

- `LUMV0800` reports a page/artboard bounds violation;
- `LUMV0801` reports parent overflow;
- several `LUMV0902`/`LUMV0903`/`LUMV0904` text errors share the same parent;
- a parent has been resized but descendants retain the old width/position scale;
- a top-level background-like rect/frame covers or exceeds the artboard;
- the diagnostic hint says move, resize, wrap, or change parent layout;
- visual critique reports clipping/overflow/alignment across a card/section, not
  one isolated text node.

Target cluster:

```text
LayoutClusterTarget {
  page_id: PageId,
  root_frame_id: Option<NodeId>,
  parent_node_id: Option<NodeId>,
  descendant_node_ids: Vec<NodeId>,
  background_node_id: Option<NodeId>,
  diagnostics: Vec<DiagnosticSummary>,
  page_bounds_pt: Rect,
  parent_bounds_pt: Option<Rect>
}
```

Allowed operations:

- modify `p(...)` on nodes in the cluster;
- modify `s(...)` on nodes in the cluster;
- change width/height sizing between fixed, `fill`, `hug`, and weighted fill on
  nodes in the cluster;
- change auto-layout direction, alignment, padding, gap, wrap, and clip on
  cluster parent/root nodes;
- grow or shrink the root cluster/container when the artboard bounds allow it;
- convert a diagnosed background rect/frame into a page/artboard fill;
- remove only a diagnosed leaf background node after its fill has been copied to
  the page/artboard and only if it has no semantic children;
- keep a diagnosed background frame as the root layout frame when it owns content,
  moving its paint to page background if needed but not deleting its children.

Prohibited operations:

- delete a page;
- re-declare an existing page;
- delete unrelated nodes;
- edit unrelated slots;
- edit unrelated Brand Kit tokens;
- replace unrelated assets;
- regenerate the whole scene;
- change page dimensions unless the diagnostic is about wrong page size and the
  user request proves the current page is the wrong artifact surface;
- hide overflow by clipping when the content still needs layout repair.

### `brand_token`

Use when:

- `LUMB...` diagnostics name raw/off-brand values, logo misuse, mode mismatch, or
  print transparency issues.

Allowed:

- token substitution in the named node/page/slot;
- no layout changes unless a brand token size change causes a follow-up layout
  diagnostic.

### `asset_tool`

Use when:

- the repair requires generating, vectorizing, placing, or replacing an image,
  logo, QR code, or asset byte.

Allowed:

- asset tools and scoped placement operations;
- no page/cluster rewrite.

### `unsupported_gap`

Use when:

- the repair requires a feature not supported by the current engine contract.

Allowed:

- `record_gap`;
- preserve the best draft.

## Layout Cluster Repair Protocol

### Step 1: classify

Input:

- preflight diagnostics;
- visual critique issues;
- current scene summary;
- page/node geometry summary;
- previous repair context.

Output:

```text
RepairClassification {
  repair_class: "layout_cluster",
  confidence: "high" | "medium" | "low",
  reason: String,
  target: LayoutClusterTarget,
  allowed_edit_surface: "structured_ops",
  forbidden_changes: Vec<String>
}
```

### Step 2: resolve cluster

The resolver should:

1. Start with the diagnostic target node.
2. Find the containing page.
3. Find the nearest bounded parent.
4. Include descendants whose bounds overflow that parent.
5. Include siblings only when they participate in the same auto-layout parent or
   share the same overflow/hierarchy failure.
6. Include a root frame when the cluster is at page/artboard level.
7. Include a background node only when diagnostics or heuristics prove it is a
   page/artboard background candidate.

### Step 3: choose actuator

Preferred actuator:

- `apply_structured_edit` with strict cluster scope for each targeted edit;
- or `apply_operations` with a batch scoped and validated by the core.

Fallback actuator:

- bounded DSL modify lines for only the page and node IDs in the cluster.

Rejected:

- new `page ...` lines;
- new top-level scene rewrite;
- unscoped `delete(...)`;
- `replace(...)` on the whole artboard/root unless the target cluster is
  explicitly the root and the operation preserves unrelated nodes/slots/assets.

### Step 4: apply repair

Typical transforms:

- Parent width changed from `400` to `170`, but descendants stayed `352` or
  `400`: set descendants to `s(fill,hug)` or parent-aware fixed widths, adjust
  padding/gap, and grow the parent if needed.
- Body text overflows after parent shrink: make body `s(fill,hug)`, increase
  parent/card height, or reduce copy/font only if the layout cannot grow.
- Header/divider/CTA exceed card: set divider to `s(fill,1)`, CTA to
  parent-fit width, header row to `s(fill,hug)`, and card padding to a feasible
  value.
- Top-level full-artboard background rect: move its fill to page background,
  then delete only that diagnosed leaf node or convert it into the root layout
  frame.
- Root frame exceeds page: resize root frame to page bounds and relayout
  descendants.

### Step 5: verify

After repair:

- rerun preflight;
- export a debug preview if preflight still fails;
- preserve best compiled scene;
- reject/rollback if the repair creates more severe diagnostics or touches
  out-of-scope entities;
- continue to visual review only when preflight and preview export are valid.

## Knowledge Document Requirements

Branch 3 must update agent knowledge so the author does the right thing before a
diagnostic appears.

Required updates:

- `apps/agent_runtime/knowledge_docs/AGENT.md`
  - add artboard-local geometry and layout-cluster repair to hard invariants and
    knowledge map.
- `apps/agent_runtime/knowledge_docs/skills/create-design/SKILL.md`
  - replace background-frame skeletons with page/artboard fill plus root frame
    recipes where supported;
  - add exact point-based A4/Letter/social examples;
  - state that child coordinates use canonical layout points.
- `apps/agent_runtime/knowledge_docs/skills/repair-design/SKILL.md`
  - add a `layout_cluster` section that explicitly permits bounded multi-node
    repair for page/parent overflow;
  - preserve destructive-repair prohibitions.
- `apps/agent_runtime/knowledge_docs/knowledge/lumen-dsl/layout.md`
  - add artboard root frame recipes;
  - explain how `fill`, `hug`, `wrap`, `pad`, and `gap` solve parent overflow.
- `apps/agent_runtime/knowledge_docs/knowledge/lumen-dsl/diagnostics.md`
  - add `LUMV0800` through `LUMV0805` repair mappings;
  - define when to escalate from text repair to `layout_cluster`.
- `apps/agent_runtime/knowledge_docs/knowledge/design/layout-recipes.md`
  - replace fake background rectangle examples;
  - add A4, Letter, square, and wide social layouts using root artboard frames.
- Optional new docs:
  - `knowledge/design/artboard-frame-authoring.md`;
  - `knowledge/loop/layout-cluster-repair.md`.

## Runtime Requirements

### Repair classification

Add a classifier that can distinguish:

- single-node text/fit repair;
- layout-cluster repair;
- brand/token repair;
- asset repair;
- unsupported gap.

The classifier must consume diagnostics and targets, not only keyword hints.

### Cluster repair request shape

Extend the repair request payload with:

```json
{
  "repair_class": "layout_cluster",
  "cluster": {
    "page_id": "appointment_card",
    "root_frame_id": "artboard_root",
    "parent_node_id": "card",
    "descendant_node_ids": ["header", "divider", "cta"],
    "background_node_id": "bg"
  },
  "permissions": [
    "modify_position",
    "modify_size",
    "modify_sizing_mode",
    "modify_auto_layout",
    "modify_padding_gap_wrap",
    "modify_page_background",
    "convert_diagnosed_background"
  ],
  "prohibitions": [
    "no_page_delete",
    "no_unrelated_node_delete",
    "no_unrelated_slot_brand_asset_edits",
    "no_whole_scene_regeneration"
  ]
}
```

### Guard behavior

The current `is_surgical_dsl` guard only accepts modify-only `#id` lines. Branch
3 should introduce a second guard for cluster repair:

```text
is_layout_cluster_dsl(source, allowed_page_ids, allowed_node_ids, background_node_id?)
```

It should allow:

- `#page:<id> background(...)` for allowed pages;
- `#<node_id> ...` modify lines for allowed cluster nodes;
- optional deletion/conversion only for the diagnosed background node, if the
  operation is explicitly allowed by the repair request.

It should reject:

- any `page ...` declaration;
- any new node declaration;
- any delete/replace/parent/clone outside the target cluster;
- any unrelated node ID;
- any unrelated page/slot/asset/brand target.

Structured edits remain preferred because they can enforce scope in the core.

## Evaluator Requirements

The branch should add evaluator checks that fail if a run:

- uses A4 child geometry against `210 x 297` child coordinates;
- creates a full-page background rect larger than artboard bounds;
- leaves `LUMV0800`/`LUMV0801` after repair;
- responds to parent overflow by only shrinking text while fixed children still
  exceed the parent;
- emits page deletion or whole-scene regeneration during a targeted repair;
- changes unrelated slots, brand tokens, or assets while repairing layout.

Trace summary should count:

- `layout_cluster` repair requests;
- `layout_cluster` repairs accepted/rejected;
- cluster guard rejections;
- oversized background findings;
- parent overflow findings;
- final remaining `LUMV080x`/`LUMV090x` diagnostics.

## Acceptance Criteria

This branch is complete when:

1. Agent knowledge clearly teaches point-based artboard-local authoring.
2. New generated A4/Letter/social examples use canonical artboard dimensions.
3. Generated page-wide backgrounds are page/artboard/root-frame fills, not loose
   oversized rectangles.
4. `LUMV0800` and `LUMV0801` route to `layout_cluster` when the target has a
   bounded parent/page context.
5. `layout_cluster` repair requests include explicit permissions,
   prohibitions, and cluster target IDs.
6. Cluster repair can update a card/root frame and affected descendants together.
7. Destructive scene/page rewrites remain rejected before application.
8. Trace/evaluator checks detect oversized backgrounds and parent overflow.
9. The appointment-card run class no longer fails because A4 uses `210 x 297`
   child coordinates or because parent/child scale diverges after repair.

## Non-Goals

This branch does not:

- implement the dark editor shell or infinite workspace UI;
- perform browser-rendered editor smoke validation;
- replace CanvasKit/Konva;
- add loose workspace objects;
- implement full Brilliant-style MCP, subagent fan-out, or live screenshot
  interruption;
- build a general automatic layout optimizer;
- add Figma import/export;
- solve full text shaping beyond existing measurement/preflight contracts;
- change the canonical `Scene`/`Operation` architecture.

## Open Questions

1. Should V0 introduce explicit `page.w` / `page.h` macros in DSL examples, or
   should examples use concrete canonical point dimensions until the grammar
   supports macros?
2. Should background conversion be represented as a single structured edit kind
   or as a scoped batch of page-patch plus node-delete/node-patch operations?
3. Should cluster repair be available to the model directly, or should the
   coordinator synthesize the cluster plan and ask the author only for
   properties?
4. Should page background fills be preferred over root-frame fills for all new
   generated pages, or only for simple single-background cases?
5. Should `LUMV0902`/`LUMV0903` escalate to `layout_cluster` only after repeated
   single-node repair failure, or immediately when multiple siblings share the
   same parent?

## Recommended Decisions For V0

1. Do not add `page.w`/`page.h` syntax in this branch unless it is already easy.
   Use concrete canonical point dimensions in examples and keep the grammar
   stable.
2. Prefer structured edits for cluster repair. Permit bounded DSL modify lines
   only as fallback.
3. Treat `LUMV0800` and `LUMV0801` as immediate `layout_cluster` candidates.
4. Treat `LUMV0902`/`LUMV0903` as `targeted_node` by default, escalating to
   `layout_cluster` when two or more diagnostics share a parent or a previous
   text-only repair failed.
5. For background conversion:
   - leaf background rect: copy fill to page background and remove only that
     diagnosed node;
   - background frame with children: keep it as root frame, move/normalize fill
     as needed, and repair descendants in place.
