# Subsystem map: Hit-testing, Bindings & Slots

Scope: `crates/lumen-core/src/hit_test.rs`, `binding.rs`, `slots.rs`, plus the
supporting machinery they depend on (`scene.rs`, `brand.rs` token resolver,
`editing.rs`/`operations.rs` patch model, `layout.rs` managed/freehand boundary,
`instance.rs` slot text application) and the editor surface
(`apps/editor/src/components/InspectorPanel.tsx`, `engine/operations.ts`).

Throughout: **EXISTS** = present in code today; **MISSING** = not implemented;
**INFERENCE** = my reasoning, labeled as such.

---

## 1. Hit-testing (`hit_test.rs`) — point → node

### How picking works (EXISTS)
- Entry points: `hit_test(scene, page_id, x, y) -> Option<NodeId>` returns the
  **topmost** hit (single-click target); `hit_stack(...) -> Vec<NodeId>` returns
  every node under the point in **paint order (bottom-to-top, `.last()` = topmost)**
  for drill-in / cycle-through-overlapping. `hit_test.rs:26-42`.
- The walk is a recursive pre-order `collect` over `page.children` then each
  node's `children`. The parent is pushed **before** its children (paint order),
  so deeper/later nodes end up later in the vector and win as "topmost".
  `hit_test.rs:44-64`.
- Geometry source is `render_box_for_node(node, None)` — the **same boxes the
  renderer draws**, derived from `node.computed` when present, else from
  `transform.x/y` + `size`. `hit_test.rs:67`, `render_geometry.rs:22-45`.
  This is the crux: **hit-testing reads `computed` (solver output), not the
  authored transform.** If layout has not run, it falls back to raw transform.

### Z-order and containers vs leaves (EXISTS)
- Z-order is purely **tree order** (document order within a parent's `children`
  Vec, pages iterated, then depth-first). There is no explicit z-index field; the
  vector position in `children` is the only stacking signal. `hit_test.rs:37-63`.
- Containers (`Frame`/`Group`/`AutoLayout`) are hit like any node when the point
  is inside their own box, and recursion into children is independent of whether
  the parent was hit — children may extend beyond the parent unless clipped.
  `hit_test.rs:56-63`.
- **Clip optimization**: `if node.clip && !inside { return; }` — a clipped
  container whose box the point misses prunes itself and all descendants.
  `hit_test.rs:51-53`.
