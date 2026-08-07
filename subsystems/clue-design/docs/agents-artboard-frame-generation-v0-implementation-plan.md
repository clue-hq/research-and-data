# Branch 3 Implementation Plan: Agent Artboard Frame Generation V0

Status: implementation plan  
Branch: `agents/artboard-frame-generation-v0`  
Worktree: `/Users/aryankeshri/Documents/brilliant-design/agents-artboard-frame-generation-v0`  
Date: 2026-06-14

## Summary

This branch turns the canonical artboard geometry work into agent behavior. The
implementation should make the DeepAgent author export-safe artboard/root-frame
layouts by default and repair page/parent overflow as bounded layout clusters
instead of repeatedly applying text-only edits.

Implementation should proceed in five slices:

1. Update agent knowledge and examples for point-based artboard-local authoring.
2. Add explicit repair classification, including `layout_cluster`.
3. Add bounded cluster target resolution, permissions, prohibitions, and guard
   behavior.
4. Add evaluator and trace checks for oversized backgrounds and parent overflow.
5. Add deterministic tests and fixture prompts for A4, Letter, square, and wide
   social artifacts.

Do not run browser/Playwright smoke validation in this branch session unless the
user explicitly asks for it. Browser-rendered editor smoke is intentionally
separate.

## Pre-Implementation Checklist

Before code changes:

1. Confirm the worktree branch:

   ```bash
   git status --short --branch
   ```

2. Read branch memory:

   - `/Users/aryankeshri/Documents/brilliant-design/.codex/memory/README.md`
   - `/Users/aryankeshri/Documents/brilliant-design/.codex/memory/workstreams/agents-artboard-frame-generation-v0.md`
   - `/Users/aryankeshri/Documents/brilliant-design/.codex/memory/workstreams/engine-canonical-artboard-geometry-v0.md`
   - `/Users/aryankeshri/Documents/brilliant-design/.codex/memory/workstreams/artboard-workspace-spec-v0.md`

3. Read required reference docs:

   - `/Users/aryankeshri/Documents/brilliant-design/design/reference_docs/ABM-Design-Engine-Temporary-Spec.md`
   - `/Users/aryankeshri/Documents/brilliant-design/design/reference_docs/Brilliant-Reverse-Engineering-Report.md`
   - `/Users/aryankeshri/Documents/brilliant-design/design/reference_docs/Brilliant-vs-Lumen-Product-Gap-Analysis.md`

4. Keep all edits inside:

   ```text
   /Users/aryankeshri/Documents/brilliant-design/agents-artboard-frame-generation-v0
   ```

## Slice 1: Agent Knowledge And Examples

### Goal

Make the first authoring pass generate correct artboard-local structure so repair
is less frequent.

### Files

Update:

- `apps/agent_runtime/knowledge_docs/AGENT.md`
- `apps/agent_runtime/knowledge_docs/skills/create-design/SKILL.md`
- `apps/agent_runtime/knowledge_docs/knowledge/design/layout-recipes.md`
- `apps/agent_runtime/knowledge_docs/knowledge/lumen-dsl/layout.md`
- `apps/agent_runtime/knowledge_docs/knowledge/lumen-dsl/grammar.md`

Add if useful:

- `apps/agent_runtime/knowledge_docs/knowledge/design/artboard-frame-authoring.md`

### Required content changes

#### `AGENT.md`

Add hard invariants:

- Child `p(...)` and `s(...)` values are canonical layout points.
- Physical page units and raster pixels belong to page/source/output metadata,
  not child geometry.
- New export-safe pages should use page/artboard background fills and a bounded
  root frame.
- Loose oversized background rectangles are not acceptable for generated
  templates.
- Parent overflow may require `layout_cluster` repair, not isolated text repair.

Update the knowledge map:

```text
Any new design:
  skills/create-design
  knowledge/lumen-dsl/grammar
  knowledge/design/layout-recipes
  knowledge/design/artboard-frame-authoring

Any layout/page/parent overflow repair:
  skills/repair-design
  knowledge/lumen-dsl/diagnostics
  knowledge/lumen-dsl/layout
  knowledge/loop/layout-cluster-repair
```

