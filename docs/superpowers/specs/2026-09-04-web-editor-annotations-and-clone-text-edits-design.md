# Web editor: element annotations, human names, and text edits inside clones — design

**Status:** design ratified in discussion with the founder, 2026-09-04. Implementation plan:
`docs/superpowers/plans/2026-09-04-web-editor-annotations-and-clone-text-edits.md`.

**Founder rulings captured here (2026-09-04):**

- R-A1 — Single click in Edit mode opens a comment box on the element; when the element is text
  the box also offers an **Edit text** quick action. Double click on text opens inline editing.
- R-A2 — The comment box has two buttons: **Add** (primary: store the annotation as a chip) and
  **Send to chat** (store and submit immediately).
- R-A3 — Annotations are **session-only**: they live in the composer until sent or removed. A
  reload or document switch drops them. The sent turn's context refs are the durable record.
- R-A4 — Hover and chip labels show the **tag plus a meaningful name** (slot name inside a clone,
  node kind or copy for vocabulary nodes), never the raw selector or class list.
- R-A5 — The layers panel shows the same **human display names**, never raw `sec_…` / `frg_…` ids.
- R-A6 — **D-F3 is amended.** A cloned section's human-editable surface is its slot values AND a
  per-node **text-override map**: element path → text + bold/italic/underline + a size step on the
  theme's type ramp. The artifact stays immutable; the override is an ordinary reversible
  operation; the agent reads overrides as facts.

---

## 1. Why

The web editor today lets the agent change anything and lets a human move a clone up or down,
rebind its slot values, and rich-text-edit vocabulary text nodes. Two things a marketer reaches
for constantly are missing:

1. **Pointing at something and saying what to change.** The ad lane already has "edit targets"
   (select nodes → chips → `design_node` context refs → focused edit), but the web lane has it
   switched off and the chip carries no comment. The web agent already accepts scoped targets
   (`WebTurnRequest.target_node_ids` → a TURN TARGET paragraph in its prompt), but the platform
   never fills it for web turns.
2. **Fixing a word.** Inside a cloned band nothing is addressable (the band is one node; its inner
   elements carry no ids), so a typo in a cloned headline is a chat round-trip.

A third defect surfaced while testing: the layers panel and every label the shell shows for a
web node is a raw id, because nothing ever sets a node's `name`.

## 2. Current state (what this design builds on — verified 2026-09-04)

| Concern | Where it lives today | State |
|---|---|---|
| Hover/select/edit in the canvas | `subsystems/clue-design/apps/api/lumen_api/web_bridge.py` (script injected by `GET /documents/{id}/web/render?mode=editor&bridge=1`) | Hover dashed outline + click select + dblclick rich-text on `[data-node-id]` elements only |
| Bridge inbound validation, selection join | `apps/frontend/src/features/design-editor/engine/webBridge.ts` (`validateBridgeMessage`), `hooks/use-web-bridge-selection.ts`, `hooks/use-web-artifact-selection.ts` | Nonce-validated; `select`, `node-info`, `edit-start/end`, `rich-text-*`, `lumen:navigate` |
| Edit-target chips (ad lane) | `apps/frontend/src/features/chat-shell/components/chat-surface.tsx` (`targetChips`, `editTargetsEnabled` gated `artifactKind === "ad"`), `model/edit-targets.ts` | Chips above the composer; `editTargetContextRefs` → `design_document` + `design_node` refs |
| Turn submission | `apps/frontend/src/features/projects/model/chat-turn.ts` (`TurnSubmission`, `turnRequestBody`: `message`, `context_refs[{object_type,object_id,version}]`, `attachment_refs`), `platform/api/clue_api/agent_turn_submission.py` (`SubmissionContextRefRow`) | No per-ref note field |
| Leg → design turn envelope | `platform/api/clue_api/design_leg_wiring.py` (~L1300–1420): `focus_refs` → `resolve_scene_targets` for scene; web request is `{prompt, base_version}` only (plan F4 v1) | Web targets deliberately not passed |
| Design API web turn | `subsystems/clue-design/apps/api/lumen_api/main.py`: `run_web_agent_turn(prompt, …, target_node_ids)` → `_describe_web_turn_targets` (kind, page, enclosing section; per-page lookup) + `config.turn_target_node_ids` | Exists, unused by the platform |
| Web agent prompt | `subsystems/clue-design/apps/agent_runtime/lumen_agent/prompts_web.py` (`build_web_solo_prompt`) | No annotation block |
| Node naming | `WebNode.name?: string` (`engine/webDocuments.ts`); engine `WebNode.name: Option<String>` (`crates/lumen-web/src/doc.rs`); layers `labelFor` = name else id (`design-editor/adapter/layers.ts`); backend `_web_node_label` (name/content/label) | Pin tools never stamp a name; fragment registry label never reaches the frontend |
| Clone model | `WebNodeKind::Fragment { fragment_id, slots }` (`doc.rs`); slot walk `crates/lumen-web/src/fragment.rs` (touches only `data-lumen-slot` elements; markers survive render); D-F3 allowlists in `web_bridge.py` ~L1235 and `webDocuments.ts` ~L1494 | Leaf; slot values only |
| Rich text | `webRichTextRuntime.ts` (Lexical, in-iframe), toolbar `components/web-rich-text-toolbar.tsx` (bold/italic/underline/strike, blocks, colour, link, variable); size is an inspector class-facet write (`adapter/apply.ts` `fontSize` → `FONT_SIZE_TO_RAMP`) | Vocabulary text only |
| Clone source for the agent | `inspect_cloned_section(fragment_id)` tool (html/css/slots) | Added 2026-09-04 |