- Shape-accurate tests: `Ellipse` uses the normalized ellipse equation
  (`hit_test.rs:98-107`); `Line` uses point-to-segment distance with tolerance =
  `half_stroke + LINE_PICK_SLOP(2.0)` (`hit_test.rs:21,110-127`); everything else
  (rect/frame/group/auto-layout/**text/image/vector/instance**) uses the rotated
  bounding box (`hit_test.rs:71-85`). Rotation is honored about the node origin
  via `to_local` (`hit_test.rs:89-96`). **Skew/flip, alpha-accurate raster, and
  true vector path-fill are explicitly V0 follow-ups** (file header `:10-13`,
  `:74-75`).

### What hit-testing knows about bindings/slots (MISSING)
- **Hit-testing is binding-/slot-blind.** It operates only on `NodeKind` and
  `computed`/`transform` geometry. It has no awareness of whether a node is
  slot-bound, token-bound, or a repeater template. Selection returns a raw
  `NodeId`; any "this is a managed region" semantics must be layered on top by
  the editor.

### Editor plumbing on top of hit-testing (EXISTS)
- WASM exposes `Engine::hit_test(page_id, x, y)` which calls `hit_stack` and
  returns a JSON stack. `crates/lumen-wasm/src/engine.rs:352-356`.
- The editor's `WasmEngine.hitTest` parses that into a `HitResult`
  (`apps/editor/src/engine/wasmEngine.ts:225-226`). Double-click container
  targeting walks up via `topLevelAncestorId(scene, nodeId)`
  (`apps/editor/src/engine/sceneQueries.ts:150`), referenced in the
  `hit_test.rs` doc-comment as `topLevelAncestorId` (`hit_test.rs:24-25`).

---

## 2. Bindings (`binding.rs`) — TWO DISTINCT MEANINGS

This is the single biggest clarity trap in the codebase: the word "binding"
refers to **two completely different mechanisms**.

### 2a. Token bindings (the thing the prompt means by `$space.lg`, `$type.headline`, `$color.*`) — NOT in binding.rs
Token bindings are **fields on the scene node itself**, resolved by the
`TokenResolver` in `brand.rs`. They are the heart of "managed vs freehand".

**Where token references live on a node** (`scene.rs`):
- Size: `Dimension::Token { token }` for `size.width` / `size.height`. `scene.rs:543-550`.
- Fill/stroke color: `Paint::Token { token }` or `Color::Token { token }` inside a
  `Paint::Solid`/gradient stop. `scene.rs:651-672`.
- Stroke width: `Stroke.width_token: Option<String>`. `scene.rs:563-564`.
- Corner radius: `CornerRadii.token: Option<String>`. `scene.rs:680-681`.
- Opacity: `Node.opacity_token: Option<String>`. `scene.rs:285-286`.
- Auto-layout gap/padding: `AutoLayoutProps.gap_token` / `padding_token`. `scene.rs:473-477`.
- Text typography: `TextNode.style_token` (role, e.g. `$type.headline`),
  `font_size_token`, `line_height_token`, `letter_spacing_token`; the font family
  can itself be a token ref (`looks_like_token_ref`). `scene.rs:361-370`, `brand.rs:2259`.

**How a node "references" a token**: the literal field holds the resolved value
*and* a sibling `*_token: Option<String>` (or the field itself is a
`Token`/`Dimension::Token`/`Color::Token` variant) holds the token path string,
e.g. `"space.lg"`, `"type.headline"`, `"surface.primary"`. The catalog of valid
tokens is grouped by domain: `surface.*`, `text.*`, `border.*`, `focus.*`,
`type.*`, `space.*`, `radius.*`, `stroke.width.*`, `opacity.*`, `logo.*`,
`asset.*`. `brand.rs:2127-2164`, `summarize_brand_kit_for_authoring`.

**`collect_scene_token_references`** (`brand.rs:2178-2271`) enumerates exactly
which node properties are token-bound — this is the authoritative inventory of
"managed" fields: page background paints, node size w/h, every fill paint, every
stroke paint + stroke width, corner radius, opacity, layout gap/padding, text
style + font-family-as-token.

#### Token resolution is DESTRUCTIVE (CRITICAL, EXISTS)
`TokenResolver::resolve_node` (`brand.rs:3405-3534`) **replaces token variants
with literal values and clears the token field**:
- `Dimension::Token` → `Dimension::Fixed(width)` (`brand.rs:3424-3437`).
- `Color::Token`/`Paint::Token` → `Paint::Solid { color: <resolved hex/oklch> }`
  (`brand.rs:3559-3583`).
- `stroke.width = width; stroke.width_token = None;` (`brand.rs:3414-3421`).
- `node.corner = CornerRadii { ..radius, token: None }` (`brand.rs:3439-3451`).
- `node.opacity = opacity; node.opacity_token = None;` (`brand.rs:3453-3460`).
- `layout.gap = gap; layout.gap_token = None;` (and padding) (`brand.rs:3536-3553`).
- Text: `text.style_token = None;` after baking family/size/weight/color into the
  literal fields and `text.font_size_token = None;` etc. (`brand.rs:3484-3532`).

  **Resolution order matters for text**: the role (`style_token`) is applied
  first (sets family/size/weight/color), THEN `font_size_token` overrides size
  (`brand.rs:3521-3532`). The role's resolved color is even contrast-corrected
  against the node's surface (`brand.rs:3498-3518`).

**Where resolution runs (and where the tokens survive)** — INFERENCE +
EXISTS: `resolve_scene_tokens` clones the scene and returns a *separate*
resolved scene (`brand.rs:2358-2378`); it does not mutate in place. It is called
from `preflight.rs:145` (preflight pipeline) and from tests. The **editor edits
the token-bearing scene** (`Engine.scene` in `lumen-wasm/src/engine.rs`); the
inspector explicitly says "Token choices are stored on the scene and resolved by
preflight" (`InspectorPanel.tsx:576`) and "resolved by preflight"
(`InspectorPanel.tsx:490`). So the live editing document **retains tokens**;
resolution to literals happens downstream in preflight/export. This is the design
that makes managed editing possible at all.

#### Raw color/size pick → literal override that BREAKS the binding (CRITICAL, EXISTS)
When a human picks a raw value in the inspector, the editor **does not annotate
or co-store** — it replaces the field with a literal, dropping the token:
- Raw Fill Color: `updateNodeFills(node, [solidFill(id, "fill", hex)])` — replaces
  the whole `fills` array with a single `Paint::Solid{Color::Hex}` literal,
  discarding any `Paint::Token`. `InspectorPanel.tsx:381-386`, builder
  `engine/operations.ts:274-282` (`fills: set(fills)`).
- Token Fill: `updateNodeFills(node, [tokenFill(id, "fill", token)])` — replaces
  with `Paint::Token`. `InspectorPanel.tsx:498-503`.
- These two controls are **mutually exclusive on the same field**: picking raw
  overwrites the token-fill and vice-versa. There is no "literal value + remember
  the token it came from" representation.
- Opacity has both a raw slider (`opacity: set(value)`,
  `InspectorPanel.tsx:283-293`) and a token select that sets/clears
  `opacity_token` (`InspectorPanel.tsx:559-569`). **But the raw opacity slider
  does NOT clear `opacity_token`** — see "stale token" hazard below.

So: **a human raw-color/size pick creates a literal that BREAKS (replaces) the
binding** for paints (because the whole `Paint` variant changes), but for
the `*_token` sibling fields (opacity, stroke width, corner, gap/padding, text
style) **the literal and the token can coexist in an inconsistent state** unless
the editor explicitly clears the token.

#### Stale-token hazard (CRITICAL, EXISTS — likely a latent bug for human editing)
`update_node` / `apply_text_edit_patch` apply literal and token fields
independently and **never auto-clear** the sibling token:
- `operations.rs:556-597` `update_node` applies each field via
  `apply_field_patch` / `apply_optional_patch` with no cross-field invalidation.
- `editing.rs:2071-2087` `apply_text_edit_patch` sets `font_family`/`font_size`
  and applies `style_token` as **separate** patches.
- Editor `updateTextNode(node, { font_family })` spreads `{...node.kind, ...text}`
  and **leaves `style_token` intact** (`engine/operations.ts:340-354`; inspector
  font-family `onChange` at `InspectorPanel.tsx:722-724`).

Consequence (INFERENCE, well-supported): if a human sets a raw `font_size`/
`font_family`/`opacity`/`gap` while a token is still present, the value looks
right in the editor, but the **next preflight resolution re-applies the token and
clobbers the human's literal** (e.g. `text.font_size = role.size`,
`node.opacity = resolved`, `brand.rs:3453-3532`). To make a literal "stick"
against a managed field, the editor must also send the matching `*_token: clear()`
— which the opacity token select does (`InspectorPanel.tsx:569`) but the raw
slider/font inputs do not. This is the single most important managed-editing
correctness gap for the round-trip.

### 2b. Binding sets (`binding.rs`) — instance/recipient data, NOT human editing
`binding.rs` is **Phase G personalization**: per-recipient *content* injected at
instance-derivation time. It is unrelated to the human-editing layer except that
it defines how slots receive values.
- `BindingSet` = `{ schema_version, binding_set_id, template_revision_id,
  audience, values: BTreeMap<String, BoundValue>, links, generated }`.
  `binding.rs:18-32`.
- `BoundValue` is `Text{value} | Asset{asset_id} | List{items}` — kind-tagged to
  match a slot's `ContentType`. `binding.rs:45-71`.
- It is **data, never operations**: "instances derive from finalized snapshot +
  binding set + asset store, never op-log replay." File header `binding.rs:1-9`.
- A binding set targets a **finalized** template revision; `validate_binding_set`
  rejects a draft (`LUMG0001`) and revision mismatch (`LUMG0002`).
  `binding.rs:237-279`.
- Validation walks the scene's slots: keys must resolve (`LUMG0010`), value kind
  must match `ContentType` (`LUMG0011`), required slots must be covered
  (`LUMG0012`), cardinality (`LUMG0013`), `max_length` (`LUMG0014`), conditional
  grammar parses, generated specs chain `links.*.url -> qr provider -> UrlQr slot`.
  `binding.rs:237-405`, `validate_value_against_slot:407-543`.
- **Frozen conditional grammar** (V0): only `has(slot_key)`, `missing(slot_key)`,
  `eq(slot_key,"literal")` — no general expression language. `binding.rs:118-211`.

**Implication for human editing**: binding sets only matter post-finalization, for
agent/templated personalization. A human editing a *draft* design never touches
binding sets. But they constrain the **slot contract** a human can break (see §3).

---

## 3. Slots (`slots.rs`) — managed content fixtures

### What a slot is (EXISTS)
A `Slot` (`slots.rs:4-23`) is a **named, typed, validated content region** that
points at one or more scene nodes:
- `key: SlotKey` (dotted, e.g. `research.quote`), `label`, `content_type`
  (`ContentType`: `TextShort/TextLong/RichTextLimited/NumberStat/Date/Image/Logo/
  UrlQr/List/RepeaterGroup/TableLike`, `slots.rs:49-63`).
- `bound_nodes: Vec<NodeId>` — the scene nodes this slot governs. `slots.rs:11`.
- `scope: SlotScope` (`Document/Page/Node/Group`), `required`, `placeholder`.
- `overflow: OverflowPolicy` (`ShrinkFont/Wrap/Clip/Ellipsis/ExpandContainer/
  Error/AskAgentToRepair`, `slots.rs:74-89`).
- `formatting` (`max_length`, `allowed_pattern`, `preserve_case`), `cardinality`,
  `conditional`, `repeater`, `image_policy`, `editability`, `binding_hints`.
- **`validation: ValidationFixtures { samples: Vec<String>, worst_case:
  Option<String>, max_length }`** — these are the slot **fixtures**: example
  content (`samples`) and a stress string (`worst_case`) used to validate layout
  fit before real data arrives. `slots.rs:156-161`.
- **`editability: Editability`** — `TemplateOnly / InstanceOnly /
  TemplateAndInstance / LockedAfterFinalization`. `slots.rs:186-193`. This is the
  closest thing to a per-slot permission flag for who may edit.

### Slot ↔ node relationship (EXISTS)
- `Scene.slots_for_node(node_id)` and `bound_nodes_for_slot(slot_id)` cross-walk
  the relationship (`scene.rs:104-120`). The link is **`slot.bound_nodes`**, kept
  on the slot, not on the node — a node has no back-pointer to its slot.
- Binding/unbinding is done by dedicated operations `BindNodeToSlot` /
  `UnbindNodeFromSlot` (`operations.rs:184-191`), and via `SlotEditPatch`
  (`bind_nodes`/`unbind_nodes`, plus `sample`/`worst_case` fixture edits) in
  `editing.rs:619-629`. It is **not** part of `NodePatch` — moving/editing a node
  never implicitly changes its slot membership.

### How slot-bound text differs from free text (CRITICAL, EXISTS)
- A free text node's `content` is authored DSL/editor text and is the source of
  truth.
- A slot-bound text node's `content` is **overwritten at instance-derivation
  time**: `apply_text_to_slot` clones the node's `TextNode`, sets
  `next.content = <bound value / placeholder / fallback>`, and emits an
  `UpdateNode` op. `instance.rs:733-762`. So for slot-bound nodes, the human's
  typed text in the template is just a *fixture*; the real text comes from the
  binding set / sample at derivation.
- Conditional behavior can **hide** the region, keep the **placeholder**, or
  substitute a **fallback** (`EmptyBehavior::HideRegion/PreservePlaceholder/
  UseFallback`, `slots.rs:129-136`; applied in `instance.rs:289-456`).
- Overflow handling (shrink-font/wrap/clip/ellipsis/expand/error/ask-agent) is a
  slot-level policy, not a node-level one (`slots.rs:74-89`).

**Implication**: a human editing the *visible text* of a slot-bound node in a
template is editing a fixture that may be replaced. The durable human edit on a
slot-bound node is to its **style/geometry**, not its `content`.

---

## 4. The "managed vs freehand" property inventory

| Property | Managed by | Token field | Solver-owned? | Human literal override exists? |
|---|---|---|---|---|
| Position (x,y) inside Frame/Group | stored `transform.x/y` (NOT solved) | — | No (freehand-ish today) | Yes — `transform: set(...)` |
| Position inside AutoLayout | **solver (Taffy)** | — | **Yes** | No — transform ignored unless rotated/skewed (opts child out, `layout.rs:264-280`) |
| Size (fixed) | `Dimension::Fixed` | — | partly (fill/hug solved) | Yes |
| Size (hug/fill) | **solver** | `Dimension::Token` for token sizes | **Yes** | switch to `fixed` |
| Fill / stroke color | literal `Paint::Solid` or `Paint::Token` | yes (Token variant) | No | Yes — replaces whole paint, breaks token |
| Stroke width | literal + `width_token` | yes | No | Yes (token can go stale) |
| Corner radius | literal + `corner.token` | yes | No | Yes (token can go stale) |
| Opacity | literal + `opacity_token` | yes | No | Yes (raw slider does NOT clear token — stale) |
| Gap / padding | literal + `gap_token`/`padding_token` | yes | feeds solver | Yes (token can go stale) |
| Text font family/size/weight | literal + `style_token`/`font_size_token` | yes | feeds text-measure → solver | Yes (does NOT clear style_token — stale) |
| Text content (free) | literal `content` | — | No | Yes |
| Text content (slot-bound) | **slot/binding at derivation** | — | overwritten | Edit is a fixture only |
| Slot membership | `slot.bound_nodes` | — | n/a | via Bind/Unbind ops only |

Key boundary (EXISTS): **the FLEX solver only governs the subtree under an
`AutoLayout` node.** Children of `Frame`/`Group`/page are positioned by their
**stored `transform.x/y`** (`layout.rs:137-192`), i.e. they are *already*
freehand. The solver writes `computed: ComputedGeometry { layout_bounds,
render_bounds }` (`scene.rs:704-708`, written in `layout.rs:330`/`write_geometry`)
which hit-testing and rendering then read.

---

## 5. Editing implications & round-trip

### 5a. What EXISTS that helps human editing
- A clean, geometry-faithful **hit-test** that matches the renderer and honors
  rotation/clip/ellipse/line — adequate for picking in both modes today
  (`hit_test.rs` entirely).
- A **dual positioning model already in the scene**: `transform.x/y` (stored,
  freehand) vs `computed` (solved). Frame/Group children are *already* absolutely
  positioned by transform; only AutoLayout subtrees are solver-managed
  (`layout.rs:137-192` vs `:195-242`). **INFERENCE**: "freehand mode" can largely
  be expressed as *placing/keeping a node under a non-AutoLayout parent (or page)
  and writing its `transform`* — the representation already exists.
- A **token layer that survives in the live editing scene** and is only resolved
  to literals downstream at preflight (`InspectorPanel.tsx:490,576`;
  `brand.rs:2358` clones rather than mutates). So "managed editing" (keep the
  token, change which token) is already possible: token selects emit
  `Paint::Token`/`*_token` writes.
- Both **raw and token controls already exist** in the inspector side-by-side
  (`InspectorPanel.tsx:376-575`), so the UI affordance for "literal override vs
  managed token" is partly built.
- Idempotent relayout: re-laying out an already-laid-out scene leaves unedited
  nodes unchanged, so an edit only perturbs the node it touched
  (`lumen-wasm/src/engine.rs:122-140`).

### 5b. What is MISSING / hazardous for human editing
- **No "literal override that remembers its token" representation.** Picking a raw
  color *destroys* the token (whole `Paint` variant swap,
  `InspectorPanel.tsx:381-386`). For `*_token` sibling fields, a literal and a
  token can silently coexist; **nothing invalidates the stale token**
  (`operations.rs:556-597`, `editing.rs:2071-2087`). After preflight, the stale
  token wins and clobbers the human literal (`brand.rs:3405-3534`). This is the
  prior-attempt failure mode echoed at the *style* layer (the prompt notes it at
  the *layout* layer).
- **No node→slot back-reference and no slot/binding awareness in hit-test or
  selection.** The editor cannot cheaply tell "is this node managed by a slot?"
  at pick time without scanning `slot.bound_nodes` (`scene.rs:104-109`).
- **AutoLayout children have no per-child escape hatch** other than rotating/
  skewing them out of flow (`layout.rs:264-280`). There is no
  `position: absolute`/`out_of_flow` boolean. So "freehand-move a node that lives
  inside an auto-layout stack" is not representable without reparenting it out of
  the AutoLayout or abusing rotation — a real gap for FREEHAND mode.
- **Hit-test depends on `computed`.** In freehand mode where the user drags before
  a relayout, picking would need the transform fallback path
  (`render_geometry.rs:38-44`) to be consistent — fine for non-auto-layout, but a
  half-solved auto-layout subtree could mis-pick. (INFERENCE.)
- **Slot-bound text edits are non-durable**: a human retyping a slot-bound node's
  text edits a fixture that derivation overwrites (`instance.rs:758-759`). The
  editor has no signal that this content is volatile.

### 5c. Round-trip (human freehand edit → agent resumes) — assessment
The agent edits the **token-bearing draft scene** through the same operation/
structured-edit channel the editor uses (`lumen-wasm/src/engine.rs:183-258`,
`build_structured_edit_batch`). So in principle a human edit and an agent edit are
homogeneous: both are `Operation`/`EditBatch` mutations of the same `Scene`. The
representation is **shared and serializable** (`scene_json`,
`engine.rs:174-176`), which is the foundation a round-trip needs.

What makes the round-trip *hard*, with evidence:
1. **Lossy literal overrides.** Once a human breaks a token (raw color) or leaves a
   stale token, the scene no longer records the design *intent* the agent reasons
   about ("this is `surface.primary`"). The agent sees only a hex literal (or a
   literal+stale-token contradiction). Re-deriving intent from a literal is the
   round-trip's core representational gap. **MISSING**: a provenance/override record
   ("user pinned this literal; ignore the token" vs "user re-chose token X").
2. **Reparent / relative→absolute changes are representable but unmarked.** Moving a
   node out of an AutoLayout via `MoveNode` (`operations.rs:505-554`) is a valid op
   and round-trips structurally, but nothing marks the node as "user-pinned
   freehand," so an agent relayout/repair could legitimately try to re-stack it.
   There is no "frozen by human" flag — the only related field is `Node.locked`
   (`scene.rs:294`) and slot-level `Editability::TemplateOnly/LockedAfterFinalization`
   (`slots.rs:186-193`), neither of which the layout solver consults.
3. **Slot contract drift.** If a human deletes/reparents a slot-bound node, the
   slot's `bound_nodes` can dangle (the binding validators flag missing nodes, e.g.
   `instance.rs` warnings, but nothing repairs the slot automatically).

### 5d. Concrete representation recommendations (INFERENCE, for architects)
- Add an explicit **override/provenance** field per managed property: keep BOTH the
  token and the literal, plus a `pinned: bool` (or `source: Token|UserLiteral|
  AgentLiteral`). This lets the resolver skip pinned fields (fixing the stale-token
  clobber) and lets the agent see "this was a human override of `surface.primary`."
  Minimal version: make raw-edit operations *also* clear the matching `*_token`
  (cheap, fixes the silent-clobber bug) — but that *loses* intent for the agent.
- Add an explicit **out-of-flow / freehand flag** on nodes (or reuse the
  rotated-child exclusion as the formal mechanism) so a node can sit inside an
  AutoLayout but keep its `transform`, instead of forcing reparenting. The solver
  already has the exclusion branch (`layout.rs:264-280`) to generalize.
- Have the layout solver / agent repair **respect `Node.locked`** and a new
  freehand flag, so human-pinned geometry is not re-stacked on the next repair.
- Give nodes a cheap **slot back-reference** (or precomputed index) so selection
  can show "managed by slot X (editability=...)" and warn before a volatile edit.

### 5e. Realistic scope (INFERENCE)
- **Cheap / high-value first step**: fix the stale-token clobber (raw edits clear or
  pin the token) and respect `locked` in repair. This alone removes the "edits fight
  the resolver" failure at the style layer.
- **Medium**: introduce the `pinned`/provenance field and an out-of-flow flag; teach
  the resolver and layout to honor them. This is the representation that genuinely
  enables the round-trip.
- **Larger**: slot-aware selection + slot repair (auto-rebind dangling slots, mark
  slot-bound content volatile in the UI), and true freehand mode (escape AutoLayout
  per-node). Hit-testing itself needs only minor work (skew/flip, alpha raster,
  vector path-fill) and is not the bottleneck.

---

## Appendix: file:line index
- Hit-test core: `crates/lumen-core/src/hit_test.rs:26,34,44,51,56,67,89,98,110,124`
- Render box (computed vs transform): `crates/lumen-core/src/render_geometry.rs:22-45`
- Scene node + token fields: `crates/lumen-core/src/scene.rs:268-296,343-371,460-497,543-682`
- Token reference inventory: `crates/lumen-core/src/brand.rs:2178-2271`
- Destructive token resolution: `crates/lumen-core/src/brand.rs:3405-3583`
- resolve_scene_tokens (clones scene): `crates/lumen-core/src/brand.rs:2338-2379`
- Binding sets (Phase G): `crates/lumen-core/src/binding.rs:18-71,237-405`
- Frozen conditional grammar: `crates/lumen-core/src/binding.rs:118-211`
- Slot definition + fixtures + editability: `crates/lumen-core/src/slots.rs:4-23,49-63,156-193`
- Slot↔node walk: `crates/lumen-core/src/scene.rs:104-120`
- Slot text overwrite at derivation: `crates/lumen-core/src/instance.rs:733-762`
- NodePatch / update_node (no cross-field token clear): `crates/lumen-core/src/operations.rs:103-126,556-597`
- move_node (reparent, cycle guard): `crates/lumen-core/src/operations.rs:505-554`
- Structured text patch (token independent of literal): `crates/lumen-core/src/editing.rs:527-595,2071-2087`
- Managed/freehand layout boundary: `crates/lumen-core/src/layout.rs:137-192,195-242,264-280,330`
- Editor inspector raw vs token controls: `apps/editor/src/components/InspectorPanel.tsx:283-293,376-575`
- Editor operation builders: `apps/editor/src/engine/operations.ts:274-354`
- WASM hit_test / edit channel: `crates/lumen-wasm/src/engine.rs:122-140,174-258,352-356`