#### `skills/create-design/SKILL.md`

Replace the current skeleton that uses:

```text
bg fr p(0,0) s(1080,1080) fill(...)
```

with a preferred page-background/root-frame structure:

```text
page linkedin_square size(1080,1080,px) background($surface.brand)
  artboard_root al(v,x(s),g(28),pad(72)) p(0,0) s(1080,1080) clip(true)
    ...
```

If page `background(...)` on create has any grammar/runtime gaps, document the
accepted fallback:

```text
page linkedin_square size(1080,1080,px)
#page:linkedin_square background($surface.brand)
  artboard_root al(v,x(s),g(28),pad(72)) p(0,0) s(1080,1080) clip(true)
```

Add exact point examples:

- A4 portrait: approximately `595 x 842`;
- Letter portrait: `612 x 792`;
- LinkedIn square: `1080 x 1080`;
- LinkedIn wide/custom social: source px equals canonical layout points.

#### `knowledge/design/layout-recipes.md`

Update recipes:

- square social ad;
- A4 one-pager/appointment card;
- US Letter one-pager;
- wide social ad.

Every recipe should:

- declare the correct page surface;
- use page background or root-frame fill;
- use one root frame or root auto-layout frame;
- use `fill`, `hug`, fixed, padding, gap, and wrap;
- avoid absolute child widths that duplicate the full old parent width.

#### `knowledge/lumen-dsl/layout.md`

Add a section:

```text
## Artboard-local layout
```

Include:

- page geometry examples;
- parent-local coordinates;
- root frame patterns;
- background fill rules;
- escalation from text to cluster repair when parent bounds fail.

#### `knowledge/lumen-dsl/grammar.md`

Confirm page background syntax. If background is currently valid on page create,
document it explicitly. If only page modify lines are stable, document the
modify-line form and make create examples use that form.

### Tests

Add or update knowledge tests in:

- `apps/agent_runtime/tests/test_lumen_deepagent_runtime.py`

Expected assertions:

- loaded knowledge for A4/artboard prompts includes "canonical layout points";
- loaded knowledge includes "artboard-local";
- loaded knowledge includes "background fill" or "page background";
- loaded knowledge no longer teaches `bg fr p(0,0) s(595,842)` as the primary
  background pattern for A4;
- create-design skill still includes valid DSL snippets.

## Slice 2: Repair Classification Model

### Goal

Make repair class a runtime concept, not just prose.

### Files

Update:

- `apps/agent_runtime/lumen_deepagent/schemas.py`
- `apps/agent_runtime/lumen_deepagent/loop.py`
- `apps/agent_runtime/lumen_deepagent/tools.py`
- `apps/agent_runtime/knowledge_docs/skills/repair-design/SKILL.md`
- `apps/agent_runtime/knowledge_docs/knowledge/lumen-dsl/diagnostics.md`

### Schema additions

Add:

```python
class RepairClass(str, Enum):
    syntax_continuation = "syntax_continuation"
    targeted_node = "targeted_node"
    layout_cluster = "layout_cluster"
    brand_token = "brand_token"
    asset_tool = "asset_tool"
    unsupported_gap = "unsupported_gap"
```

Add:

```python
class LayoutClusterTarget(BaseModel):
    page_id: Optional[str] = None
    root_frame_id: Optional[str] = None
    parent_node_id: Optional[str] = None
    descendant_node_ids: List[str] = Field(default_factory=list)
    background_node_id: Optional[str] = None
    diagnostic_codes: List[str] = Field(default_factory=list)
```

Extend `RepairRequest`:

```python
repair_class: Optional[RepairClass] = None
cluster: Optional[LayoutClusterTarget] = None
permissions: List[str] = Field(default_factory=list)
prohibitions: List[str] = Field(default_factory=list)
```

Keep existing fields for compatibility:

- `target`;
- `allowed_edit_surface`;
- `forbidden_changes`.

### Classification rules

Add a pure helper, likely in `loop.py` or a new small module:

```python
def classify_repair(summary_or_critique: dict, target: dict, scene_summary: dict) -> RepairClassification:
    ...
```

V0 rules:

1. Compile/parser failures:
   - `LUMD02xx`, `LUMD03xx`, `LUMD04xx`, `LUMA0200`
   - `repair_class = syntax_continuation`
   - unless the failure happened during an already-marked cluster repair, in
     which case preserve the prior class and target.

2. Page/artboard bounds:
   - any error `LUMV0800`
   - `repair_class = layout_cluster`

3. Parent bounds:
   - any error/warning `LUMV0801`
   - `repair_class = layout_cluster`

4. Invalid page geometry:
   - `LUMV0803`
   - if generated by the current agent, classify as `layout_cluster` only if a
     bounded page target can be corrected without changing user intent;
   - otherwise `unsupported_gap` or fail deterministic.

5. Legacy page advice:
   - `LUMV0805`
   - no automatic mutation in Branch 3; this is a scene migration/product gap
     unless the run itself created the page.

6. Text fit:
   - one `LUMV0902`/`LUMV0903`/`LUMV0904` on one node:
     `targeted_node`;
   - two or more text-fit errors under the same parent:
     `layout_cluster`;
   - repeat failure after a prior text-only repair:
     `layout_cluster`.

7. Brand:
   - `LUMB...`
   - `brand_token`

8. Asset generation/placement:
   - explicit generate/vectorize/QR intent or asset diagnostic:
     `asset_tool`

### Repair request creation

Update every `create_repair_request(...)` call path in `loop.py`:

- compile failure;
- preflight failure;
- visual critique failure.

Each path should:

1. classify repair;
2. compute allowed edit surface;
3. include class-specific constraints;
4. persist `repair_class`, `cluster`, `permissions`, and `prohibitions`.

### Tests

Add tests in `apps/agent_runtime/tests/test_lumen_deepagent_runtime.py`:

- `LUMV0800` routes to `layout_cluster`;
- `LUMV0801` routes to `layout_cluster`;
- one `LUMV0903` routes to `targeted_node`;
- two `LUMV0903` diagnostics under one parent route to `layout_cluster`;
- `LUMB0804` routes to `brand_token`;
- asset-generation intent still routes to `asset_tool`;
- legacy `LUMV0805` does not silently mutate page geometry.

## Slice 3: Cluster Resolution And Permissions

### Goal

Turn a diagnostic target into a bounded repair cluster.

### Files

Update:

- `apps/agent_runtime/lumen_deepagent/tools.py`
- `apps/agent_runtime/lumen_deepagent/loop.py`
- `apps/agent_runtime/lumen_deepagent/schemas.py`

Possibly add:

- `apps/agent_runtime/lumen_deepagent/repair.py`

### Cluster resolver

Implement a read-only resolver over `tools.scene`:

```python
def resolve_layout_cluster(scene: dict, diagnostics: list[dict], target: dict) -> LayoutClusterTarget:
    ...
```

Inputs:

- current scene;
- current diagnostics;
- first diagnostic target;
- prior repair context when present.

Algorithm:

1. Determine `page_id`:
   - from diagnostic `target_page_id`;
   - from target node's parent chain;
   - fallback to active/first page only if the scene has one page.

2. Determine target node:
   - `target_node_id` from diagnostic;
   - issue target from visual critique;
   - background-like node from diagnostic message/hint if present.

3. Walk parent chain:
   - nearest parent node becomes `parent_node_id`;
   - page-level target uses root frame candidate if one exists.

4. Detect root frame candidate:
   - direct child of page;
   - `p(0,0)`;
   - size approximately page bounds;
   - frame or auto-layout;
   - has children or clip/fill/layout role;
   - id contains `root`, `artboard`, `bg`, `background`, `canvas`, or is the only
     direct page child.

5. Detect background candidate:
   - direct page child;
   - rect/frame;
   - no slot binding;
   - fill present;
   - bounds cover most or all page;
   - either leaf node or root frame with content.