## 3. Design

### 3.1 Element address (one grammar, every consumer)

```
ElementAddress = {
  node_id: string,            // the WebDoc node that owns the DOM subtree
  path?: string,              // structural path from the FRAGMENT node's rendered root to the
                              //   element, only for elements inside a cloned band. Form:
                              //   ":nth-child(2) > :nth-child(1) > :nth-child(3)" — the same
                              //   structural form `lumen_ingestion.sections.slotdetect` emits
                              //   (class-free, because a page's class names repeat).
  slot?: string,              // the element's data-lumen-slot key when it carries one
  tag: string,                // lowercase tag name, display only
}
```

- The bridge computes `path` from the live DOM by walking from the element up to its enclosing
  `[data-node-id]` element, counting element siblings. It excludes the bridge's own injected
  nodes (grips, badges, label chips) from the count — they are all `.lumen-*` and are inserted as
  the LAST children of `document.body`, never inside a fragment.
- The backend resolves `path` against the fragment's stored HTML with `selectolax` using the
  same `:nth-child` chain (the slot annotator already does exactly this walk). A path that no
  longer resolves is reported, never guessed.
- Vocabulary nodes have `path` absent. Their address is the node id, as today.

### 3.2 Display names (one function, four consumers)

`displayNameForNode(node, fragmentMeta?)` in a new `design-editor/adapter/node-names.ts`:

1. `node.name` when non-empty (the agent's pin tools and the human rename write it);
2. by kind: `text` → first 40 chars of the plain text; `button` → label; `image` → alt, else
   "Image"; `fragment` → `"{Role} — {label}"` from the registry (`fragmentMeta`), else "Cloned
   section"; `section` wrapping exactly one fragment → that fragment's name; `container` →
   "Container"; else the kind capitalised.

Inner-element label (bridge, hover chip and comment chip): `"{tag} · {slot}"` when a slot key
exists, else `tag`.

Consumers: the layers panel (`buildWebLayerRows.labelFor`), the hover label chip, the comment-box
chip, the composer chips, and the backend's TURN TARGET paragraph (`_web_node_label` gains the
same order so the agent and the human read the same name).

**Pin-time naming.** `assemble_cloned_sections`, `insert_cloned_section`, `assemble_abm_page`, and
`repair_cloned_section` (pin-in-place) stamp `name` on both the section wrapper and the fragment
node: `"{section_role title} — {registry label}"`. Existing documents keep working through the
derivation above; a one-off backfill is not needed.

**Registry meta in the frontend.** The layers/hover path needs only `{fragment_id: {label,
section_role}}` for the fragments the document pins. `public_document` (design API `GET
/documents/{id}`) adds it as a sibling key `fragment_meta` (read-only, derived from the registry
at read time; absent entries mean "unreleased or unknown" and fall back to "Cloned section"), so
the frontend needs no second fetch and the document body itself stays byte-identical.

### 3.3 Bridge changes (`web_bridge.py` injected script)

