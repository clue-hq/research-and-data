# Web Editor Annotations, Human Names, and Clone Text Edits — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In the web editor's Edit mode, a marketer can hover any element (including inside a cloned band) and see its name, single-click it to leave a numbered comment that ships with the next chat message as a scoped target the agent honours, double-click text inside a clone to edit its words and bold/italic/underline/size, and read human names in the layers panel.

**Architecture:** One element-address grammar (`node_id` + optional structural `path` inside a fragment + optional `slot`) is computed by the injected iframe bridge and resolved by the design API; one display-name function feeds the layers panel, hover chip, comment chip and the agent's TURN TARGET paragraph. Annotations ride the existing turn pipeline (context refs gain a `note`; the platform finally passes web targets; the design API's target paragraph grows the note and path). Text edits inside clones are a new engine operation writing a per-node `text_overrides` map that the fragment render walk applies after slot values (D-F3 amended, ruling R-A6).

**Tech Stack:** Rust (`lumen-web` crate, quick_xml walk), Python 3.12 (FastAPI design API, `selectolax`, platform API + Alembic), TypeScript/React 19 (Next.js app router, `tsx --test` unit tests), vanilla JS bridge script embedded in Python.

**Spec:** `docs/superpowers/specs/archive/2026-09-04-web-editor-annotations-and-clone-text-edits-design.md`

## Global Constraints

- Founder rulings R-A1..R-A6 in the spec are binding; quote them in code comments where they bind.
- No AI attribution in commits. Local commits only; never push.
- Env parity: any new flag appears in `.env`, `.env.example`, and (if LUMEN_*) `subsystems/clue-design/.env.example` with its default, the moment it is introduced. (This plan introduces none.)
- Alembic: hash revision ids via `alembic revision -m`, `down_revision` = current head `8079022e5802`, one head always, `make db-smoke` on a throwaway DB.
- Design subsystem engine gate, in order, after ANY change under `subsystems/clue-design/crates/`: `cargo test --workspace` → `cargo build -p lumen-api-helper --release` → `bash scripts/build_wasm_core.sh && node scripts/verify_handshake.mjs` (prints HANDSHAKE OK; lumen-core is untouched by this plan, so the stamp is unchanged, but run it) → `PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/agent_runtime/tests apps/api/tests -q` → restart the dev stack (`./scripts/dev_stack.sh down && ./scripts/dev_stack.sh up` from the repo root) so the API loads the rebuilt helper (the stale-helper trap of 2026-09-04).
- Frontend gate: `cd apps/frontend && npm run lint && npm test && npm run build`.
- Platform gate: `cd <repo root> && .venv/bin/python -m pytest tests/api -q -k "design_turn_targets or agent_turn_submission or chat"` plus `make db-smoke` for the migration task.
- Tests are `node:test` + `node:assert/strict` for the frontend (`*.test.ts` beside the module, no DOM), `pytest` for Python, `#[cfg(test)]` modules for Rust. A failing test is analysed, never weakened.
- Session memory: append progress to `_memory/2026-09-04-web-editor-annotations.md` at the end of each slice (create it in Task 1).
- Address grammar (spec §3.1): `path` matches `^(:nth-child\(\d+\)( > )?)+$` (1-based, element children only); `object_id` on the wire for an inner element is `"{node_id}#{path}"`; `#` never appears in node ids or paths.
- Override bounds (spec §3.6): ≤ 64 overrides per node; path ≤ 256 chars; text ≤ 8192 bytes; `size` ∈ −3…+3.

---

## File map (what each task creates or changes)

| Area | Path | Responsibility |
|---|---|---|
| Frontend naming | `apps/frontend/src/features/design-editor/adapter/node-names.ts` (+ `.test.ts`) | `displayNameForNode`, `innerElementLabel` — the one naming function |
| Frontend layers | `apps/frontend/src/features/design-editor/adapter/layers.ts` | `labelFor` → `displayNameForNode` |
| Frontend document | `apps/frontend/src/features/design-editor/engine/webDocuments.ts` | `fragment_meta` on the loaded document; `WebOperation` gains `set_fragment_text_override`; op builder |
| Frontend bridge types | `apps/frontend/src/features/design-editor/engine/webBridge.ts` (+ `.test.ts`) | `WebElementAddress`, inbound `annotate`, `edit-text`, `clone-text-commit`; outbound `annotations` |
| Frontend bridge hook | `apps/frontend/src/features/design-editor/hooks/use-web-bridge-selection.ts` | dispatch new inbound messages |
| Frontend annotations | `apps/frontend/src/features/design-editor/hooks/use-web-annotations.ts` (+ `.test.ts` for the pure reducer in `adapter/annotations.ts`) | session-only annotation state |
| Frontend popover | `apps/frontend/src/features/design-editor/components/web-annotation-popover.tsx`, `web-annotation-popover.logic.ts` (+ `.test.ts`), `.module.css` | comment box |
| Frontend composer | `apps/frontend/src/features/chat-shell/components/chat-surface.tsx`, `chat-shell/model/edit-targets.ts` (+ test) | chips for web, `note` on refs |
| Frontend turn model | `apps/frontend/src/features/projects/model/chat-turn.ts` (+ `chat-schemas.test.ts`) | `note` on `TurnContextReference` and wire body |
| Frontend writes | `apps/frontend/src/features/design-editor/hooks/use-inspector-writes.ts` | `setFragmentTextOverride` write |
| Platform schema | `platform/api/clue_api/chat/schemas.py`, `platform/agents/clue_agents/contracts.py`, `platform/api/clue_api/agent_turn_submission.py`, `alembic/versions/<hash>_context_ref_note.py` | `note` end to end |
| Platform leg | `platform/api/clue_api/design_leg_wiring.py`, `platform/api/clue_api/design_turn_targets.py` (+ `tests/api/test_design_turn_targets.py`) | web targets + notes into the web request |
| Design API | `subsystems/clue-design/apps/api/lumen_api/models.py`, `main.py` (`public_document`, `_web_node_label`, `_describe_web_turn_targets`, `run_web_agent_turn`), `web_bridge.py`, `agent_cloned_sections.py` (`read_source` overrides) | names, bridge, targets with notes |
| Agent runtime | `subsystems/clue-design/apps/agent_runtime/lumen_agent/config.py`, `harness_web.py`, `prompts_web.py`, `tools/web_substrate.py` | pin-time names, ANNOTATIONS block, overrides in inspect |
| Engine | `subsystems/clue-design/crates/lumen-web/src/doc.rs`, `ops.rs`, `validate.rs`, `fragment.rs` | `text_overrides`, `SetFragmentTextOverride`, override render pass |

---

# Slice 1 — Human names everywhere

### Task 1: One display-name function (frontend) and the layers panel uses it