6. Include descendants:
   - children whose geometry exceeds parent;
   - siblings in the same auto-layout parent when multiple diagnostics share the
     parent;
   - divider/header/CTA descendants for common card overflow pattern when they
     retain old fixed widths.

V0 can be conservative. It is better to return a small cluster and ask for one
more repair than to include unrelated nodes.

### Permission set

For `layout_cluster`, set:

```python
LAYOUT_CLUSTER_PERMISSIONS = [
    "modify_position",
    "modify_size",
    "modify_sizing_mode",
    "modify_auto_layout",
    "modify_padding",
    "modify_gap",
    "modify_wrap",
    "modify_clip",
    "modify_page_background",
    "convert_diagnosed_background",
]
```

Set prohibitions:

```python
LAYOUT_CLUSTER_PROHIBITIONS = [
    "do not delete pages",
    "do not re-declare existing pages",
    "do not delete unrelated nodes",
    "do not edit unrelated slots",
    "do not edit unrelated Brand Kit tokens",
    "do not replace unrelated assets",
    "do not regenerate the whole scene",
    "do not hide overflow with clipping unless the content also fits",
]
```

### Repair request payload

For a `layout_cluster`, `create_repair_request` should persist:

- target page;
- target parent/root;
- descendant IDs;
- background node ID if relevant;
- diagnostic codes;
- allowed operations;
- forbidden operations;
- exact diagnostic feedback;
- debug preview summary if available.

### Tests

Add unit tests for:

- cluster resolver finds page and parent for a child overflow;
- cluster resolver includes root frame for page overflow;
- background candidate detection identifies leaf background rect;
- background candidate detection keeps wrapper frame with children;
- unrelated siblings are not included.

## Slice 4: Cluster Repair Guard And Actuator

### Goal

Permit bounded multi-node repair without allowing destructive scene rewrite.

### Current behavior to preserve

Existing surgical repair rejection must still work:

- if the previous feedback says `surgical_repair`;
- and the author emits a non-modify DSL block;
- reject before compile;
- do not touch `tools.scene`.

### New behavior

Add `layout_cluster_repair` enforcement parallel to surgical enforcement.

In `loop.py`, before `compile_dsl_block(source)`:

```python
if repair_context and repair_context.get("repair_class") == "layout_cluster":
    if not is_layout_cluster_dsl(source, repair_context):
        reject unapplied and continue with cluster violation feedback
```

### DSL cluster guard

Implement:

```python
def is_layout_cluster_dsl(source: str, context: dict) -> bool:
    ...
```

Allowed line forms:

- blank lines;
- `// checkpoint` comments;
- `#page:<allowed_page_id> background(...)` or other allowed page property
  patches;
- `#<allowed_node_id> ...` modify lines;
- optional `delete(<background_node_id>)` only if:
  - background node ID exactly matches the diagnosed background node;
  - the repair request includes `convert_diagnosed_background`;
  - the delete line does not include unrelated IDs.

Rejected line forms:

- `page ...`;
- any element declaration;
- `delete(...)` for non-background nodes;
- `parent(...)`, `clone(...)`, `replace(...)`, `ungroup(...)` unless V0
  explicitly scopes and tests them;
- `#slot:...`, `#asset:...`, `#document` unless the repair class is not layout;
- any ID not in the allowed cluster.

### Structured edits preferred path

The better V0 path is to guide the author toward `apply_structured_edit` with
strict scope. Existing DeepAgent provider/tool wiring already exposes
`apply_structured_edit`; update repair instructions to prefer it when the repair
request has `repair_class = layout_cluster`.

Example scoped edit:

```json
{
  "kind": "modify",
  "target": { "kind": "node", "id": "card" },
  "patch": {
    "kind": "node",
    "value": {
      "size": { "width": { "kind": "set", "value": "fill" }, "height": { "kind": "set", "value": "hug" } }
    }
  },
  "scope": {
    "mode": "strict",
    "allowed": [
      { "kind": "page", "id": "appointment_card" },
      { "kind": "node", "id": "artboard_root" },
      { "kind": "node", "id": "card" },
      { "kind": "node", "id": "header" },
      { "kind": "node", "id": "divider" },
      { "kind": "node", "id": "cta" }
    ]
  }
}
```