- **Hover on every element.** `mouseover` outlines the nearest element (not the nearest
  `[data-node-id]`), using a single positioned overlay `<div class="lumen-hover-box">` rather than
  an outline class, so elements the clone's CSS styles with `outline`/`overflow` are unaffected.
  A label chip `<div class="lumen-hover-label">` sits at the overlay's top-left with the
  inner-element label or the node's display name (posted down from the shell in a `names` map
  at render time, `__LUMEN_NODE_NAMES__`, like `__LUMEN_PAGE_ROUTES__`).
- **Single click → `annotate`.** Posts `{type:"annotate", address, name, geometry}` and ALSO the
  existing `select` for the owning node (so the inspector and layers keep behaving). Clicks on
  grips/handles/badges are ignored as today; a click while a rich-text session is open settles it
  first, as today.
- **Double click → `edit-text`.** For a `[data-tv]` vocabulary node: unchanged (`beginEditing`).
  For a text-bearing element inside a fragment: posts `{type:"edit-text", address, text, marks,
  size}` and starts a **constrained** local session (see 3.6).
- **Badges.** Inbound `{type:"annotations", items:[{address, n}]}` renders numbered badges
  (`.lumen-annotation-badge`) at each element's top-right and a faint dashed outline; the map is
  re-sent on every render. Inbound `{type:"annotations", items:[]}` clears them.
- **Fragment interiors** stay non-movable, non-droppable, non-resizable (D-F3 unchanged there).

### 3.4 Shell: comment box, session state, chips, badges

- **State.** `useWebAnnotations(documentId, pageId)` in `design-editor/hooks/`: an ordered list
  `{n, address, name, note, pageId}`; add / update / remove / clear; a `pending` entry for an
  open comment box. Session-only (React state keyed on the document id; dropped on unmount).
- **Comment box.** `WebAnnotationPopover` in `design-editor/components/`: positioned against the
  iframe rect + element geometry (same math as `computeToolbarPosition` in
  `web-rich-text-toolbar.logic.ts`); name chip; textarea (placeholder "Edit or ask a question");
  delete; **Add** (primary), **Send to chat**; **Edit text** quick action when the element is
  text-bearing (posts the same `edit-text` the double click would). Escape / click-away discards
  an empty pending box, keeps a non-empty one as a draft chip.
- **Chips.** The existing edit-target bar in `chat-surface.tsx` renders web annotations as
  `"{n} {first ~28 chars of note}"` chips with a remove control; the bar's label reads
  "Annotations" for web. `editTargetsEnabled` widens to web.
- **Badges.** The hook posts the `annotations` map into the frame on every change and every
  render nonce.

### 3.5 Annotations into the turn

- **Submission.** `TurnSubmission.contextRefs` entries gain an optional `note?: string`; the
  wire body's `context_refs[]` gains `note`. Server: `SubmissionContextRefRow.note: str | None`
  (one nullable column, migration with Alembic hash id, `down_revision` = current head),
  `DomainObjectRef` gains `note`. The `object_id` for an inner element is
  `"{node_id}#{path}"` when `path` is present (the `#` is illegal in node ids and in the path
  grammar, so the split is unambiguous); `object_type` stays `design_node`.
- **Leg wiring.** `design_leg_wiring.py` passes, for a web-pinned leg, `target_node_ids` (the
  owning node ids, ordered, deduplicated) and a new `target_notes: [{target, path, note}]` in the
  web request. `WebTurnRequest` gains `target_notes: Optional[List[WebTurnTargetNote]]`.
- **Prompt.** `_describe_web_turn_targets` grows: per annotation, the display name, the inner
  path and slot when present, and the note verbatim, numbered in submission order. Fail-closed
  wording is kept for a node that no longer exists. `build_web_solo_prompt` gets a short
  ANNOTATIONS block: honour them in order; each is a bounded change (the plan-sizing rule
  applies); for a path inside a clone, read the band with `inspect_cloned_section` and locate the
  element by that path; confirm each annotation by number in the finalize summary; never touch a
  band no annotation names unless the message asks.
- **Agent read.** `inspect_cloned_section` output gains `text_overrides` (3.6) so an agent
  repair never silently discards a human edit.

### 3.6 Text edits inside clones (D-F3 amendment R-A6)

- **Engine model** (`crates/lumen-web/src/doc.rs`):
  ```
  WebNodeKind::Fragment {
    fragment_id, slots,
    text_overrides: BTreeMap<String /*path*/, FragmentTextOverride>,   // default empty, skipped when empty
  }
  FragmentTextOverride { text: String, bold: bool, italic: bool, underline: bool, size: Option<i8> }
  ```
  Bounds: ≤ 64 overrides per node, path ≤ 256 chars matching `^(:nth-child\(\d+\)( > )?)+$`,
  text ≤ 8 KB (same as slot values), `size` ∈ −3…+3 steps on the theme ramp.