**Files:**
- Create: `apps/frontend/src/features/design-editor/adapter/node-names.ts`
- Create: `apps/frontend/src/features/design-editor/adapter/node-names.test.ts`
- Modify: `apps/frontend/src/features/design-editor/adapter/layers.ts` (`labelFor`, `buildWebLayerRows` signature)
- Modify: `apps/frontend/src/features/design-editor/adapter/layers.test.ts`
- Modify: `apps/frontend/src/features/design-editor/engine/webDocuments.ts` (`LoadedWebDocument.fragmentMeta`, parsed from the GET's `fragment_meta`)
- Modify: `apps/frontend/src/features/design-editor/hooks/use-web-editing-session.ts` (pass `fragmentMeta` into `buildWebLayerRows`)
- Create: `_memory/2026-09-04-web-editor-annotations.md`

**Interfaces:**
- Produces:
  ```ts
  export interface FragmentMeta { label: string | null; section_role: string | null }
  export type FragmentMetaMap = Record<string, FragmentMeta>;   // keyed by fragment_id
  export function displayNameForNode(node: WebNode, nodes: Record<string, WebNode>, fragmentMeta?: FragmentMetaMap): string
  export function innerElementLabel(tag: string, slot?: string | null): string   // "h2 · headline" | "h2"
  export function buildWebLayerRows(page: WebLayerPage, activeNodeId: string | null, fragmentMeta?: FragmentMetaMap): WebLayerRow[]
  ```

- [ ] **Step 1: Write the failing tests**

`apps/frontend/src/features/design-editor/adapter/node-names.test.ts`:
```ts
import assert from "node:assert/strict";
import test from "node:test";
import type { WebNode } from "../engine/webDocuments";
import { displayNameForNode, innerElementLabel } from "./node-names";

const nodes: Record<string, WebNode> = {
  sec_a: { id: "sec_a", kind: "section", classes: "", children: ["frg_a"] },
  frg_a: { id: "frg_a", kind: "fragment", classes: "", fragment_id: "frag_" + "ab".repeat(8) },
  sec_b: { id: "sec_b", kind: "section", classes: "", children: ["txt", "btn"] },
  txt: { id: "txt", kind: "text", classes: "", content: "<p>Card infrastructure <em>economics</em>, built for Ramp.</p>" },
  btn: { id: "btn", kind: "button", classes: "", label: "Talk to our team" },
  img: { id: "img", kind: "image", classes: "", asset_id: "asset_x", alt: "Visa card" },
  img2: { id: "img2", kind: "image", classes: "", asset_id: "asset_y", alt: "" },
  box: { id: "box", kind: "container", classes: "" },
  named: { id: "named", kind: "text", classes: "", name: "Eyebrow", content: "Issuing" },
};
const meta = { ["frag_" + "ab".repeat(8)]: { label: "Stripe homepage hero", section_role: "hero" } };

test("a node's own name wins over everything", () => {
  assert.equal(displayNameForNode(nodes.named, nodes, meta), "Eyebrow");
});

test("text is named by its plain words, capped at 40 chars", () => {
  assert.equal(displayNameForNode(nodes.txt, nodes), "Card infrastructure economics, built for");
});

test("buttons by label, images by alt or 'Image', containers by kind", () => {
  assert.equal(displayNameForNode(nodes.btn, nodes), "Talk to our team");
  assert.equal(displayNameForNode(nodes.img, nodes), "Visa card");
  assert.equal(displayNameForNode(nodes.img2, nodes), "Image");
  assert.equal(displayNameForNode(nodes.box, nodes), "Container");
});

test("a fragment is named from the registry meta, and its wrapper section inherits it", () => {
  assert.equal(displayNameForNode(nodes.frg_a, nodes, meta), "Hero — Stripe homepage hero");
  assert.equal(displayNameForNode(nodes.sec_a, nodes, meta), "Hero — Stripe homepage hero");
  // Without meta the clone is still human, never an id.
  assert.equal(displayNameForNode(nodes.frg_a, nodes), "Cloned section");
  assert.equal(displayNameForNode(nodes.sec_b, nodes), "Section");
});

test("inner elements read as tag plus slot when there is one", () => {
  assert.equal(innerElementLabel("h2", "headline"), "h2 · headline");
  assert.equal(innerElementLabel("svg", null), "svg");
  assert.equal(innerElementLabel("P", undefined), "p");
});
```

Append to `apps/frontend/src/features/design-editor/adapter/layers.test.ts`:
```ts
test("layer rows show display names, never raw ids (R-A5)", () => {
  const page = {
    page_root: "root",
    nodes: {
      root: { id: "root", kind: "container", classes: "", children: ["sec_1"] },
      sec_1: { id: "sec_1", kind: "section", classes: "", children: ["frg_1"] },
      frg_1: { id: "frg_1", kind: "fragment", classes: "", fragment_id: "frag_" + "cd".repeat(8) },
    },
  };
  const rows = buildWebLayerRows(page, null, {
    ["frag_" + "cd".repeat(8)]: { label: "Stripe footer", section_role: "footer" },
  });
  assert.deepEqual(rows.map((r) => r.label), ["Footer — Stripe footer", "Footer — Stripe footer"]);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd apps/frontend && npx tsx --test src/features/design-editor/adapter/node-names.test.ts src/features/design-editor/adapter/layers.test.ts`
Expected: FAIL — `Cannot find module './node-names'` and the layers test failing on labels `sec_1`/`frg_1`.

- [ ] **Step 3: Implement `node-names.ts`**

```ts
import type { WebNode } from "../engine/webDocuments";

/** Registry facts about one pinned fragment, as `GET /documents/{id}` serves them under
 * `fragment_meta` (design API `public_document`, Task 2). Absent → "unreleased or unknown". */
export interface FragmentMeta {
  label: string | null;
  section_role: string | null;
}
export type FragmentMetaMap = Record<string, FragmentMeta>;

const NAME_CAP = 40;

function plainText(html: string): string {
  return html.replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
}

function capitalise(word: string): string {
  return word.length === 0 ? word : word[0].toUpperCase() + word.slice(1);
}

function fragmentName(node: WebNode, fragmentMeta?: FragmentMetaMap): string {
  const meta = node.fragment_id ? fragmentMeta?.[node.fragment_id] : undefined;
  if (!meta) return "Cloned section";
  const role = meta.section_role ? capitalise(meta.section_role) : null;
  const label = meta.label?.trim() || null;
  if (role && label) return `${role} — ${label}`;
  return role ?? label ?? "Cloned section";
}

/**
 * Ruling R-A5 (founder, 2026-09-04): every label the shell shows for a web node is a human
 * name, never a raw id. ONE order of precedence, shared by the layers panel, the hover chip,
 * the comment chip, and (mirrored in Python, `_web_node_label`) the agent's TURN TARGET line:
 *   1. the node's own `name` (pin tools stamp it; a human rename writes it);
 *   2. by kind — text: its plain words; button: its label; image: its alt; fragment: the
 *      registry's role and label; a section wrapping exactly one fragment: that fragment's name;
 *   3. the kind, capitalised.
 */
export function displayNameForNode(
  node: WebNode,
  nodes: Record<string, WebNode>,
  fragmentMeta?: FragmentMetaMap,
): string {
  if (typeof node.name === "string" && node.name.trim().length > 0) return node.name.trim();
  switch (node.kind) {
    case "text": {
      const text = plainText(typeof node.content === "string" ? node.content : "");
      return text.length > 0 ? text.slice(0, NAME_CAP).trim() : "Text";
    }
    case "button":
      return node.label?.trim() || "Button";
    case "image":
      return node.alt?.trim() || "Image";
    case "fragment":
      return fragmentName(node, fragmentMeta);
    case "section": {
      const children = node.children ?? [];
      const only = children.length === 1 ? nodes[children[0]] : undefined;
      if (only && only.kind === "fragment") return fragmentName(only, fragmentMeta);
      return "Section";
    }
    default:
      return capitalise(node.kind);
  }
}

/** Ruling R-A4: an element INSIDE a clone reads as its tag plus the slot it carries. */
export function innerElementLabel(tag: string, slot?: string | null): string {
  const lower = tag.toLowerCase();
  return slot ? `${lower} · ${slot}` : lower;
}
```

- [ ] **Step 4: Wire `layers.ts`, the loaded document, and the session**

In `layers.ts` replace `labelFor` and thread the map:
```ts
import { displayNameForNode, type FragmentMetaMap } from "./node-names";
// ...
export function buildWebLayerRows(
  page: WebLayerPage,
  activeNodeId: string | null,
  fragmentMeta?: FragmentMetaMap,
): WebLayerRow[] {
  // ... unchanged, but every `label: labelFor(x)` becomes
  //     `label: displayNameForNode(x, page.nodes, fragmentMeta)`
}
```
Delete the old `labelFor`.

In `webDocuments.ts`, where `LoadedWebDocument` is built from the GET (`fetchWebDocument`), add:
```ts
export interface LoadedWebDocument {
  // ...existing fields
  /** Task 1/2: registry facts for pinned fragments, keyed by fragment_id. `{}` when the
   * API did not send any (older API) — names then fall back to "Cloned section". */
  fragmentMeta: Record<string, { label: string | null; section_role: string | null }>;
}
// in fetchWebDocument, after parsing `payload.scene`:
const rawMeta = (payload as { fragment_meta?: unknown }).fragment_meta;
const fragmentMeta: LoadedWebDocument["fragmentMeta"] = {};
if (rawMeta && typeof rawMeta === "object") {
  for (const [id, value] of Object.entries(rawMeta as Record<string, unknown>)) {
    if (value && typeof value === "object") {
      const v = value as { label?: unknown; section_role?: unknown };
      fragmentMeta[id] = {
        label: typeof v.label === "string" ? v.label : null,
        section_role: typeof v.section_role === "string" ? v.section_role : null,
      };
    }
  }
}
```
and include `fragmentMeta` in the returned object.

In `use-web-editing-session.ts`, find the `buildWebLayerRows(` call and pass `webSelection.document?.fragmentMeta` as the third argument.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd apps/frontend && npx tsx --test src/features/design-editor/adapter/node-names.test.ts src/features/design-editor/adapter/layers.test.ts`
Expected: PASS (all).

- [ ] **Step 6: Frontend gate**

Run: `cd apps/frontend && npm run lint && npm test`
Expected: lint clean (two pre-existing warnings in `canvasOperations.ts` are known), all tests pass.

- [ ] **Step 7: Create the memory note and commit**

`_memory/2026-09-04-web-editor-annotations.md`:
```markdown
# 2026-09-04 — web editor: annotations, human names, clone text edits (implementation log)
Spec: docs/superpowers/specs/archive/2026-09-04-web-editor-annotations-and-clone-text-edits-design.md
Plan: docs/superpowers/plans/2026-09-04-web-editor-annotations-and-clone-text-edits.md

## Slice 1 — names
- Task 1: `displayNameForNode` + layers wired; `fragmentMeta` parsed from GET /documents.
```

```bash
git add apps/frontend/src/features/design-editor/adapter/node-names.ts apps/frontend/src/features/design-editor/adapter/node-names.test.ts apps/frontend/src/features/design-editor/adapter/layers.ts apps/frontend/src/features/design-editor/adapter/layers.test.ts apps/frontend/src/features/design-editor/engine/webDocuments.ts apps/frontend/src/features/design-editor/hooks/use-web-editing-session.ts _memory/2026-09-04-web-editor-annotations.md
git commit -m "feat(frontend): one display-name function for web nodes; layers panel shows human names (R-A5)"
```

---

### Task 2: Design API serves `fragment_meta` beside the document

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py` (`public_document` and its two call sites for web docs: `get_document` at ~L2522 and wherever `public_document(` is returned for a web doc — grep `public_document(` and add the meta only on the GET route)
- Test: `subsystems/clue-design/apps/api/tests/test_public_document_fragment_meta.py`

**Interfaces:**
- Produces: `GET /documents/{id}` → JSON gains top-level `"fragment_meta": {fragment_id: {"label": str|null, "section_role": str|null}}` for every `fragment` node across all pages of a web document. Absent for scene docs.
- Consumes: `HybridRepository.list_web_fragments()` rows (fields `fragment_id`, `label`, `section_role`) — the same rows `agent_cloned_sections.py:484` reads.

- [ ] **Step 1: Write the failing test**

```python
# subsystems/clue-design/apps/api/tests/test_public_document_fragment_meta.py
from __future__ import annotations

from lumen_api.main import fragment_meta_for_document

FRAG = "frag_" + "ab" * 8
OTHER = "frag_" + "cd" * 8


def _doc() -> dict:
    return {
        "doc_kind": "web",
        "scene": {
            "pages": [
                {"id": "home", "root": "r", "nodes": {
                    "r": {"id": "r", "kind": "container", "children": ["s"]},
                    "s": {"id": "s", "kind": "section", "children": ["f"]},
                    "f": {"id": "f", "kind": "fragment", "fragment_id": FRAG},
                }},
                {"id": "issuing", "root": "r2", "nodes": {
                    "r2": {"id": "r2", "kind": "container", "children": ["f2"]},
                    "f2": {"id": "f2", "kind": "fragment", "fragment_id": OTHER},
                }},
            ]
        },
    }


def test_meta_covers_every_pinned_fragment_on_every_page() -> None:
    rows = [
        {"fragment_id": FRAG, "label": "Stripe homepage hero", "section_role": "hero"},
        {"fragment_id": "frag_" + "ef" * 8, "label": "unpinned", "section_role": "cta"},
    ]
    meta = fragment_meta_for_document(_doc(), rows)
    assert meta == {
        FRAG: {"label": "Stripe homepage hero", "section_role": "hero"},
        OTHER: {"label": None, "section_role": None},   # pinned but unknown → honest nulls
    }


def test_scene_documents_get_no_meta() -> None:
    assert fragment_meta_for_document({"doc_kind": "scene", "scene": {}}, []) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd subsystems/clue-design && PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/api/tests/test_public_document_fragment_meta.py -q`
Expected: FAIL — `ImportError: cannot import name 'fragment_meta_for_document'`.

- [ ] **Step 3: Implement**

In `main.py`, next to `public_document`:
```python
def fragment_meta_for_document(
    document: JsonObject, fragment_rows: Sequence[JsonObject]
) -> Optional[JsonObject]:
    """Ruling R-A5 (founder, 2026-09-04): the registry facts a human name is made of —
    `label` + `section_role` — for every fragment the document pins, on every page. A pinned
    id the registry does not hold (unreleased, another workspace's) gets honest nulls, so the
    frontend names it "Cloned section" instead of guessing. None for a scene document."""
    if document.get("doc_kind") != "web":
        return None
    by_id: dict = {}
    for row in fragment_rows:
        fid = row.get("fragment_id")
        if isinstance(fid, str):
            by_id[fid] = {
                "label": row.get("label") if isinstance(row.get("label"), str) else None,
                "section_role": row.get("section_role")
                if isinstance(row.get("section_role"), str)
                else None,
            }
    meta: JsonObject = {}
    scene = document.get("scene") if isinstance(document.get("scene"), dict) else {}
    for page in scene.get("pages") or []:
        if not isinstance(page, dict):
            continue
        for node in (page.get("nodes") or {}).values():
            if isinstance(node, dict) and node.get("kind") == "fragment":
                fid = node.get("fragment_id")
                if isinstance(fid, str) and fid not in meta:
                    meta[fid] = by_id.get(fid, {"label": None, "section_role": None})
    return meta
```
In `get_document` (the `@app.get("/documents/{document_id}")` route):
```python
    def get_document(document_id: str, repo: HybridRepository = Depends(repository)) -> JsonObject:
        document = require_document(repo, document_id)
        result = public_document(document)
        meta = fragment_meta_for_document(document, repo.list_web_fragments())
        if meta is not None:
            result["fragment_meta"] = meta
        return result
```
(`list_web_fragments` is the repository method `agent_cloned_sections.py:484` already calls; if it is workspace-scoped through `repo`, that scoping is exactly what we want.)

- [ ] **Step 4: Run the tests**

Run: `cd subsystems/clue-design && PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/api/tests/test_public_document_fragment_meta.py apps/api/tests/test_web_turns.py -q`
Expected: PASS.

- [ ] **Step 5: Live check and commit**

With the dev stack up: `curl -s -H "X-Workspace-Id: ws_009a035fd48c4985891fee919254c31a" http://127.0.0.1:8010/documents/doc_7ad66d87091f536c97ffc417b0b0691b | python3 -c "import sys,json; print(json.load(sys.stdin)['fragment_meta'])"` prints a map with roles/labels for the Ramp page's seven clones. Reload the editor: the layers panel shows "Hero — …", "Footer — …" instead of `sec_…`/`frg_…`.

```bash
git add subsystems/clue-design/apps/api/lumen_api/main.py subsystems/clue-design/apps/api/tests/test_public_document_fragment_meta.py
git commit -m "feat(design-api): GET /documents serves fragment_meta (label, section_role) for every pinned clone"
```

---

### Task 3: Pin tools stamp a human `name` on the section and fragment nodes

**Files:**
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/web_substrate.py` (`_cloned_section_pin_nodes` at ~L8100; its callers `insert_cloned_section`, `assemble_cloned_sections`, `recreate_cloned_page`, `assemble_abm_page`, and the repair pin-in-place path pass the resolved registry entry)
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_web_cloned_sections.py`

**Interfaces:**
- Produces: `_cloned_section_pin_nodes(self, fragment_id, slots, taken, *, name: str | None = None)`; both nodes carry `"name": name` when given. `pin_display_name(resolved: dict) -> str` builds `"{Role} — {label}"` from the resolved entry's `section_role` and `label` (same words as Task 1's `fragmentName`).

- [ ] **Step 1: Write the failing test**