Adjust this example to the actual structured-edit patch schema before putting it
in agent-facing knowledge. The planning invariant is the strict scope, not this
exact JSON.

### Background conversion actuator

Support three cases:

1. Page supports background patch:
   - use page patch to set `background`;
   - delete diagnosed leaf background rect only if allowed;
   - preserve semantic children.

2. Background node is a wrapper frame with children:
   - keep the frame;
   - resize it to page bounds;
   - set clip/layout/fill appropriately;
   - update children to fit/fill/hug;
   - do not delete the wrapper.

3. Page background patch is unsupported in structured edit:
   - use a page modify DSL line if supported;
   - otherwise record a gap and repair geometry without conversion.

### Tests

Add tests:

- non-cluster destructive repair is still rejected;
- layout-cluster DSL with only allowed `#` lines passes the guard;
- layout-cluster DSL with `page ...` is rejected;
- layout-cluster DSL with unrelated `#node` is rejected;
- layout-cluster DSL with unrelated delete is rejected;
- diagnosed leaf background delete is accepted only with permission;
- rejected cluster repair leaves `tools.scene` unchanged;
- successful cluster repair can touch multiple allowed nodes.

## Slice 5: Trace Evaluator Checks

### Goal

Make the run trace prove the branch solved the intended failure class.

### Files

Update:

- `apps/agent_runtime/lumen_deepagent/eval_traces.py`
- `apps/agent_runtime/evaluation/fixture_prompts.json`
- `apps/agent_runtime/tests/test_lumen_deepagent_runtime.py`

Possibly add:

- `apps/agent_runtime/evaluation/artboard_checks.py`

### Trace checks

Add structured checks over `final.json` and iteration payloads:

- `oversized_background_rect_count`;
- `parent_overflow_diagnostic_count`;
- `artboard_overflow_diagnostic_count`;
- `layout_cluster_repair_request_count`;
- `layout_cluster_repair_rejection_count`;
- `destructive_repair_rejection_count`;
- `whole_scene_regeneration_attempt_count`;
- `final_lumv080x_count`;
- `final_lumv090x_count`.

For trace payloads, inspect:

- `iterations/*/repair_request.json`;
- `iterations/*/dsl.lumen`;
- `iterations/*/compile.json`;
- `iterations/*/preflight.json` if present;
- final scene snapshot or final response payload.

### Oversized background heuristic

For final scene snapshots:

- inspect direct page children;
- if a leaf rect/frame has fill and size exceeds page bounds by tolerance, count
  as oversized;
- if a full-page background-like node exists and page background is empty, count
  as background-conversion warning;
- do not flag root artboard frames with children when they are exactly page sized
  and have layout/clip role.

### Parent overflow heuristic

Count final diagnostics:

- `LUMV0800`;
- `LUMV0801`;
- text fit errors where multiple nodes share one parent and no cluster repair was
  attempted.

### CLI output

Extend `summarize_trace_dir` with:

```json
{
  "layout_cluster_repairs": 2,
  "layout_cluster_rejections": 1,
  "oversized_background_rects": 0,
  "remaining_artboard_overflow": 0,
  "remaining_parent_overflow": 0
}
```

### Tests

Add deterministic fake trace directories and assert counts.

## Slice 6: Fixture Prompts

### Goal

Make the exit gate reproducible without relying only on live-provider runs.

### Files

Update:

- `apps/agent_runtime/evaluation/fixture_prompts.json`

Add fixtures:

1. `a4_appointment_card_artboard_frame`

   Prompt intent:

   ```text
   Create an A4 portrait appointment reminder card. Use canonical A4 layout
   points, a page/artboard background fill, a bounded root frame, auto-layout,
   and realistic patient/clinic/CTA copy.
   ```

   Expected:

   - page preset A4 portrait;
   - no child coordinates in `210 x 297`;
   - root frame approximately `595 x 842`;
   - no oversized bg rect;
   - no final `LUMV0800`/`LUMV0801`.