- **Operation** (`ops.rs`): `SetFragmentTextOverride { page_id, id, path, override: Option<…> }`
  (None clears). Inverse restores the previous entry. Validation refuses a non-fragment node, a
  bad path grammar, and a path that does not resolve in the fragment's HTML at apply time (the
  API threads the fragment package, as it does for slot kinds).
- **Render** (`fragment.rs`): after the slot pass, a second pass walks the artifact HTML with
  the same quick_xml reader, resolves each override path by counting element children, replaces
  the element's text content (escaped), and wraps it as needed: `<strong>`, `<em>`, `<u>` for the
  marks, and a `data-lumen-size="{step}"` attribute + an inline `font-size` computed from the
  theme ramp for the size step. Markers and everything else copy through byte-for-byte. A path
  that no longer resolves emits a diagnostic and leaves the element untouched.
- **Allowlists.** `web_bridge.py` and `webDocuments.ts` D-F3 comments updated: fragment stays
  leaf/movable-only; text overrides are the one interior edit, and only through this op.
- **Inline editor.** A constrained mode of the existing rich-text session: plain text + the three
  marks + a size stepper. Commit posts `{type:"clone-text-commit", address, override}`; the shell
  writes `SetFragmentTextOverride` through the existing `applyWebOperations` path with the
  loaded `base_version`. Cancel restores the DOM from the last render.
- **Inspector.** When a fragment is selected, the fragment card (F3.2 seam, first component use)
  lists slots and text overrides with a "Clear" per override.

### 3.7 Gesture summary (Edit mode, web canvas)

| Gesture | Vocabulary node | Element inside a clone |
|---|---|---|
| Hover | overlay + label (display name) | overlay + label (tag · slot) |
| Single click | comment box (+ Edit text if text) + select node | comment box (+ Edit text if text) + select band |
| Double click on text | rich-text session (unchanged) | constrained clone-text session |
| Escape / click-away | settle/cancel as today | settle/cancel |

## 4. Error handling

- A stale address (node deleted, path no longer resolves) → the TURN TARGET line says so and the
  agent uses judgment; the override op refuses at apply with a typed engine code the inspector
  shows in the Page-section style ("That text is no longer in the section").
- A render nonce change drops pending comment-box position and re-posts badges.
- Annotations on page A while the user switches to page B: chips keep their page id; the badge
  map is posted per page; the turn paragraph names the page (already does).
- Overrides and slot substitution disagree (a slot's fallback element also has an override): the
  override wins because it runs second; documented in `fragment.rs`.

## 5. Testing

- **Bridge** (`apps/api/tests/test_web_bridge*.py`): path computation matches `slotdetect`'s
  path for the same markup (shared fixture); hover label content; annotate/edit-text payloads.
- **Frontend** (`tsx --test`): `node-names.test.ts` (order of precedence, fragment meta);
  `layers.test.ts` updated; `use-web-annotations` reducer tests; `edit-targets` note propagation;
  `turnRequestBody` includes `note`; popover position math.
- **Platform** (`tests/api/`): submission row stores `note`; leg wiring builds `target_notes`
  for a web leg and NOT for a scene leg; migration up/down.
- **Design API** (`apps/api/tests`): `_describe_web_turn_targets` with notes and paths;
  `public_document.fragment_meta`; pin tools stamp names; `inspect_cloned_section` shows
  overrides.
- **Engine** (`cargo test --workspace`): override op apply/inverse/validation; render pass with
  marks, size, void elements, unresolvable path diagnostic; slot + override on one element.
- **Agent** (`apps/agent_runtime/tests`): solo prompt carries the ANNOTATIONS block; a
  bounded-annotation brief triggers the short plan.
- **Live acceptance**: three annotations on the Ramp home page (one inside a clone), sent as one
  message; a clone headline typo fixed by double-click; the layers panel shows names.

## 6. Out of scope (recorded, not built)

Durable annotations (R-A3); human rename of layers (the name op exists, UI later); annotations
on ad canvases beyond today's chips; comment threads/replies; text edits inside custom
components; library scoping of released campaign variants (separate ruling pending).