Append to `test_web_cloned_sections.py` (use the file's existing `FakeRegistry`/tool fixture; the existing test `test_inserting_wraps_the_cloned_section_in_a_section_container` shows how a pin is exercised and how the doc is read back):
```python
def test_a_pin_stamps_a_human_name_on_both_nodes(tool, registry):
    # The registry entry the fake serves must carry a role and a label (adjust the fake's
    # released entry to include "section_role": "hero", "label": "Stripe homepage hero").
    fragment_id = registry.released_ids()[0]
    tool.insert_cloned_section(fragment_id, slot_values_json="{}")
    page = tool.web_doc["pages"][0]
    section = next(n for n in page["nodes"].values() if n["kind"] == "section")
    fragment = next(n for n in page["nodes"].values() if n["kind"] == "fragment")
    assert section["name"] == "Hero — Stripe homepage hero"
    assert fragment["name"] == "Hero — Stripe homepage hero"


def test_pin_display_name_degrades_honestly():
    from lumen_agent.tools.web_substrate import pin_display_name
    assert pin_display_name({"section_role": "footer", "label": "Stripe footer"}) == "Footer — Stripe footer"
    assert pin_display_name({"section_role": "cta", "label": ""}) == "Cta"
    assert pin_display_name({"label": "Only a label"}) == "Only a label"
    assert pin_display_name({}) == "Cloned section"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd subsystems/clue-design && PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/agent_runtime/tests/test_web_cloned_sections.py -q -k "human_name or display_name"`
Expected: FAIL (`KeyError: 'name'`, `ImportError`).

- [ ] **Step 3: Implement**

Module-level helper in `web_substrate.py`:
```python
def pin_display_name(resolved: Mapping[str, Any]) -> str:
    """Ruling R-A5: the name a pinned clone is born with — `"{Role} — {label}"` — the same
    words the frontend derives for an unnamed clone from `fragment_meta`, so a page pinned by
    the agent and a page read by a human agree on what every band is called."""
    role = resolved.get("section_role")
    label = resolved.get("label")
    role_text = role.strip().capitalize() if isinstance(role, str) and role.strip() else None
    label_text = label.strip() if isinstance(label, str) and label.strip() else None
    if role_text and label_text:
        return f"{role_text} — {label_text}"
    return role_text or label_text or "Cloned section"
```
In `_cloned_section_pin_nodes`, add `*, name: str | None = None` and set `"name": name` on both `section_node` and `fragment_node` when `name` is truthy. At every call site the resolved registry entry (`resolved`) is in scope; pass `name=pin_display_name(resolved)`. For the repair pin-in-place path, the resolved entry of the minted repair is what it pins; use that.

- [ ] **Step 4: Run tests**

Run: `cd subsystems/clue-design && PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/agent_runtime/tests/test_web_cloned_sections.py apps/agent_runtime/tests/test_web_substrate.py -q`
Expected: PASS. (If a replay-equality test compares node dicts byte-for-byte against a fixture, update the fixture to carry `name`.)

- [ ] **Step 5: Commit**

```bash
git add subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/web_substrate.py subsystems/clue-design/apps/agent_runtime/tests/test_web_cloned_sections.py
git commit -m "feat(design-agent): pinned clones are born with a human name on the section and fragment nodes (R-A5)"
```

---

### Task 4: The agent's TURN TARGET line uses the same name order

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py` (`_web_node_label` ~L8983)
- Test: `subsystems/clue-design/apps/api/tests/test_web_turn_pages.py`

**Interfaces:**
- Produces: `_web_node_label(node, nodes=None, fragment_meta=None) -> Optional[str]` — same precedence as Task 1 (name → text/label/alt → fragment meta → section-wrapping-fragment → None so the caller prints the kind).

- [ ] **Step 1: Failing test** (append to `test_web_turn_pages.py`)

```python
def test_turn_target_names_a_clone_like_the_frontend_does():
    from lumen_api.main import _describe_web_turn_targets
    frag = "frag_" + "ab" * 8
    doc = {"pages": [{"id": "home", "root": "r", "nodes": {
        "r": {"id": "r", "kind": "container", "children": ["s"]},
        "s": {"id": "s", "kind": "section", "children": ["f"]},
        "f": {"id": "f", "kind": "fragment", "fragment_id": frag},
    }}]}
    meta = {frag: {"label": "Stripe homepage hero", "section_role": "hero"}}
    text = _describe_web_turn_targets(doc, ["f"], fragment_meta=meta)
    assert 'fragment "Hero — Stripe homepage hero"' in text
```

- [ ] **Step 2: Run to verify failure** — `pytest apps/api/tests/test_web_turn_pages.py -q -k clone_like` → FAIL (`TypeError: unexpected keyword 'fragment_meta'`).

- [ ] **Step 3: Implement** — extend `_web_node_label(node, nodes=None, fragment_meta=None)`:
```python
def _web_node_label(node, nodes=None, fragment_meta=None):
    name = node.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()[:40]
    kind = node.get("kind")
    if kind == "fragment":
        meta = (fragment_meta or {}).get(node.get("fragment_id") or "") or {}
        role, label = meta.get("section_role"), meta.get("label")
        role = role.strip().capitalize() if isinstance(role, str) and role.strip() else None
        label = label.strip() if isinstance(label, str) and label.strip() else None
        return (f"{role} — {label}" if role and label else role or label) or "Cloned section"
    if kind == "section" and nodes is not None:
        children = node.get("children") or []
        if len(children) == 1 and isinstance(nodes.get(children[0]), dict) \
                and nodes[children[0]].get("kind") == "fragment":
            return _web_node_label(nodes[children[0]], nodes, fragment_meta)
    for key in ("content", "label", "alt"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            text = re.sub(r"<[^>]+>", "", value).strip()
            if text:
                return text[:40]
    return None
```
`_describe_web_turn_targets(web_doc, target_node_ids, fragment_meta=None)` passes `nodes` and `fragment_meta` into `_web_node_label`; `run_web_agent_turn` computes `fragment_meta_for_document({"doc_kind": "web", "scene": web_doc}, repo.list_web_fragments())` once and passes it (the route already has `repo` in scope).

- [ ] **Step 4: Run** — `pytest apps/api/tests/test_web_turn_pages.py apps/api/tests/test_web_turns.py -q` → PASS.

- [ ] **Step 5: Commit**
```bash
git add subsystems/clue-design/apps/api/lumen_api/main.py subsystems/clue-design/apps/api/tests/test_web_turn_pages.py
git commit -m "feat(design-api): TURN TARGET lines name nodes with the shared display-name order"
```
Append "Slice 1 done" to `_memory/2026-09-04-web-editor-annotations.md` and commit it.

---

# Slice 2 — Annotations end to end

### Task 5: Bridge — hover on every element with a label, `annotate` on click, badges

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/web_bridge.py` (template: state vars ~L94, style ~L110, `mouseover`/`mouseout` ~L362–377, click handler ~L380–427; message handler for inbound types ~L595–670; `render_bridge_script` ~L1262)
- Test: `subsystems/clue-design/apps/api/tests/test_web_bridge_annotations.py`

**Interfaces:**
- Produces (script → shell): `{type:"annotate", channel, nonce, address:{nodeId, path?, slot?, tag}, name, geometry:{viewport:{x,y,width,height}, document:{...}}, textLike: boolean}`; the existing `select` still fires for the owning node.
- Consumes (shell → script): `{type:"annotations", channel, nonce, items:[{address:{nodeId,path?}, n:number}]}` → numbered badges; `{type:"annotations", items:[]}` clears.
- Produces (Python): `_bridge_node_names(web_doc, page_id, fragment_meta) -> dict[str,str]` and `render_bridge_script(nonce, web_doc, page_id, fragment_meta=None)` substituting `__LUMEN_NODE_NAMES__`.
- `textLike` is true when the element's tag is one of `h1..h6,p,span,a,button,li,blockquote,figcaption,label,strong,em,small,td,th,dt,dd` and it has non-empty `textContent`.

- [ ] **Step 1: Failing test**

```python
# subsystems/clue-design/apps/api/tests/test_web_bridge_annotations.py
from __future__ import annotations
from lumen_api.web_bridge import _bridge_node_names, render_bridge_script

FRAG = "frag_" + "ab" * 8

def _doc():
    return {"pages": [{"id": "home", "root": "root", "nodes": {
        "root": {"id": "root", "kind": "container", "children": ["sec_a", "sec_b"]},
        "sec_a": {"id": "sec_a", "kind": "section", "children": ["frg_a"]},
        "frg_a": {"id": "frg_a", "kind": "fragment", "fragment_id": FRAG},
        "sec_b": {"id": "sec_b", "kind": "section", "name": "Proof", "children": ["txt"]},
        "txt": {"id": "txt", "kind": "text", "content": "<p>135+ currencies</p>"},
    }}]}

def test_node_names_follow_the_shared_order():
    names = _bridge_node_names(_doc(), "home", {FRAG: {"label": "Stripe hero", "section_role": "hero"}})
    assert names == {
        "sec_a": "Hero — Stripe hero", "frg_a": "Hero — Stripe hero",
        "sec_b": "Proof", "txt": "135+ currencies",
    }

def test_script_carries_names_and_the_annotate_protocol():
    script = render_bridge_script("nonce-12345678", _doc(), "home", fragment_meta={})
    assert '"txt":"135+ currencies"' in script
    assert '"annotate"' in script and '"annotations"' in script
    assert "lumen-hover-label" in script and "lumen-annotation-badge" in script
    # `<` is never interpolated raw into the script body.
    assert "\\u003c" in script or "<" not in script.split("__LUMEN_NODE_NAMES__")[-1][:0]
```

- [ ] **Step 2: Run** — `pytest apps/api/tests/test_web_bridge_annotations.py -q` → FAIL (`ImportError`).

- [ ] **Step 3: Implement the Python side**

```python
def _bridge_node_names(web_doc, page_id, fragment_meta=None) -> dict[str, str]:
    """Ruling R-A4/R-A5: the display name of every node on the rendered page, in the shared
    order (`main._web_node_label`), baked into the script so the hover chip can name a band
    without a round trip."""
    from lumen_api.main import _web_node_label  # shared order; import here to avoid a cycle
    pages = web_doc.get("pages") if isinstance(web_doc, dict) else None
    page = next((p for p in (pages or []) if isinstance(p, dict) and p.get("id") == page_id), None)
    nodes = (page or {}).get("nodes") if isinstance((page or {}).get("nodes"), dict) else {}
    names = {}
    for node_id, node in nodes.items():
        if not isinstance(node, dict):
            continue
        label = _web_node_label(node, nodes, fragment_meta)
        names[node_id] = label or str(node.get("kind") or "node").capitalize()
    return names
```
`render_bridge_script(nonce, web_doc=None, page_id="home", fragment_meta=None)` adds `.replace("__LUMEN_NODE_NAMES__", _script_json(_bridge_node_names(web_doc, page_id, fragment_meta)))`. The render route (`/web/render?bridge=1`) passes `fragment_meta_for_document(...)` (Task 2).

- [ ] **Step 4: Implement the script side** (inside `_BRIDGE_V0_TEMPLATE`)

State + styles (next to `PAGE_ROUTES`):
```js
  var NODE_NAMES = __LUMEN_NODE_NAMES__;
  var hoverBox = null, hoverLabel = null, badgeLayer = null;
  var TEXT_LIKE = /^(h[1-6]|p|span|a|button|li|blockquote|figcaption|label|strong|em|small|td|th|dt|dd)$/;
```
Append to `style.textContent`:
```js
    ".lumen-hover-box{position:absolute;pointer-events:none;border:1.5px solid rgba(79,111,255,0.85);border-radius:2px;z-index:2147483000;}" +
    ".lumen-hover-label{position:absolute;pointer-events:none;background:#4f6fff;color:#fff;font:11px/16px ui-monospace,Menlo,monospace;padding:1px 6px;border-radius:3px;z-index:2147483001;white-space:nowrap;}" +
    ".lumen-annotation-outline{position:absolute;pointer-events:none;border:1.5px dashed rgba(234,179,8,0.95);z-index:2147482999;}" +
    ".lumen-annotation-badge{position:absolute;pointer-events:none;min-width:18px;height:18px;border-radius:9px;background:#f0a;color:#fff;font:600 11px/18px system-ui,sans-serif;text-align:center;padding:0 5px;z-index:2147483002;}"
```
Helpers (after `nodeInfo`):
```js
  function isBridgeEl(el) {
    return !!(el && el.closest && el.closest(".lumen-hover-box,.lumen-hover-label,.lumen-annotation-outline,.lumen-annotation-badge,.lumen-grip,.lumen-resize-handle,.lumen-resize-badge"));
  }
  function ownerNode(el) { return el && el.closest ? el.closest("[data-node-id]") : null; }
  // Spec §3.1: structural path from the OWNING node's element to `el`, 1-based, element
  // children only, bridge-injected nodes excluded (they are never inside a node's subtree).
  function elementPath(el, owner) {
    if (!el || !owner || el === owner) return null;
    var parts = [], cur = el;
    while (cur && cur !== owner) {
      var parent = cur.parentElement; if (!parent) return null;
      var index = 0, sib = parent.firstElementChild, position = 0;
      while (sib) { if (!isBridgeEl(sib)) { index += 1; if (sib === cur) { position = index; break; } } sib = sib.nextElementSibling; }
      if (!position) return null;
      parts.unshift(":nth-child(" + position + ")");
      cur = parent;
    }
    return parts.join(" > ");
  }
  function addressOf(el) {
    var owner = ownerNode(el); if (!owner) return null;
    var ownerId = owner.getAttribute("data-node-id");
    var isFragment = owner.hasAttribute("data-fragment-root") || (el !== owner && !el.hasAttribute("data-node-id"));
    var path = isFragment ? elementPath(el, owner) : null;
    var slot = el.getAttribute && el.getAttribute("data-lumen-slot");
    return { nodeId: ownerId, path: path || undefined, slot: slot || undefined, tag: el.tagName.toLowerCase() };
  }
  function labelFor(el, address) {
    if (address.path) return address.slot ? address.tag + " · " + address.slot : address.tag;
    return NODE_NAMES[address.nodeId] || address.tag;
  }
  function placeBox(box, rect) {
    box.style.left = (rect.left + window.scrollX) + "px"; box.style.top = (rect.top + window.scrollY) + "px";
    box.style.width = rect.width + "px"; box.style.height = rect.height + "px";
  }
  function showHover(el) {
    if (!hoverBox) { hoverBox = document.createElement("div"); hoverBox.className = "lumen-hover-box"; document.body.appendChild(hoverBox);
      hoverLabel = document.createElement("div"); hoverLabel.className = "lumen-hover-label"; document.body.appendChild(hoverLabel); }
    var address = addressOf(el); if (!address) return hideHover();
    var rect = el.getBoundingClientRect(); placeBox(hoverBox, rect);
    hoverLabel.textContent = labelFor(el, address);
    hoverLabel.style.left = (rect.left + window.scrollX) + "px";
    hoverLabel.style.top = Math.max(0, rect.top + window.scrollY - 18) + "px";
    hoverBox.style.display = hoverLabel.style.display = "block";
  }
  function hideHover() { if (hoverBox) { hoverBox.style.display = "none"; hoverLabel.style.display = "none"; } }
```
Replace the `mouseover`/`mouseout` handlers:
```js
  document.addEventListener("mouseover", function (event) {
    var el = event.target;
    if (!el || isBridgeEl(el) || el === document.body || el === document.documentElement) return hideHover();
    if (editing && editing.contains(el)) return hideHover();
    showHover(el);
    var owner = ownerNode(el);
    if (hoverEl && hoverEl !== owner) hoverEl.classList.remove("lumen-hover");
    hoverEl = owner;
  });
  document.addEventListener("mouseout", function (event) { if (!event.relatedTarget) hideHover(); });
```
In the capture-phase click handler, after `setSelected(el)` (the owning node — keep it), add:
```js
      var target = event.target;
      if (target && !isBridgeEl(target) && target !== document.body) {
        var address = addressOf(target);
        if (address) {
          var r = target.getBoundingClientRect();
          post("annotate", {
            address: address,
            name: labelFor(target, address),
            textLike: TEXT_LIKE.test(address.tag) && (target.textContent || "").trim().length > 0,
            geometry: { viewport: rectInfo(r, 0, 0), document: rectInfo(r, window.scrollX, window.scrollY) }
          });
        }
      }
```
Badges — inbound handler (where `select-node`/`clear` are handled):
```js
      if (data.type === "annotations") {
        if (!badgeLayer) { badgeLayer = document.createElement("div"); badgeLayer.className = "lumen-annotation-layer"; document.body.appendChild(badgeLayer); }
        badgeLayer.innerHTML = "";
        (data.items || []).forEach(function (item) {
          var el = resolveAddress(item.address); if (!el) return;
          var rect = el.getBoundingClientRect();
          var outline = document.createElement("div"); outline.className = "lumen-annotation-outline"; placeBox(outline, rect); badgeLayer.appendChild(outline);
          var badge = document.createElement("div"); badge.className = "lumen-annotation-badge"; badge.textContent = String(item.n);
          badge.style.left = (rect.right + window.scrollX - 9) + "px"; badge.style.top = (rect.top + window.scrollY - 9) + "px"; badgeLayer.appendChild(badge);
        });
        return;
      }
```
with
```js
  function resolveAddress(address) {
    if (!address || typeof address.nodeId !== "string") return null;
    var owner = document.querySelector('[data-node-id="' + CSS.escape(address.nodeId) + '"]');
    if (!owner || !address.path) return owner;
    var cur = owner, parts = address.path.split(" > ");
    for (var i = 0; i < parts.length; i++) {
      var m = /^:nth-child\((\d+)\)$/.exec(parts[i]); if (!m) return null;
      var n = parseInt(m[1], 10), sib = cur.firstElementChild, count = 0, next = null;
      while (sib) { if (!isBridgeEl(sib)) { count += 1; if (count === n) { next = sib; break; } } sib = sib.nextElementSibling; }
      if (!next) return null; cur = next;
    }
    return cur;
  }
```
Re-run the last `annotations` payload on `resize`/`scroll` (store it in `lastAnnotations` and call the same renderer from the existing metrics refresh).

Also mark the fragment element in the render so `addressOf` can tell a fragment root from a vocabulary node: in `crates/lumen-web/src/render.rs`, the Fragment arm's wrapper gets ` data-fragment-root="true"` next to `node_attr(out)` (editor mode only). This is a one-attribute engine change → run the full engine gate (Global Constraints) at the end of this task, including the helper rebuild and stack restart.

- [ ] **Step 5: Run** — `pytest apps/api/tests/test_web_bridge_annotations.py apps/api/tests/test_fragment_mobility.py -q` → PASS; engine gate → all green; restart the stack.

- [ ] **Step 6: Manual check** — open the Ramp page in Edit mode: hovering the Visa card image inside the "why" band shows an outline and `img · …` or `img`; hovering a band shows "Hero — …"; clicking posts `annotate` (see it in the browser console via the shell's message listener in Task 6, or temporarily `console.log` in the handler — remove before commit).

- [ ] **Step 7: Commit**
```bash
git add subsystems/clue-design/apps/api/lumen_api/web_bridge.py subsystems/clue-design/apps/api/tests/test_web_bridge_annotations.py subsystems/clue-design/crates/lumen-web/src/render.rs
git commit -m "feat(design-api): bridge hovers every element with a name chip and posts annotate addresses; numbered badges (R-A1, R-A4)"
```

---

### Task 6: Shell — annotation state, comment box, badges

**Files:**
- Modify: `apps/frontend/src/features/design-editor/engine/webBridge.ts` (types + `validateBridgeMessage` + outbound builder)
- Create/Modify: `apps/frontend/src/features/design-editor/engine/webBridge.test.ts` (extend if it exists)
- Create: `apps/frontend/src/features/design-editor/adapter/annotations.ts` (+ `.test.ts`) — pure reducer
- Create: `apps/frontend/src/features/design-editor/hooks/use-web-annotations.ts`
- Modify: `apps/frontend/src/features/design-editor/hooks/use-web-bridge-selection.ts` (`onAnnotate` callback; forward `annotations` post)
- Create: `apps/frontend/src/features/design-editor/components/web-annotation-popover.logic.ts` (+ `.test.ts`), `web-annotation-popover.tsx`, `web-annotation-popover.module.css`
- Modify: `apps/frontend/src/features/design-editor/components/web-artifact-canvas.tsx` (render the popover next to the rich-text toolbar; expose `postAnnotations`)
- Modify: `apps/frontend/src/features/design-editor/hooks/use-web-editing-session.ts` (own the hook; expose `annotations`)

**Interfaces:**
```ts
// webBridge.ts
export interface WebElementAddress { nodeId: string; path?: string; slot?: string; tag: string }
export interface WebAnnotateEvent { address: WebElementAddress; name: string; textLike: boolean; geometry: WebNodeGeometry }
// WebBridgeInbound gains: | { type: "annotate"; event: WebAnnotateEvent }
export function webBridgeAnnotationsMessage(nonce: string, items: { address: WebElementAddress; n: number }[]): { channel; nonce; type: "annotations"; items }
export function addressKey(a: WebElementAddress): string        // `${nodeId}#${path ?? ""}`
export function addressObjectId(a: WebElementAddress): string   // `${nodeId}` or `${nodeId}#${path}` (spec §3.5)

// adapter/annotations.ts
export interface WebAnnotation { n: number; address: WebElementAddress; name: string; note: string; pageId: string; textLike: boolean }
export interface AnnotationState { items: WebAnnotation[]; pending: { address; name; textLike; geometry; pageId } | null; nextN: number }
export type AnnotationAction =
  | { type: "open"; address; name; textLike; geometry; pageId }
  | { type: "dismiss" }
  | { type: "add"; note: string }          // commits pending → items (ignored when note is blank)
  | { type: "remove"; n: number }
  | { type: "clear" };
export function annotationsReducer(state: AnnotationState, action: AnnotationAction): AnnotationState
export const EMPTY_ANNOTATIONS: AnnotationState

// hooks/use-web-annotations.ts
export function useWebAnnotations(documentId: string | null, pageId: string | null): {
  state: AnnotationState; open(...); dismiss(); add(note: string): WebAnnotation | null; remove(n: number); clear();
  itemsForPage(pageId: string): { address; n }[];
}
```

- [ ] **Step 1: Failing tests**

`adapter/annotations.test.ts`:
```ts
import assert from "node:assert/strict";
import test from "node:test";
import { annotationsReducer, EMPTY_ANNOTATIONS } from "./annotations";

const geometry = { viewport: { x: 1, y: 2, width: 3, height: 4 }, document: { x: 1, y: 2, width: 3, height: 4 } };
const open = { type: "open" as const, address: { nodeId: "frg_a", path: ":nth-child(1) > :nth-child(2)", tag: "h2" }, name: "h2 · headline", textLike: true, geometry, pageId: "home" };

test("open then add numbers the annotation and clears the pending box", () => {
  let s = annotationsReducer(EMPTY_ANNOTATIONS, open);
  assert.ok(s.pending);
  s = annotationsReducer(s, { type: "add", note: "Make this shorter" });
  assert.equal(s.pending, null);
  assert.deepEqual(s.items.map((i) => [i.n, i.note, i.pageId]), [[1, "Make this shorter", "home"]]);
  assert.equal(s.nextN, 2);
});

test("a blank note adds nothing (Add is inert on an empty box)", () => {
  const s = annotationsReducer(annotationsReducer(EMPTY_ANNOTATIONS, open), { type: "add", note: "   " });
  assert.equal(s.items.length, 0);
  assert.ok(s.pending, "the box stays open");
});

test("numbers are never reused after a remove (R-A3: session-only, but stable while it lasts)", () => {
  let s = annotationsReducer(EMPTY_ANNOTATIONS, open);
  s = annotationsReducer(s, { type: "add", note: "one" });
  s = annotationsReducer(s, open);
  s = annotationsReducer(s, { type: "add", note: "two" });
  s = annotationsReducer(s, { type: "remove", n: 1 });
  s = annotationsReducer(s, open);
  s = annotationsReducer(s, { type: "add", note: "three" });
  assert.deepEqual(s.items.map((i) => i.n), [2, 3]);
});

test("clear drops everything", () => {
  const s = annotationsReducer(annotationsReducer(annotationsReducer(EMPTY_ANNOTATIONS, open), { type: "add", note: "x" }), { type: "clear" });
  assert.deepEqual(s, EMPTY_ANNOTATIONS);
});
```

`engine/webBridge.test.ts` (add):
```ts
test("an annotate message is validated into a typed event, and addresses key/serialise per spec §3.5", () => {
  const event = { data: { channel: WEB_BRIDGE_CHANNEL, nonce: "n", type: "annotate",
    address: { nodeId: "frg_a", path: ":nth-child(2)", slot: "headline", tag: "h2" }, name: "h2 · headline", textLike: true,
    geometry: { viewport: { x: 0, y: 0, width: 1, height: 1 }, document: { x: 0, y: 0, width: 1, height: 1 } } } } as MessageEvent;
  const message = validateBridgeMessage(event, "n", null);
  assert.equal(message?.type, "annotate");
  assert.equal(addressObjectId({ nodeId: "frg_a", path: ":nth-child(2)", tag: "h2" }), "frg_a#:nth-child(2)");
  assert.equal(addressObjectId({ nodeId: "txt", tag: "p" }), "txt");
  assert.equal(addressKey({ nodeId: "txt", tag: "p" }), "txt#");
});
```
(Match the file's existing way of faking `MessageEvent` + source window; if `validateBridgeMessage` checks `event.source === contentWindow`, pass `null` for both as the existing tests do.)

`components/web-annotation-popover.logic.test.ts`:
```ts
import assert from "node:assert/strict";
import test from "node:test";
import { computePopoverPosition } from "./web-annotation-popover.logic";

test("the box sits to the right of the element inside the viewport, else flips left", () => {
  const iframe = { left: 100, top: 50, width: 1000, height: 800 };
  const el = { x: 200, y: 100, width: 300, height: 60 };
  assert.deepEqual(computePopoverPosition(iframe, el, { width: 320, height: 180 }, { width: 1400, height: 900 }), { left: 100 + 200 + 300 + 12, top: 50 + 100 });
  const farRight = { x: 800, y: 100, width: 190, height: 60 };
  assert.deepEqual(computePopoverPosition(iframe, farRight, { width: 320, height: 180 }, { width: 1400, height: 900 }), { left: 100 + 800 - 320 - 12, top: 150 });
});
```

- [ ] **Step 2: Run** — the three test files → FAIL (modules missing).

- [ ] **Step 3: Implement the reducer**

```ts
// adapter/annotations.ts
import type { WebElementAddress, WebNodeGeometry } from "../engine/webBridge";

export interface WebAnnotation { n: number; address: WebElementAddress; name: string; note: string; pageId: string; textLike: boolean }
export interface PendingAnnotation { address: WebElementAddress; name: string; textLike: boolean; geometry: WebNodeGeometry; pageId: string }
export interface AnnotationState { items: WebAnnotation[]; pending: PendingAnnotation | null; nextN: number }
export type AnnotationAction =
  | ({ type: "open" } & PendingAnnotation)
  | { type: "dismiss" }
  | { type: "add"; note: string }
  | { type: "remove"; n: number }
  | { type: "clear" };

/** Ruling R-A3: session-only. This state lives in React memory for one document and dies
 * with it; the sent turn's context refs are the durable record. */
export const EMPTY_ANNOTATIONS: AnnotationState = { items: [], pending: null, nextN: 1 };

export function annotationsReducer(state: AnnotationState, action: AnnotationAction): AnnotationState {
  switch (action.type) {
    case "open": {
      const { type: _t, ...pending } = action;
      return { ...state, pending };
    }
    case "dismiss":
      return { ...state, pending: null };
    case "add": {
      const note = action.note.trim();
      if (!state.pending || note.length === 0) return state;
      const item: WebAnnotation = { n: state.nextN, note, address: state.pending.address, name: state.pending.name, pageId: state.pending.pageId, textLike: state.pending.textLike };
      return { items: [...state.items, item], pending: null, nextN: state.nextN + 1 };
    }
    case "remove":
      return { ...state, items: state.items.filter((i) => i.n !== action.n) };
    case "clear":
      return EMPTY_ANNOTATIONS;
  }
}
```

- [ ] **Step 4: Implement the bridge types and validator**

In `webBridge.ts` add the interfaces above; in `validateBridgeMessage` add:
```ts
  if (data.type === "annotate") {
    const a = data.address as Partial<WebElementAddress> | undefined;
    if (!a || typeof a.nodeId !== "string" || typeof a.tag !== "string") return null;
    const path = typeof a.path === "string" && /^(:nth-child\(\d+\)( > )?)+$/.test(a.path) ? a.path : undefined;
    const slot = typeof a.slot === "string" && a.slot.length > 0 ? a.slot : undefined;
    const geometry = coerceGeometry(data.geometry);   // reuse the geometry coercion `coerceNodeInfo` uses
    if (!geometry) return null;
    return { type: "annotate", event: { address: { nodeId: a.nodeId, path, slot, tag: a.tag }, name: typeof data.name === "string" ? data.name : a.tag, textLike: data.textLike === true, geometry } };
  }
```
plus:
```ts
export function addressKey(a: WebElementAddress): string { return `${a.nodeId}#${a.path ?? ""}`; }
export function addressObjectId(a: WebElementAddress): string { return a.path ? `${a.nodeId}#${a.path}` : a.nodeId; }
export function webBridgeAnnotationsMessage(nonce: string, items: { address: WebElementAddress; n: number }[]) {
  return { channel: WEB_BRIDGE_CHANNEL, nonce, type: "annotations" as const, items };
}
```

- [ ] **Step 5: Implement the hook, position logic, popover, and wiring**

`hooks/use-web-annotations.ts`:
```ts
"use client";
import { useCallback, useEffect, useReducer, useRef } from "react";
import { annotationsReducer, EMPTY_ANNOTATIONS, type PendingAnnotation, type WebAnnotation } from "../adapter/annotations";

export function useWebAnnotations(documentId: string | null, pageId: string | null) {
  const [state, dispatch] = useReducer(annotationsReducer, EMPTY_ANNOTATIONS);
  const forDoc = useRef(documentId);
  useEffect(() => { if (forDoc.current !== documentId) { forDoc.current = documentId; dispatch({ type: "clear" }); } }, [documentId]);   // R-A3: a document switch drops everything
  const open = useCallback((pending: Omit<PendingAnnotation, "pageId">) => { if (pageId) dispatch({ type: "open", ...pending, pageId }); }, [pageId]);
  const add = useCallback((note: string): WebAnnotation | null => {
    const before = state.nextN; dispatch({ type: "add", note });
    return note.trim().length > 0 && state.pending ? { n: before, note: note.trim(), address: state.pending.address, name: state.pending.name, pageId: state.pending.pageId, textLike: state.pending.textLike } : null;
  }, [state]);
  const itemsForPage = useCallback((page: string) => state.items.filter((i) => i.pageId === page).map((i) => ({ address: i.address, n: i.n })), [state.items]);
  return { state, open, add, dismiss: () => dispatch({ type: "dismiss" }), remove: (n: number) => dispatch({ type: "remove", n }), clear: () => dispatch({ type: "clear" }), itemsForPage };
}
```
`components/web-annotation-popover.logic.ts`:
```ts
export interface Box { width: number; height: number }
export function computePopoverPosition(iframe: { left: number; top: number; width: number; height: number }, el: { x: number; y: number; width: number; height: number }, box: Box, viewport: Box): { left: number; top: number } {
  const GAP = 12;
  const right = iframe.left + el.x + el.width + GAP;
  const left = right + box.width <= viewport.width ? right : iframe.left + el.x - box.width - GAP;
  const top = Math.min(Math.max(0, iframe.top + el.y), viewport.height - box.height);
  return { left: Math.max(0, left), top };
}
```
`components/web-annotation-popover.tsx` — a `position: fixed` card rendered by `WebArtifactCanvas` when `pending` is set: header row with a name chip (`pending.name`) and a close button; `<textarea placeholder="Edit or ask a question" autoFocus>`; footer with a trash icon (dismiss), **Add** (primary; disabled while blank; calls `onAdd(note)`), **Send to chat** (calls `onSend(note)`), and, when `pending.textLike`, an **Edit text** link-button calling `onEditText(pending.address)` (wired in Task 15/16; until then it is rendered only when `onEditText` is provided). Escape → dismiss. Click outside the card and outside the iframe → dismiss. Styles copy the token usage of `web-rich-text-toolbar.module.css` (same surface, border, shadow variables).

Wiring: `useWebBridgeSelection` gains `onAnnotate?: (event: WebAnnotateEvent) => void` and forwards `annotate` messages to it (ignored while `editingRef.current`). `WebArtifactCanvas` gains props `annotations: { pending; itemsForPage(pageId); open; dismiss; add; }` and a `postAnnotations(items)` that posts `webBridgeAnnotationsMessage(nonce, items)` on every items change and on every `ready`. `useWebEditingSession` owns `useWebAnnotations(activeDocumentId, activePageId)` and exposes it as `annotations`; both mounts (`chat-surface.tsx`, `editor-surface.tsx`) pass `session.annotations` to the canvas.

- [ ] **Step 6: Run** — the three test files and then `npm test` → PASS. `npm run lint && npm run build` → clean.

- [ ] **Step 7: Manual check** — click the Ramp headline: a comment box opens beside it with chip "Hero — …" (band) or "h2 · headline" (inner); type and Add: box closes, badge "1" appears on the element; reload: gone.

- [ ] **Step 8: Commit**
```bash
git add apps/frontend/src/features/design-editor
git commit -m "feat(frontend): web annotations — click opens an anchored comment box, Add stores a numbered session-only annotation with a badge (R-A1..R-A3)"
```

---

### Task 7: Composer chips and the turn body carry annotations

**Files:**
- Modify: `apps/frontend/src/features/projects/model/chat-turn.ts` (`TurnContextReference.note?`, `turnRequestBody` emits `note`)
- Modify: `apps/frontend/src/features/projects/model/chat-schemas.test.ts`
- Modify: `apps/frontend/src/features/chat-shell/model/edit-targets.ts` (+ `.test.ts`): `annotationContextRefs(documentId, version, items)`
- Modify: `apps/frontend/src/features/chat-shell/components/chat-surface.tsx` (web chips; submit snapshot; "Send to chat")

**Interfaces:**
```ts
// chat-turn.ts
export interface TurnContextReference { objectId: string; objectType: TurnContextObjectType; version: number | null; note?: string }
// wire: context_refs[i].note present only when defined
// edit-targets.ts
export function annotationContextRefs(snapshot: { documentId: string; documentVersion: number | null; items: readonly WebAnnotation[] } | null): TurnContextReference[]
// → [design_document ref] + one design_node ref per item, in `n` order, objectId = addressObjectId(item.address), note = `${item.n}. ${item.note}`
export function annotationChips(items: readonly WebAnnotation[]): { n: number; label: string }[]   // label = first 28 chars of note + "…"
```

- [ ] **Step 1: Failing tests**

`chat-schemas.test.ts` (add):
```ts
test("a context ref's note rides the wire only when present", () => {
  assert.deepEqual(
    turnRequestBody({ kind: "message", message: "fix", contextRefs: [
      { objectId: "doc_1", objectType: "design_document", version: 3 },
      { objectId: "frg_a#:nth-child(2)", objectType: "design_node", version: 3, note: "1. Make this shorter" },
    ] }),
    { message: "fix", context_refs: [
      { object_type: "design_document", object_id: "doc_1", version: 3 },
      { object_type: "design_node", object_id: "frg_a#:nth-child(2)", version: 3, note: "1. Make this shorter" },
    ], attachment_refs: [], agent_profile_id: null },
  );
});
```
`edit-targets.test.ts` (add):
```ts
test("annotations become one document ref plus ordered noted node refs; chips are numbered", () => {
  const items = [
    { n: 2, note: "Make the headline shorter and punchier please", address: { nodeId: "frg_a", path: ":nth-child(1)", tag: "h2" }, name: "h2", pageId: "home", textLike: true },
    { n: 3, note: "Remove", address: { nodeId: "sec_b", tag: "section" }, name: "Proof", pageId: "home", textLike: false },
  ];
  assert.deepEqual(annotationContextRefs({ documentId: "doc_1", documentVersion: 9, items }), [
    { objectId: "doc_1", objectType: "design_document", version: 9 },
    { objectId: "frg_a#:nth-child(1)", objectType: "design_node", version: 9, note: "2. Make the headline shorter and punchier please" },
    { objectId: "sec_b", objectType: "design_node", version: 9, note: "3. Remove" },
  ]);
  assert.deepEqual(annotationChips(items), [{ n: 2, label: "Make the headline shorter an…" }, { n: 3, label: "Remove" }]);
});
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement**

`chat-turn.ts`: add `note?: string` to the interface; in `turnRequestBody` map `...(reference.note !== undefined ? { note: reference.note } : {})` into each ref.

`edit-targets.ts`:
```ts
import { addressObjectId } from "@/features/design-editor/engine/webBridge";
import type { WebAnnotation } from "@/features/design-editor/adapter/annotations";

export function annotationContextRefs(snapshot: { documentId: string; documentVersion: number | null; items: readonly WebAnnotation[] } | null): TurnContextReference[] {
  if (snapshot === null || snapshot.items.length === 0) return [];
  const ordered = [...snapshot.items].sort((a, b) => a.n - b.n);
  return [
    { objectId: snapshot.documentId, objectType: "design_document", version: snapshot.documentVersion },
    ...ordered.map((item): TurnContextReference => ({ objectId: addressObjectId(item.address), objectType: "design_node", version: snapshot.documentVersion, note: `${item.n}. ${item.note}` })),
  ];
}
export function annotationChips(items: readonly WebAnnotation[]): { n: number; label: string }[] {
  return [...items].sort((a, b) => a.n - b.n).map((i) => ({ n: i.n, label: i.note.length > 28 ? `${i.note.slice(0, 28).trimEnd()}…` : i.note }));
}
```
`chat-surface.tsx`: introduce `const webAnnotationsEnabled = chat.designLegOpen && shell.artifactKind === "web" && session.activeDocumentId !== null;` render the edit-target bar for web with label "Annotations" and chips `"{n} {label}"` (remove → `session.annotations.remove(n)`); in `onSubmit`, when web, build `annotationContextRefs({ documentId: session.activeDocumentId, documentVersion: session.webSelection.document?.currentVersion ?? null, items: session.annotations.state.items })` and spread into `contextRefs`; after an accepted submit call `session.annotations.clear()`. **Send to chat**: the popover's `onSend(note)` calls `session.annotations.add(note)` then triggers the composer's submit with the composer's current text (empty text is allowed when at least one annotation exists — the message then reads `"See annotations."`; add that constant as `ANNOTATIONS_ONLY_MESSAGE`).

- [ ] **Step 4: Run** — `npm test`, `npm run lint`, `npm run build` → green.

- [ ] **Step 5: Commit**
```bash
git add apps/frontend/src/features/projects/model/chat-turn.ts apps/frontend/src/features/projects/model/chat-schemas.test.ts apps/frontend/src/features/chat-shell
git commit -m "feat(frontend): annotations ride the turn as noted design_node refs; numbered chips above the composer; Send to chat (R-A2)"
```

---

### Task 8: Platform — `note` on context refs, end to end, with a migration

**Files:**
- Modify: `platform/api/clue_api/chat/schemas.py` (`ContextRefRequest.note`)
- Modify: `platform/agents/clue_agents/contracts.py` (`DomainObjectRef.note`)
- Modify: `platform/api/clue_api/chat/router.py` (the three `DomainObjectRef(` constructions at ~L588, ~L1236, ~L2064 pass `note=ref.note`)
- Modify: `platform/api/clue_api/agent_turn_submission.py` (`SubmissionContextRefRow.note`; INSERT/SELECT include `note`; the read path that rebuilds `DomainObjectRef`s from rows passes `note`)
- Create: `alembic/versions/<hash>_context_ref_note.py`
- Test: `tests/api/test_agent_turn_submission_note.py` (DB-gated like its siblings; copy the fixture style of the nearest `test_agent_turn_submission*.py`)

**Interfaces:**
- `ContextRefRequest.note: str | None = Field(default=None, max_length=2_000)`
- `DomainObjectRef.note: str | None = Field(default=None, max_length=2_000)` (FrozenContract; default keeps every existing construction valid)
- Column `agent_turn_submission_context_ref.note TEXT NULL`

- [ ] **Step 1: Migration**

```bash
cd <repo root> && .venv/bin/alembic revision -m "context ref note"
```
Edit the generated file: `down_revision = "8079022e5802"`,
```python
def upgrade() -> None:
    op.add_column("agent_turn_submission_context_ref", sa.Column("note", sa.Text(), nullable=True))

def downgrade() -> None:
    op.drop_column("agent_turn_submission_context_ref", "note")
```
Run: `.venv/bin/alembic heads` → exactly one head (the new id). Run `make db-smoke`.

- [ ] **Step 2: Failing test**

```python
# tests/api/test_agent_turn_submission_note.py
import pytest
from clue_agents.contracts import DomainObjectRef
from clue_api.agent_turn_submission import insert_submission, load_submission_context_refs  # use the real read fn name from the module

@pytest.mark.asyncio
async def test_a_context_ref_note_round_trips(db_conn, submission_kwargs):   # reuse the sibling test's fixtures
    ref = DomainObjectRef(workspace_id=submission_kwargs["workspace_id"], object_type="design_node", object_id="frg_a#:nth-child(2)", version=9, note="1. Make this shorter")
    row, created = await insert_submission(db_conn, context_refs=[ref], **submission_kwargs)
    assert created
    refs = await load_submission_context_refs(db_conn, turn_id=row.turn_id, workspace_id=row.workspace_id)
    assert refs[0].note == "1. Make this shorter"
```
And a schema test (no DB) in `tests/api/test_chat_schemas_note.py`:
```python
from clue_api.chat.schemas import ContextRefRequest
def test_note_is_optional_and_bounded():
    assert ContextRefRequest(object_type="design_node", object_id="x").note is None
    assert ContextRefRequest(object_type="design_node", object_id="x", note="hi").note == "hi"
```

- [ ] **Step 3: Run** → FAIL (`note` unexpected / column missing).

- [ ] **Step 4: Implement** — add the fields; in `insert_submission` add `note` to the INSERT columns/params (`"note": ref.note`); in the SELECT add `note`; where rows become `DomainObjectRef`s pass `note=row.note`; in `router.py` pass `note=ref.note` at each construction.

- [ ] **Step 5: Run** — `.venv/bin/python -m pytest tests/api -q -k "submission or chat_schemas"` → PASS; `make db-smoke` → PASS.

- [ ] **Step 6: Commit**
```bash
git add alembic/versions platform/api/clue_api/chat/schemas.py platform/agents/clue_agents/contracts.py platform/api/clue_api/chat/router.py platform/api/clue_api/agent_turn_submission.py tests/api/test_agent_turn_submission_note.py tests/api/test_chat_schemas_note.py
git commit -m "feat(platform): a context ref may carry a note — schema, contract, durable column, replay"
```

---

### Task 9: Platform — web legs pass targets and notes into the web turn request

**Files:**
- Modify: `platform/api/clue_api/design_turn_targets.py` — add `resolve_web_targets(focus_refs) -> ResolvedWebTargets`
- Modify: `platform/api/clue_api/design_leg_wiring.py` (~L1345: the web request dict)
- Test: `tests/api/test_design_turn_targets.py`

**Interfaces:**
```python
@dataclass(frozen=True)
class WebTargetNote: target: str; path: str | None; note: str | None
@dataclass(frozen=True)
class ResolvedWebTargets: target_node_ids: tuple[str, ...]; target_notes: tuple[WebTargetNote, ...]
def resolve_web_targets(focus_refs: Sequence[DomainObjectRef]) -> ResolvedWebTargets | None
```
Web request gains `"target_node_ids": [...]` and `"target_notes": [{"target","path","note"}, ...]` only when at least one `design_node` ref rides (the F4 v1 freeze: an unconditional key would change a byte-for-byte contract).

- [ ] **Step 1: Failing test** (append to `tests/api/test_design_turn_targets.py`)
```python
from clue_agents.contracts import DomainObjectRef
from clue_api.design_turn_targets import resolve_web_targets

def _ref(object_id, note=None, object_type="design_node"):
    return DomainObjectRef(workspace_id="ws_1", object_type=object_type, object_id=object_id, version=9, note=note)

def test_web_targets_split_inner_paths_and_keep_order_and_notes():
    resolved = resolve_web_targets([_ref("doc_1", object_type="design_document"), _ref("frg_a#:nth-child(1) > :nth-child(2)", "1. Shorter"), _ref("sec_b", "2. Remove"), _ref("frg_a#:nth-child(3)", "3. Bolder")])
    assert resolved.target_node_ids == ("frg_a", "sec_b")           # owning nodes, deduplicated, first-seen order
    assert [(n.target, n.path, n.note) for n in resolved.target_notes] == [
        ("frg_a", ":nth-child(1) > :nth-child(2)", "1. Shorter"), ("sec_b", None, "2. Remove"), ("frg_a", ":nth-child(3)", "3. Bolder")]

def test_no_design_node_refs_means_no_targets():
    assert resolve_web_targets([_ref("doc_1", object_type="design_document")]) is None
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement**
```python
def resolve_web_targets(focus_refs):
    notes, ids = [], []
    for ref in focus_refs:
        if ref.object_type != "design_node":
            continue
        target, _, path = ref.object_id.partition("#")
        notes.append(WebTargetNote(target=target, path=path or None, note=ref.note))
        if target not in ids:
            ids.append(target)
    if not notes:
        return None
    return ResolvedWebTargets(target_node_ids=tuple(ids), target_notes=tuple(notes))
```
In `design_leg_wiring.py` web branch: `web_targets = resolve_web_targets(focus_refs)` and spread `{"target_node_ids": list(web_targets.target_node_ids), "target_notes": [asdict(n) for n in web_targets.target_notes]}` when not None. Update the F4 comment: targets now ride for web when the user pointed at something.

- [ ] **Step 4: Run** — `pytest tests/api/test_design_turn_targets.py -q` and the design-leg tests (`-k design_leg`) → PASS.

- [ ] **Step 5: Commit**
```bash
git add platform/api/clue_api/design_turn_targets.py platform/api/clue_api/design_leg_wiring.py tests/api/test_design_turn_targets.py
git commit -m "feat(platform): web legs pass annotated targets (node ids + inner paths + notes) into the web turn request"
```

---

### Task 10: Design API — the TURN TARGET paragraph carries path and note, resolved against the clone

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/models.py` (`WebTurnTargetNote`, `WebTurnRequest.target_notes`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py` (`_describe_web_turn_targets(web_doc, target_node_ids, fragment_meta=None, target_notes=None, read_source=None)`, `run_web_agent_turn(..., target_notes=None)`, the two `/web/turns` call sites ~L3285/L3362, config `turn_target_notes`)
- Create: `subsystems/clue-design/apps/api/lumen_api/fragments/paths.py` — `resolve_structural_path(html, path) -> {"tag": str, "text": str, "slot": str|None} | None`
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/config.py` (`turn_target_notes: list[dict] | None = None`)
- Tests: `subsystems/clue-design/apps/api/tests/test_fragment_paths.py`, `test_web_turn_pages.py`

**Interfaces:**
- `WebTurnTargetNote(BaseModel)`: `target: str`, `path: Optional[str] = None` (regex `^(:nth-child\(\d+\)( > )?)+$`, max 256), `note: Optional[str] = None` (max 2000)
- Paragraph format per note: `\n\nANNOTATION {n}: on {kind} "{name}" (page `{page}`, section `{sec}`){inner} — "{note}"` where `{inner}` = `, element `h2 · headline` at path `:nth-child(1) > :nth-child(2)` reading "Card infrastructure economics…"` when the path resolves, or `, element at path … which no longer resolves in that section — use your judgment` when it does not. `{n}` is parsed from a leading `"N. "` in the note when present, else the 1-based order.

- [ ] **Step 1: Failing tests**

```python
# apps/api/tests/test_fragment_paths.py
from lumen_api.fragments.paths import resolve_structural_path
HTML = '<section><div><h2 data-lumen-slot="headline">Card <em>economics</em></h2><p>Body</p></div><img src="x"></section>'
def test_a_path_resolves_to_tag_text_and_slot():
    assert resolve_structural_path(HTML, ":nth-child(1) > :nth-child(1)") == {"tag": "h2", "text": "Card economics", "slot": "headline"}
    assert resolve_structural_path(HTML, ":nth-child(1) > :nth-child(2)") == {"tag": "p", "text": "Body", "slot": None}
    assert resolve_structural_path(HTML, ":nth-child(2)") == {"tag": "img", "text": "", "slot": None}
def test_a_dead_or_malformed_path_is_none():
    assert resolve_structural_path(HTML, ":nth-child(9)") is None
    assert resolve_structural_path(HTML, "div > h2") is None
```
Append to `test_web_turn_pages.py`:
```python
def test_annotations_are_numbered_and_resolved_against_the_clone():
    from lumen_api.main import _describe_web_turn_targets
    frag = "frag_" + "ab" * 8
    doc = {"pages": [{"id": "home", "root": "r", "nodes": {
        "r": {"id": "r", "kind": "container", "children": ["s"]},
        "s": {"id": "s", "kind": "section", "children": ["f"]},
        "f": {"id": "f", "kind": "fragment", "fragment_id": frag}}}]}
    html = '<section><h2 data-lumen-slot="headline">Card economics</h2></section>'
    text = _describe_web_turn_targets(doc, ["f"], fragment_meta={frag: {"label": "Stripe hero", "section_role": "hero"}},
        target_notes=[{"target": "f", "path": ":nth-child(1)", "note": "1. Make this shorter"}, {"target": "f", "path": ":nth-child(7)", "note": "2. Bolder"}],
        read_source=lambda fid: {"html": html})
    assert 'ANNOTATION 1: on fragment "Hero — Stripe hero"' in text
    assert "element `h2 · headline` at path `:nth-child(1)` reading \"Card economics\"" in text
    assert '"1. Make this shorter"' in text
    assert "ANNOTATION 2" in text and "no longer resolves" in text
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement**

`fragments/paths.py`:
```python
import re
from selectolax.lexbor import LexborHTMLParser
PATH_RE = re.compile(r"^(:nth-child\((\d+)\)( > )?)+$")
_STEP = re.compile(r":nth-child\((\d+)\)")

def resolve_structural_path(html: str, path: str):
    """Spec §3.1: the bridge's structural path, resolved against the artifact's stored HTML with
    the SAME rule (1-based, element children only). None when malformed or dead — reported,
    never guessed."""
    if not PATH_RE.match(path or ""):
        return None
    tree = LexborHTMLParser(html)
    body = tree.body
    if body is None:
        return None
    cur = body
    for step in _STEP.findall(path):
        n = int(step)
        children = [c for c in cur.iter(include_text=False)] if hasattr(cur, "iter") else []
        children = [c for c in cur.child_nodes() if c.tag not in ("-text", "-comment")] if hasattr(cur, "child_nodes") else children
        if n < 1 or n > len(children):
            return None
        cur = children[n - 1]
    return {"tag": cur.tag, "text": " ".join((cur.text(deep=True) or "").split()), "slot": cur.attributes.get("data-lumen-slot")}
```
(Use whichever child-iteration the installed `selectolax.lexbor` exposes — `slots.py` in the same package already walks element children; copy its helper rather than guessing.)

In `main.py`, `_describe_web_turn_targets` gains `target_notes` and `read_source` (a callable `fragment_id -> {"html": ...}`; the route passes `registry.read_source`, the same seam `inspect_cloned_section` uses). Keep the existing per-target lines for targets that have NO note (unchanged behaviour); for each note produce the ANNOTATION line described above. `run_web_agent_turn` threads `target_notes` into `config.turn_target_notes` alongside `turn_target_node_ids`.

- [ ] **Step 4: Run** — `pytest apps/api/tests/test_fragment_paths.py apps/api/tests/test_web_turn_pages.py apps/api/tests/test_web_turns.py -q` → PASS.

- [ ] **Step 5: Commit**
```bash
git add subsystems/clue-design/apps/api/lumen_api/models.py subsystems/clue-design/apps/api/lumen_api/main.py subsystems/clue-design/apps/api/lumen_api/fragments/paths.py subsystems/clue-design/apps/agent_runtime/lumen_agent/config.py subsystems/clue-design/apps/api/tests
git commit -m "feat(design-api): annotated targets — numbered ANNOTATION lines with the inner element resolved against the clone's real HTML"
```

---

### Task 11: Agent — the ANNOTATIONS block in the solo prompt

**Files:**
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/prompts_web.py` (`build_web_solo_prompt(..., annotations: Sequence[Mapping] | None = None)`; block interpolated after `{account_block}` at ~L1291)
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/harness_web.py` (~L521/541: pass `annotations=runtime_config.turn_target_notes`)
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_web_solo_mode.py`

**Interfaces:** the block is present only when `annotations` is non-empty.

- [ ] **Step 1: Failing test** (append to `test_web_solo_mode.py`)
```python
def test_solo_prompt_carries_the_annotations_law_only_when_annotations_ride() -> None:
    base = {"doc_title": "T", "has_existing_content": True, "brand_card": "BRAND", "theme_token_names": "primary accent"}
    with_notes = build_web_solo_prompt(**base, annotations=[{"target": "frg_a", "path": ":nth-child(1)", "note": "1. Shorter"}])
    assert "ANNOTATIONS ARE THE BRIEF" in with_notes
    assert "inspect_cloned_section" in with_notes
    assert "confirm each annotation by its number" in with_notes
    assert "ANNOTATIONS ARE THE BRIEF" not in build_web_solo_prompt(**base)
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** — in `build_web_solo_prompt` add the parameter and:
```python
    annotations_block = (
        """
ANNOTATIONS ARE THE BRIEF. The marketer clicked elements on the live page and wrote a note on
each; they arrive below the brief as numbered ANNOTATION lines (rulings R-A1..R-A3, 2026-09-04).
- Work them in number order. Each one is a BOUNDED change to the element it names — the
  plan-sizing rule applies: one short paragraph per annotation, no full plan.
- An annotation inside a cloned band names the element by a structural path and its slot.
  Read that band with `inspect_cloned_section(frag_…)` and find the element by that path in
  the real HTML before you change anything. If the words are in a slot, REBIND the slot;
  otherwise DERIVE A VARIANT of that band with the smallest possible edit.
- A path that "no longer resolves" means the page moved under the marketer's pointer: say so
  in your summary and use your judgment about what they meant.
- Touch nothing an annotation does not name unless the message itself asks for it.
- In `finalize_web_run`, confirm each annotation by its number: what you changed, or why not.
"""
        if annotations
        else ""
    )
```
and interpolate `{annotations_block}` right after `{account_block}` in the template string. In `harness_web.py`, both `build_web_solo_prompt(` calls pass `annotations=runtime_config.turn_target_notes`.

- [ ] **Step 4: Run** — `pytest apps/agent_runtime/tests/test_web_solo_mode.py -q` → PASS; `ruff check` on the two files → clean.

- [ ] **Step 5: Live acceptance for Slice 2** — restart the stack. On the Ramp page in Edit mode: annotate the hero headline ("Shorter"), a "why" card title inside the clone ("Say 'interchange share' plainly"), and the close band ("Remove the third column"); Add each; press send with an empty composer. Trace the run: the worker log's brief carries three ANNOTATION lines; the agent inspects the band for the inner one; the finalize summary confirms 1, 2, 3 by number. Record timings in the memory note.

- [ ] **Step 6: Commit**
```bash
git add subsystems/clue-design/apps/agent_runtime/lumen_agent/prompts_web.py subsystems/clue-design/apps/agent_runtime/lumen_agent/harness_web.py subsystems/clue-design/apps/agent_runtime/tests/test_web_solo_mode.py _memory/2026-09-04-web-editor-annotations.md
git commit -m "feat(design-agent): the solo prompt honours numbered annotations in order, resolving clone paths through inspect_cloned_section"
```

---

# Slice 3 — Text edits inside clones (D-F3 amended)

### Task 12: Engine — `text_overrides` on the fragment node and the `set_fragment_text_override` operation

**Files:**
- Modify: `subsystems/clue-design/crates/lumen-web/src/doc.rs` (`FragmentTextOverride`, `WebNodeKind::Fragment.text_overrides`, bounds constants)
- Modify: `subsystems/clue-design/crates/lumen-web/src/ops.rs` (`WebOperation::SetFragmentTextOverride`, apply + inverse)
- Modify: `subsystems/clue-design/crates/lumen-web/src/validate.rs` (bounds; new codes `LUMW0440` bad path, `LUMW0441` too many overrides, `LUMW0442` text too long, `LUMW0443` size out of range)
- Tests: `#[cfg(test)]` in `ops.rs` and `validate.rs`

**Interfaces:**
```rust
// doc.rs
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct FragmentTextOverride {
    pub text: String,
    #[serde(default)] pub bold: bool,
    #[serde(default)] pub italic: bool,
    #[serde(default)] pub underline: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")] pub size: Option<i8>,
}
pub const MAX_FRAGMENT_TEXT_OVERRIDES: usize = 64;
pub const MAX_FRAGMENT_OVERRIDE_PATH_CHARS: usize = 256;
pub fn fragment_override_path_is_valid(path: &str) -> bool   // ^(:nth-child\(\d+\)( > )?)+$, each n ≥ 1
// WebNodeKind::Fragment { fragment_id, slots, #[serde(default, skip_serializing_if = "BTreeMap::is_empty")] text_overrides: BTreeMap<String, FragmentTextOverride> }
// ops.rs
WebOperation::SetFragmentTextOverride { page_id: PageId, id: NodeId, path: String, #[serde(default, skip_serializing_if = "Option::is_none")] r#override: Option<FragmentTextOverride> }
```
Wire kind: `"set_fragment_text_override"`; JSON field `"override"` (rename the Rust field with `#[serde(rename = "override")]`).

- [ ] **Step 1: Failing tests** (in `ops.rs` tests module; follow the `SetSlotKey` tests at ~L1655 for the doc fixture)
```rust
#[test]
fn set_fragment_text_override_applies_and_inverts() {
    let mut doc = doc_with_pinned_fragment();   // a page with one fragment node "frg" (copy the SetSlotKey fixture's shape)
    let set = WebOperation::SetFragmentTextOverride { page_id: page("home"), id: node("frg"), path: ":nth-child(1)".into(),
        r#override: Some(FragmentTextOverride { text: "Shorter".into(), bold: true, italic: false, underline: false, size: Some(1) }) };
    let inverse = apply_operations(&mut doc, &[set.clone()]).expect("applies");
    let frag = &doc.pages[0].nodes[&node("frg")];
    match &frag.kind { WebNodeKind::Fragment { text_overrides, .. } => assert_eq!(text_overrides[":nth-child(1)"].text, "Shorter"), _ => panic!() }
    assert_eq!(inverse, vec![WebOperation::SetFragmentTextOverride { page_id: page("home"), id: node("frg"), path: ":nth-child(1)".into(), r#override: None }]);
    apply_operations(&mut doc, &inverse).expect("inverse applies");
    match &doc.pages[0].nodes[&node("frg")].kind { WebNodeKind::Fragment { text_overrides, .. } => assert!(text_overrides.is_empty()), _ => panic!() }
}

#[test]
fn set_fragment_text_override_refuses_non_fragments_and_bad_paths() {
    let mut doc = doc_with_pinned_fragment();
    let bad_path = WebOperation::SetFragmentTextOverride { page_id: page("home"), id: node("frg"), path: "div > h2".into(), r#override: Some(FragmentTextOverride { text: "x".into(), bold: false, italic: false, underline: false, size: None }) };
    assert_eq!(apply_operations(&mut doc, &[bad_path]).unwrap_err().code, "op.override_path_invalid");
    let not_fragment = WebOperation::SetFragmentTextOverride { page_id: page("home"), id: node("sec"), path: ":nth-child(1)".into(), r#override: None };
    assert_eq!(apply_operations(&mut doc, &[not_fragment]).unwrap_err().code, "op.node_kind_mismatch");
}
```
`validate.rs` test: a fragment with 65 overrides → `LUMW0441`; text of 8193 bytes → `LUMW0442`; `size: Some(4)` → `LUMW0443`; path `":nth-child(0)"` → `LUMW0440`.

- [ ] **Step 2: Run** — `cd subsystems/clue-design && cargo test -p lumen-web` → FAIL to compile (new variants missing).

- [ ] **Step 3: Implement** — add the struct, the field with `#[serde(default, skip_serializing_if = "BTreeMap::is_empty")]` (every existing `WebNodeKind::Fragment { fragment_id, slots }` pattern gains `text_overrides: BTreeMap::new()` at construction and `..` in matches), the op variant, the apply arm:
```rust
WebOperation::SetFragmentTextOverride { page_id, id, path, r#override } => {
    if !fragment_override_path_is_valid(path) {
        return Err(WebOpError::new("op.override_path_invalid", format!("override path `{path}` is not a structural path")));
    }
    let page = require_page_mut(doc, page_id)?;
    let node = page.nodes.get_mut(id).ok_or_else(|| WebOpError::new("op.node_missing", format!("node `{id}` not found")))?;
    let WebNodeKind::Fragment { text_overrides, .. } = &mut node.kind else {
        return Err(WebOpError::new("op.node_kind_mismatch", format!("node `{id}` is not a cloned section")));
    };
    let previous = match r#override {
        Some(value) => text_overrides.insert(path.clone(), value.clone()),
        None => text_overrides.remove(path),
    };
    Ok(WebOperation::SetFragmentTextOverride { page_id: page_id.clone(), id: id.clone(), path: path.clone(), r#override: previous })
}
```
and the validation arm next to the existing Fragment checks (~L546). Add the D-F3 amendment note in `doc.rs` above the field: "Ruling R-A6 (founder, 2026-09-04): the ONE interior edit a human may make to a clone."

- [ ] **Step 4: Run** — `cargo test --workspace` → PASS.

- [ ] **Step 5: Commit**
```bash
git add subsystems/clue-design/crates/lumen-web/src/doc.rs subsystems/clue-design/crates/lumen-web/src/ops.rs subsystems/clue-design/crates/lumen-web/src/validate.rs
git commit -m "feat(lumen-web): fragment text overrides — the one interior human edit a clone allows (D-F3 amended, R-A6)"
```

---

### Task 13: Engine — the override render pass

**Files:**
- Modify: `subsystems/clue-design/crates/lumen-web/src/fragment.rs` (second walk after slots; new diagnostic `LUMW0444` override path did not resolve)
- Modify: `subsystems/clue-design/crates/lumen-web/src/render.rs` (Fragment arm passes `text_overrides` and the theme's size ramp)
- Test: `fragment.rs` tests module

**Interfaces:**
- `pub(crate) fn apply_fragment_text_overrides(html: &str, overrides: &BTreeMap<String, FragmentTextOverride>, size_px: impl Fn(i8) -> Option<f32>, node_id: &NodeId, diagnostics: &mut Vec<Diagnostic>) -> String`
- Output for an override on `<h2 …>old</h2>` with `bold` + `size: Some(1)`: `<h2 … data-lumen-override=":nth-child(1)" style="font-size:1.125em">` + `<strong>new text</strong>` + `</h2>`; marks nest `strong > em > u`; size uses `em` multipliers from the ramp `[-3: 0.75, -2: 0.8125, -1: 0.875, 0: 1, 1: 1.125, 2: 1.25, 3: 1.5]` (this ramp is the theme-agnostic default; the theme's own ramp, when present, is passed by `render.rs` through `size_px`). The element's existing `style` attribute is preserved and the size appended.

- [ ] **Step 1: Failing tests** (in `fragment.rs` tests, reuse `doc_with`)
```rust
#[test]
fn an_override_replaces_text_and_wraps_marks_and_size() {
    let html = r#"<section><div><h2 data-lumen-slot="headline">Old <em>words</em></h2><p>Body</p></div></section>"#;
    let mut overrides = BTreeMap::new();
    overrides.insert(":nth-child(1) > :nth-child(1)".to_owned(), FragmentTextOverride { text: "New & better".into(), bold: true, italic: false, underline: true, size: Some(1) });
    let mut diags = Vec::new();
    let out = apply_fragment_text_overrides(html, &overrides, |_| None, &NodeId::from("frg"), &mut diags);
    assert!(out.contains(r#"<h2 data-lumen-slot="headline" data-lumen-override=":nth-child(1) > :nth-child(1)" style="font-size:1.125em"><strong><u>New &amp; better</u></strong></h2>"#), "{out}");
    assert!(out.contains("<p>Body</p>"));
    assert!(diags.is_empty());
}

#[test]
fn a_dead_override_path_leaves_the_element_and_says_so() {
    let html = "<section><p>Body</p></section>";
    let mut overrides = BTreeMap::new();
    overrides.insert(":nth-child(4)".to_owned(), FragmentTextOverride { text: "x".into(), bold: false, italic: false, underline: false, size: None });
    let mut diags = Vec::new();
    let out = apply_fragment_text_overrides(html, &overrides, |_| None, &NodeId::from("frg"), &mut diags);
    assert_eq!(out, html);
    assert_eq!(diags[0].code, "LUMW0444");
}

#[test]
fn an_override_wins_over_a_slot_value_on_the_same_element() {
    // Run the slot walk first (existing substitute_fragment_slots), then the override walk, and
    // assert the override's text is what remains.
}
```
(Write the third test fully using the existing slot test helpers `kinds`/`slots`.)

- [ ] **Step 2: Run** → FAIL to compile.

- [ ] **Step 3: Implement** — a quick_xml walk mirroring `substitute_fragment_slots`: maintain a stack of child counters (element children only, incremented on each `Event::Start`/`Event::Empty` at that depth); build the current path string as the stack of `:nth-child(n)` joined by `" > "`; when the current path is a key in `overrides`, emit the start tag with `data-lumen-override` and the size appended to `style`, then emit the wrapped, escaped text, then skip the element's original subtree (track depth until the matching `Event::End`), then emit the end tag. Void elements are never override targets (an `<img>` has no text) — skip and emit `LUMW0444`. Any override key not consumed by the end of the walk → `LUMW0444` with the path in the message. In `render.rs` the Fragment arm calls the slot walk then this walk, with `size_px` reading the theme's type ramp when the theme defines one (`theme.tokens` keys `text-size-*`), else `None` (the `em` default).

- [ ] **Step 4: Run** — `cargo test --workspace` → PASS. Then the FULL engine gate: `cargo build -p lumen-api-helper --release`, wasm build + handshake (must print HANDSHAKE OK), Python suites, stack restart.

- [ ] **Step 5: Commit**
```bash
git add subsystems/clue-design/crates/lumen-web/src/fragment.rs subsystems/clue-design/crates/lumen-web/src/render.rs
git commit -m "feat(lumen-web): render fragment text overrides after slot values — marks, size step, dead-path diagnostic"
```

---

### Task 14: API, agent inspect, and frontend write path for overrides

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/agent_cloned_sections.py` (`read_source` returns `text_overrides` for a given node when the caller passes the document node — extend `inspect_cloned_section` in `web_substrate.py` to list overrides found on any pinned node of that fragment on the page)
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/web_substrate.py` (`inspect_cloned_section` output gains `"text_overrides": [{node_id, path, text, bold, italic, underline, size}]`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py` (web/operations: no schema change needed — the engine validates the new kind; ADD the override path resolution check before apply: for each `set_fragment_text_override` op with a non-null override, resolve the path against the fragment's HTML via `fragments/paths.py`; refuse 422 with engine code `op.override_path_unresolved` when dead)
- Modify: `apps/frontend/src/features/design-editor/engine/webDocuments.ts` (`WebOperation` union + `setFragmentTextOverrideOp`; `WebNode.text_overrides?`)
- Modify: `apps/frontend/src/features/design-editor/hooks/use-inspector-writes.ts` (`setFragmentTextOverride(pageId, nodeId, path, override | null)`, intent `"clone_text_edit"` / `"clone_text_clear"`)
- Modify: `apps/frontend/src/features/chat-shell/components/web-inspector.tsx` — when a fragment (or its wrapper section) is selected, a "Cloned text edits" section listing overrides with a Clear button each (first consumer of the F3.2 fragment-card seam is NOT required here; the list is read from the document node)
- Tests: `apps/agent_runtime/tests/test_web_cloned_sections.py`, `apps/api/tests/test_web_operations_overrides.py`, `apps/frontend/.../webDocuments.test.ts` (op builder)

- [ ] **Step 1: Failing tests**

Python (`test_web_operations_overrides.py`): POST `/documents/{id}/web/operations` with a `set_fragment_text_override` whose path resolves → 200 and the node carries it; with a dead path → 422 `engine_code == "op.override_path_unresolved"`. Use the TestClient fixture the sibling `test_web_turns.py` uses.

Agent (`test_web_cloned_sections.py`): pin a clone, apply an override op through `tool.web_ops(...)`, then `inspect_cloned_section(fragment_id)` → JSON has `text_overrides[0].path == ":nth-child(1)"`.

Frontend (`webDocuments.test.ts` or a new `web-operations.test.ts`):
```ts
test("the override op builder spells the engine's wire shape", () => {
  assert.deepEqual(setFragmentTextOverrideOp("home", "frg_a", ":nth-child(1)", { text: "New", bold: true, italic: false, underline: false, size: 1 }),
    { kind: "set_fragment_text_override", page_id: "home", id: "frg_a", path: ":nth-child(1)", override: { text: "New", bold: true, italic: false, underline: false, size: 1 } });
  assert.deepEqual(setFragmentTextOverrideOp("home", "frg_a", ":nth-child(1)", null),
    { kind: "set_fragment_text_override", page_id: "home", id: "frg_a", path: ":nth-child(1)" });
});
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** all four surfaces as specified in Interfaces; the inspector section is a plain list (`InspectorField` rows: path label via `innerElementLabel(tag, slot)` when the path resolves client-side against `fragment_meta`… no — the client has no HTML; show `path` verbatim plus the override text, and the Clear button).

- [ ] **Step 4: Run** — Python suites, `npm test`, `npm run lint`, `npm run build` → green.

- [ ] **Step 5: Commit**
```bash
git add subsystems/clue-design/apps/api subsystems/clue-design/apps/agent_runtime apps/frontend/src/features/design-editor apps/frontend/src/features/chat-shell/components/web-inspector.tsx
git commit -m "feat: fragment text overrides flow through the API (path checked), the agent's inspect tool, and the inspector"
```

---

### Task 15: Double-click text inside a clone → constrained inline editor → override

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/web_bridge.py` (dblclick on a text-like element inside `[data-fragment-root]`; a minimal in-frame editor; `clone-text-commit` message)
- Modify: `apps/frontend/src/features/design-editor/engine/webBridge.ts` (inbound `clone-text-commit` / `clone-text-cancel`; outbound `edit-text` builder for the popover quick action)
- Modify: `apps/frontend/src/features/design-editor/hooks/use-web-bridge-selection.ts` (`onCloneTextCommit`)
- Modify: `apps/frontend/src/features/design-editor/hooks/use-web-editing-session.ts` (commit → `writes.setFragmentTextOverride`)
- Tests: `subsystems/clue-design/apps/api/tests/test_web_bridge_annotations.py` (script contains the protocol strings), `webBridge.test.ts` (validator)

**Interfaces:**
- Script → shell: `{type:"clone-text-commit", address:{nodeId,path,slot?,tag}, override:{text,bold,italic,underline,size}}`; `{type:"clone-text-cancel", address}`.
- Shell → script: `{type:"edit-text", nonce, address}` starts the same editor programmatically (used by the popover's Edit text quick action in Task 16).
- The in-frame editor: the element becomes `contenteditable="plaintext-only"` (fallback `contenteditable="true"` with paste-as-text), a tiny floating toolbar (`.lumen-clone-toolbar`) with B / I / U toggles and `A−` / `A+` size steppers (−3…+3, shown as a number), Enter or click-away commits, Escape cancels. Initial marks/size are read from an existing override for that path (the bridge receives `__LUMEN_TEXT_OVERRIDES__` = `{node_id: {path: override}}` at render, added to `render_bridge_script`).

- [ ] **Step 1: Failing tests** — extend `test_web_bridge_annotations.py`: the script contains `"clone-text-commit"`, `"edit-text"`, `lumen-clone-toolbar`, and `__LUMEN_TEXT_OVERRIDES__` is substituted with the node's overrides for the rendered page. Extend `webBridge.test.ts`: a `clone-text-commit` message validates into `{ type: "clone-text-commit", address, override }` with `size` clamped to −3…+3 and text capped at 8192 bytes; a malformed override → null.

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** — bridge: in the `dblclick` handler, when `closest("[data-node-id][data-tv]")` is null, take `event.target.closest("[data-fragment-root] *")`-style: `var el = event.target; var owner = ownerNode(el); if (owner && owner.hasAttribute("data-fragment-root") && TEXT_LIKE.test(el.tagName.toLowerCase())) beginCloneEditing(el);`. `beginCloneEditing` stores the original innerHTML, sets contenteditable, mounts the toolbar, and on commit posts the message and restores the original DOM (the shell's write triggers a re-render that shows the override). Frontend: validator + hook callback + session wiring to `writes.setFragmentTextOverride(pageId, address.nodeId, address.path, override)`.

- [ ] **Step 4: Run** — Python + frontend gates → green; restart stack; manual: double-click a card title inside the "why" band on the Ramp page, type, press B, Enter → the page re-renders with the bold new title; undo from the artifact menu restores it.

- [ ] **Step 5: Commit**
```bash
git add subsystems/clue-design/apps/api/lumen_api/web_bridge.py subsystems/clue-design/apps/api/tests/test_web_bridge_annotations.py apps/frontend/src/features/design-editor
git commit -m "feat: double-click text inside a clone opens a constrained inline editor (text, B/I/U, size) that writes a fragment text override (R-A1, R-A6)"
```

---

# Slice 4 — Quick action and polish

### Task 16: "Edit text" quick action, D-F3 comment updates, docs, live acceptance

**Files:**
- Modify: `apps/frontend/src/features/design-editor/components/web-annotation-popover.tsx` (Edit text → `postEditText(address)`), `web-artifact-canvas.tsx` (outbound `edit-text` via `webBridgeEditTextMessage(nonce, address)`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/web_bridge.py` (~L1235 D-F3 comment), `apps/frontend/src/features/design-editor/engine/webDocuments.ts` (~L1494 comment), `subsystems/clue-design/apps/api/lumen_api/fragments/… ` where D-F3 is quoted (grep `D-F3`), `apps/frontend/src/features/design-editor/model/fragment-card.ts` docblock
- Modify: `subsystems/clue-design/docs/` — the clone-fidelity ruling record that states D-F3 (grep `D-F3` under `subsystems/clue-design/docs`) gains the R-A6 amendment paragraph
- Modify: `_memory/2026-09-04-web-editor-annotations.md` (closing entry), root `CLAUDE.md` backlog bullet for the library-scoping ruling still pending (one line, cross-referencing the spec's §6)

- [ ] **Step 1: Failing test** — `webBridge.test.ts`: `webBridgeEditTextMessage("n", { nodeId: "frg_a", path: ":nth-child(1)", tag: "h2" })` deep-equals `{ channel: WEB_BRIDGE_CHANNEL, nonce: "n", type: "edit-text", address: {...} }`.

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** the builder and the popover wiring (the quick action dismisses the pending box, then posts `edit-text`; the bridge's `edit-text` handler from Task 15 starts the editor for a fragment element, or `beginEditing` for a `[data-tv]` node). Update every D-F3 comment to: "D-F3 (Option A) + R-A6 amendment (2026-09-04): a clone moves as a whole and exposes slot values AND per-element text overrides; nothing else inside it is editable."

- [ ] **Step 4: Gates** — frontend gate; `pytest apps/api/tests apps/agent_runtime/tests -q` in the design subsystem.

- [ ] **Step 5: Live acceptance (record in memory)**
  1. Layers panel on the Ramp page: every row is a human name.
  2. Hover the Visa image inside a clone: outline + `img`; hover a band: "Hero — …".
  3. Three annotations (one inside a clone), Add each, badges 1–3, send with empty composer → agent run confirms 1–3 by number; the inner one edited via a variant or rebind, nothing else touched.
  4. Single-click a clone headline → Edit text quick action → type, B, Enter → override rendered; inspector lists it; Clear removes it; undo/redo round-trip.
  5. Double-click does the same directly.
  6. Reload drops chips and badges (R-A3); the document keeps the override (it is an operation).

- [ ] **Step 6: Commit**
```bash
git add apps/frontend/src/features/design-editor subsystems/clue-design/apps/api/lumen_api/web_bridge.py subsystems/clue-design/docs _memory/2026-09-04-web-editor-annotations.md CLAUDE.md
git commit -m "feat(frontend): Edit text quick action in the comment box; D-F3 amendment recorded everywhere the ruling is quoted"
```

---

## Self-review against the spec

- §3.1 address grammar → Tasks 5, 6, 10 (bridge computes, validator checks, backend resolves). ✔
- §3.2 names, four consumers → Task 1 (layers, chip), Task 4/5 (agent line, hover), Task 3 (pin-time). ✔
- §3.3 bridge hover/annotate/edit-text/badges → Tasks 5, 15. ✔
- §3.4 popover, Add/Send, chips, badges, session-only → Tasks 6, 7. ✔
- §3.5 note on refs, leg wiring, prompt, inspect shows overrides → Tasks 7, 8, 9, 10, 11, 14. ✔
- §3.6 engine model, op, render, inline editor, inspector → Tasks 12, 13, 14, 15. ✔
- §3.7 gesture table → Tasks 5, 15, 16. ✔
- §4 error handling: stale address wording (Task 10), dead path refusal (Task 14), nonce re-post (Task 6), page-scoped badges (Task 6 `itemsForPage`), override wins over slot (Task 13). ✔
- §5 tests: each task carries its own; live acceptance in Tasks 11 and 16. ✔
- Type consistency: `WebElementAddress {nodeId, path?, slot?, tag}` is used identically in Tasks 5, 6, 7, 15, 16; `FragmentTextOverride {text,bold,italic,underline,size?}` in Tasks 12–15; wire kind `set_fragment_text_override` with field `override` in Tasks 12 and 14. ✔