2. `letter_healthcare_one_pager`

   Expected:

   - `612 x 792` layout;
   - root frame or page background;
   - text wraps inside parent.

3. `linkedin_square_artboard_frame`

   Expected:

   - exact 1080 square;
   - no fake square inside another page.

4. `parent_overflow_cluster_repair`

   Deterministic test prompt or fake author setup that triggers:

   - parent card resized narrower;
   - descendants remain wide;
   - preflight emits `LUMV0801`;
   - repair request classifies as `layout_cluster`.

## Slice 7: Runtime Tests

### Test targets

Primary:

```bash
/Users/aryankeshri/Documents/brilliant-design/.venv/bin/python -m pytest apps/agent_runtime/tests/test_lumen_deepagent_runtime.py -q
```

When API wiring changes:

```bash
/Users/aryankeshri/Documents/brilliant-design/.venv/bin/python -m pytest apps/api/tests/test_api.py -q
```

Only run Phase G separately if touched:

```bash
/Users/aryankeshri/Documents/brilliant-design/.venv/bin/python -m pytest apps/api/tests/test_phase_g_conformance.py -q
```

Rust tests only if core edit operations or layout validation are changed:

```bash
cargo test -p lumen-core --test layout_engine
cargo test -p lumen-core --test editing
cargo test -p lumen-agent
```

Always run:

```bash
git diff --check
```

### Tests to add

In `apps/agent_runtime/tests/test_lumen_deepagent_runtime.py`:

- `test_lumv0800_routes_to_layout_cluster`
- `test_lumv0801_routes_to_layout_cluster`
- `test_single_text_overflow_stays_targeted_node`
- `test_multiple_sibling_text_overflows_escalate_to_layout_cluster`
- `test_layout_cluster_repair_request_carries_permissions_and_prohibitions`
- `test_layout_cluster_guard_rejects_page_redeclaration`
- `test_layout_cluster_guard_rejects_unrelated_node_modify`
- `test_layout_cluster_guard_allows_allowed_cluster_modify_lines`
- `test_background_conversion_delete_requires_diagnosed_background_permission`
- `test_rejected_layout_cluster_repair_does_not_touch_scene`
- `test_trace_summary_counts_layout_cluster_repairs`
- `test_trace_summary_flags_oversized_background_rect`

In Rust only if needed:

- page background structured edit support;
- scoped page patch plus node patch;
- scope rejection for out-of-cluster node mutation;
- background conversion operation batch inverse/undo behavior.

## Implementation Order

### Step 1: Knowledge docs first

This gives immediate value and clarifies the desired generated output before
runtime work.

Deliver:

- updated create-design guidance;
- updated layout recipes;
- updated diagnostics mapping for `LUMV080x`;
- new artboard-frame authoring doc if needed.

Verification:

```bash
git diff --check
```

### Step 2: Add schemas and pure classifier

Deliver:

- `RepairClass`;
- `LayoutClusterTarget`;
- classifier helper;
- tests for diagnostic mapping.

Verification:

```bash
/Users/aryankeshri/Documents/brilliant-design/.venv/bin/python -m pytest apps/agent_runtime/tests/test_lumen_deepagent_runtime.py -q
```

### Step 3: Add cluster resolver

Deliver:

- resolve page/parent/root/background cluster from scene;
- conservative inclusion rules;
- tests with fake scene dictionaries.

Verification:

```bash
/Users/aryankeshri/Documents/brilliant-design/.venv/bin/python -m pytest apps/agent_runtime/tests/test_lumen_deepagent_runtime.py -q
```

### Step 4: Wire repair request payloads

Deliver:

- preflight failure path persists `layout_cluster` payload;
- visual critique path persists `layout_cluster` payload when clipping/overflow
  is cluster-level;
- compile repair path preserves prior class during repair attempts;
- trace payloads expose class/cluster.

Verification:

```bash
/Users/aryankeshri/Documents/brilliant-design/.venv/bin/python -m pytest apps/agent_runtime/tests/test_lumen_deepagent_runtime.py -q
```

### Step 5: Add cluster guard

Deliver:

- `is_layout_cluster_dsl`;
- violation feedback;
- pre-compile rejection;
- best-scene preservation unchanged.

Verification:

```bash
/Users/aryankeshri/Documents/brilliant-design/.venv/bin/python -m pytest apps/agent_runtime/tests/test_lumen_deepagent_runtime.py -q
```

### Step 6: Add trace evaluator checks

Deliver:

- trace summary counts;
- fake trace tests;
- fixture prompt metadata.

Verification:

```bash
/Users/aryankeshri/Documents/brilliant-design/.venv/bin/python -m pytest apps/agent_runtime/tests/test_lumen_deepagent_runtime.py -q
```

### Step 7: Integration pass

Run narrowed test suites:

```bash
/Users/aryankeshri/Documents/brilliant-design/.venv/bin/python -m pytest apps/agent_runtime/tests/test_lumen_deepagent_runtime.py -q
/Users/aryankeshri/Documents/brilliant-design/.venv/bin/python -m pytest apps/api/tests/test_api.py -q
git diff --check
```

Do not run broad API or browser suites repeatedly while iterating. Use the
narrow agent-runtime test first, then the API test only after helper/API shape is
affected.

## Detailed Runtime Design

### New classification helper

Recommended module:

```text
apps/agent_runtime/lumen_deepagent/repair.py
```

Suggested functions:

```python
def classify_diagnostics(
    diagnostics: list[dict],
    target: dict,
    *,
    scene: dict,
    prior_context: dict | None = None,
) -> RepairClassification:
    ...

def resolve_layout_cluster(
    scene: dict,
    diagnostics: list[dict],
    target: dict,
) -> LayoutClusterTarget:
    ...

def is_layout_cluster_dsl(source: str, context: dict) -> bool:
    ...

def layout_cluster_violation_feedback(prior: dict, rejected_source: str) -> dict:
    ...
```

Keep these pure and unit-testable. Avoid coupling them to provider calls.

### RepairClassification shape

If adding a Pydantic model is useful:

```python
class RepairClassification(BaseModel):
    repair_class: RepairClass
    target: Optional[VisualTarget] = None
    cluster: Optional[LayoutClusterTarget] = None
    allowed_edit_surface: EditSurfaceRecommendation
    permissions: List[str] = Field(default_factory=list)
    prohibitions: List[str] = Field(default_factory=list)
    reason: str
```

### Loop integration

Replace ad hoc surgical detection with:

```python
classification = classify_diagnostics(
    preflight_summary.get("diagnostics", []),
    target,
    scene=self.tools.scene,
    prior_context=block_request.repair_context,
)
```

Then:

- if `classification.repair_class == targeted_node`, preserve current surgical
  flow;
- if `classification.repair_class == layout_cluster`, use cluster flow;
- otherwise use existing edit-surface recommendation behavior.

Do not regress the current `LUMA0200` guard.

### Repair request fields

For every repair request, include:

```json
{
  "repair_class": "...",
  "target": { "...": "..." },
  "cluster": { "...": "..." },
  "permissions": [],
  "prohibitions": [],
  "allowed_edit_surface": "structured_ops"
}
```

For backward compatibility, keep:

- `forbidden_changes`;
- `target`;
- `allowed_edit_surface`.

### Authoring constraints

Add:

```python
LAYOUT_CLUSTER_AUTHORING_CONSTRAINTS = [
    "This is a BOUNDED LAYOUT CLUSTER repair.",
    "You may edit only the named page/root/parent/descendant IDs in the cluster.",
    "You may modify p/s, fill/hug/fixed sizing, auto-layout, padding, gap, wrap, clip, and page background when permitted.",
    "You may convert only the diagnosed background node into page/artboard fill.",
    "Do not emit page declarations, unrelated node declarations, or whole-scene replacements.",
    "Do not delete pages, unrelated nodes, slots, Brand Kit tokens, or assets."
]
```

### Violation feedback

Should be as specific as surgical violation feedback:

```text
Your previous layout_cluster repair was rejected and not applied. It attempted
to edit outside the allowed cluster or re-author the page. Only modify the
allowed page/node IDs: ...
```

Include rejected source snippet and cluster target in trace payload.

## Core Operation Considerations

This branch is primarily agent runtime. Touch Rust core only when the runtime
cannot express a required bounded edit through existing operations.

Check before modifying core:

- Can `apply_structured_edit` patch page background?
- Can it patch node layout fields needed for `p`, `s`, `al`, `pad`, `gap`,
  `wrap`, and `clip`?
- Can scope include both page and node targets?
- Can a scoped batch apply multiple edits?

If not, add the minimum core support:

1. Extend `editing.rs` patch builder for missing page/node fields.
2. Add scope checks for page plus node clusters.
3. Add tests in `crates/lumen-core/tests/editing.rs`.
4. Confirm inverse/undo operation generation remains valid.

Avoid adding a general "auto repair layout" engine in Rust for V0. The runtime
classification and bounded edit plan are enough.

## Branch Exit Gate

The branch can be considered ready when:

- Knowledge docs teach point-based artboard-local authoring.
- New recipes use page background/root frame patterns.
- `LUMV0800` and `LUMV0801` classify as `layout_cluster`.
- `layout_cluster` repair requests carry cluster IDs, permissions, and
  prohibitions.
- The runtime rejects layout-cluster repairs that re-declare pages or touch
  unrelated IDs.
- Trace summary can flag oversized backgrounds and parent overflow.
- Deterministic tests prove the appointment-card failure class is routed to
  cluster repair.
- No browser/Playwright smoke was run unless explicitly requested.

## Verification Commands

Primary loop:

```bash
/Users/aryankeshri/Documents/brilliant-design/.venv/bin/python -m pytest apps/agent_runtime/tests/test_lumen_deepagent_runtime.py -q
git diff --check
```

If API contracts changed:

```bash
/Users/aryankeshri/Documents/brilliant-design/.venv/bin/python -m pytest apps/api/tests/test_api.py -q
```

If Phase G integration changed:

```bash
/Users/aryankeshri/Documents/brilliant-design/.venv/bin/python -m pytest apps/api/tests/test_phase_g_conformance.py -q
```

If Rust core edit/layout changed:

```bash
cargo test -p lumen-core --test editing
cargo test -p lumen-core --test layout_engine
cargo test -p lumen-agent
```

If only docs changed:

```bash
git diff --check
```

## Documentation Completion Tasks

At the end of the implementation branch:

1. Update this implementation plan with completed/deferred sections.
2. Update branch memory:

   ```text
   /Users/aryankeshri/Documents/brilliant-design/.codex/memory/workstreams/agents-artboard-frame-generation-v0.md
   ```

3. Record:
   - durable contract changes;
   - new repair request shape;
   - tests run;
   - downstream implications for `editor/infinite-workspace-v0` and future
     visual/browser validation.

## Risks

### Risk: cluster repair becomes whole-scene regeneration

Mitigation:

- pre-compile guard;
- explicit allowed IDs;
- strict structured-edit scope;
- trace rejected attempts;
- keep `best_scene` preservation.

### Risk: background conversion deletes semantic content

Mitigation:

- delete only diagnosed leaf background nodes;
- wrapper frames with children are converted into root frames, not deleted;
- scope tests cover both cases.

### Risk: text repair and layout repair fight each other

Mitigation:

- single text diagnostic remains `targeted_node`;
- shared-parent or repeated text diagnostics escalate to `layout_cluster`;
- traces record escalation reason.

### Risk: docs teach syntax the compiler does not support

Mitigation:

- verify page background syntax before updating examples;
- if unsupported, use page modify form or root-frame fill fallback;
- add knowledge tests that compile representative snippets if practical.

### Risk: browser/editor appearance remains unverified

Mitigation:

- do not claim browser/editor smoke as complete in this branch;
- keep acceptance focused on agent runtime, diagnostics, and trace behavior;
- defer rendered editor validation to a future Codex Browser plugin session.
