import assert from "node:assert/strict";
import { it } from "node:test";
import type {
  Node,
  NodePatch,
  Scene,
  TextAlign,
  VerticalAlign,
} from "../engine/scene/contracts";
import { nodePatch, set } from "../engine/scene/operations";
import {
  HARVESTED_AD_PAGE,
  adAutoLayout,
  adPlainText,
  adRect,
  adTokenText,
} from "./__fixtures__/scene-nodes";
import { COLOR_NONE } from "./scene-hydrate";
import { sceneChangeToOperation } from "./scene-apply";

/**
 * AD3.1: this file IS the ad-inspector mapping contract's §1.2 (text schema)
 * write table — one `it` per control row, each citing its row, plus the null
 * contract's refusals. The twin of the website lane's `apply.test.ts`.
 *
 * Every case runs against AD2.2's harvested bytes
 * (`__fixtures__/scene-nodes`, document `doc_ad22linkedinsquare00000000001`)
 * — never a hand-written node. Where the harvest cannot express a case, the
 * scene is CLONED and exactly one field is edited (the AD2.4/AD2.5
 * technique); each such clone says which field and why, and is marked
 * UNCOVERED-by-harvest. Three cases need it:
 *   • a fill-less / gradient-filled / multi-fill TEXT node (every harvested
 *     text carries exactly one solid-or-token fill),
 *   • a non-hug-height TEXT node (both harvested texts hug),
 *   • a PINNED node (`position_mode` appears nowhere in the harvest).
 */

const SCENE = HARVESTED_AD_PAGE;

function clone(scene: Scene): Scene {
  return JSON.parse(JSON.stringify(scene)) as Scene;
}

function apply(
  node: Node,
  property: string,
  value: unknown,
  scene: Scene = SCENE,
): ReturnType<typeof sceneChangeToOperation> {
  return sceneChangeToOperation(
    { property, selectionId: node.id, value },
    node,
    scene,
  );
}

/** The expected operation, built through the ENGINE's own patch builder: the
 * patch names the one field that is `set` and leaves every other field
 * `unchanged`, so a write that touches the wrong field fails loudly. */
function updateNode(nodeId: string, patch: Partial<NodePatch>) {
  return { kind: "update_node", node_id: nodeId, patch: nodePatch(patch) };
}

/** A clone of the harvested scene with ONE field of one node replaced, and
 * the cloned node itself — the adapter must be handed the node it will read
 * (`scene.nodes[id]`), not the pristine fixture. */
function withNodeField<Field extends keyof Node>(
  nodeId: string,
  field: Field,
  value: Node[Field],
): { node: Node; scene: Scene } {
  const scene = clone(SCENE);
  const node = scene.nodes[nodeId];
  assert.ok(node, `fixture node ${nodeId} missing`);
  node[field] = value;
  return { node, scene };
}

// ══ §1.2 row 1 — Color (text fill, §1.6 policy) ═════════════════════════════

it("§1.2 Color: a hex writes ONE solid fill and reuses the paint id the node already carries", () => {
  assert.deepEqual(
    apply(adPlainText(), "textColor", "#FF00AA"),
    updateNode("text_proof_stat", {
      fills: set([
        {
          id: "paint_stat",
          paint: { color: { kind: "hex", value: "#ff00aa" }, kind: "solid" },
        },
      ]),
    }),
  );
});

it("§1.6: a raw hex on a TOKEN-bound text detaches the brand binding — the ratified trade", () => {
  // `text_headline`'s fill is the real `$text.inverse` token paint. The write
  // replaces it with a literal; the user-facing "leaves your brand palette"
  // note is Gate G-B chrome that does not exist yet (§6 item 2).
  assert.deepEqual(
    apply(adTokenText(), "textColor", "#123ABC"),
    updateNode("text_headline", {
      fills: set([
        {
          id: "paint_headline",
          paint: { color: { kind: "hex", value: "#123abc" }, kind: "solid" },
        },
      ]),
    }),
  );
});

it("§1.2 Color: a text node with no fill mints the editor's own paint id", () => {
  // UNCOVERED by the harvest: every harvested text carries a fill. One field
  // edited (`fills` → []) so the minted-id branch runs against real bytes.
  const { node, scene } = withNodeField("text_proof_stat", "fills", []);
  assert.deepEqual(
    apply(node, "textColor", "#FF00AA", scene),
    updateNode("text_proof_stat", {
      fills: set([
        {
          id: "paint_text_proof_stat_fill",
          paint: { color: { kind: "hex", value: "#ff00aa" }, kind: "solid" },
        },
      ]),
    }),
  );
});

it("§1.2 Color: an 8-digit hex truncates to six digits (the ported normalization)", () => {
  const operation = apply(adPlainText(), "textColor", "#FF00AA80");
  assert.deepEqual(
    operation,
    updateNode("text_proof_stat", {
      fills: set([
        {
          id: "paint_stat",
          paint: { color: { kind: "hex", value: "#ff00aa" }, kind: "solid" },
        },
      ]),
    }),
  );
});

it("§1.2 Color: anything that is not a hex is refused rather than guessed black", () => {
  for (const value of ["", "  ", "#FFF", "rebeccapurple", "00F59B", COLOR_NONE]) {
    assert.equal(apply(adPlainText(), "textColor", value), null, value);
  }
  assert.equal(apply(adPlainText(), "textColor", 16711680), null);
});

it("§1.6 guard: a GRADIENT fill is not writable through the single swatch", () => {
  // One field edited (`fills`), and the gradient is the harvested one from
  // `rect_accent_bar` — a real 3-stop linear gradient, not an invented paint.
  const { node, scene } = withNodeField("text_proof_stat", "fills", [
    ...adRect().fills,
  ]);
  assert.equal(apply(node, "textColor", "#FF00AA", scene), null);
});

it("§1.6 guard: a MULTI-LAYER fill is not writable through the single swatch", () => {
  const { node, scene } = withNodeField("text_proof_stat", "fills", [
    ...adPlainText().fills,
    ...adTokenText().fills,
  ]);
  assert.equal(apply(node, "textColor", "#FF00AA", scene), null);
});

it("§1.2 Color: a NON-text node is refused — hydrate routes its fill to backgroundColor", () => {
  assert.equal(apply(adRect(), "textColor", "#FF00AA"), null);
  assert.equal(apply(adAutoLayout(), "textColor", "#FF00AA"), null);
});

// ══ §1.2 row 2 — Font family ════════════════════════════════════════════════

it("§1.2 Font: a family writes only the text kind's font_family", () => {
  assert.deepEqual(
    apply(adPlainText(), "fontFamily", "Inter Tight"),
    updateNode("text_proof_stat", {
      kind: set({ ...adPlainText().kind, font_family: "Inter Tight" }),
    }),
  );
});

it("§1.2 Font: an empty family is refused", () => {
  assert.equal(apply(adPlainText(), "fontFamily", ""), null);
  assert.equal(apply(adPlainText(), "fontFamily", "   "), null);
});

// ══ §1.2 row 3 — Size (free number ≥ 1, §2 delta row 2) ═════════════════════

it("§1.2 Size: a free number ≥ 1 writes font_size", () => {
  assert.deepEqual(
    apply(adPlainText(), "fontSize", "48"),
    updateNode("text_proof_stat", {
      kind: set({ ...adPlainText().kind, font_size: 48 }),
    }),
  );
  const fractional = apply(adPlainText(), "fontSize", "18.5");
  assert.ok(fractional && fractional.kind === "update_node");
  assert.deepEqual(fractional.patch.kind, {
    kind: "set",
    value: { ...adPlainText().kind, font_size: 18.5 },
  });
});

it("§1.2 Size: below 1, unparseable, and an empty field are refused", () => {
  // The ad inspector's size box is a free-text `InspectorInput` firing per
  // KEYSTROKE, so "", "-" and "1e" are real intermediate events.
  for (const value of ["0", "0.5", "-12", "abc", "", "  ", "-", "1e", "1e400"]) {
    assert.equal(apply(adPlainText(), "fontSize", value), null, value);
  }
  assert.equal(apply(adPlainText(), "fontSize", Number.NaN), null);
  assert.equal(apply(adPlainText(), "fontSize", 48), null);
});

// ══ §1.2 row 4 — Weight (the nine named labels, §2 delta row 2) ═════════════

it("§1.2 Weight: each of the nine named labels inverts to its numeric weight", () => {
  const ramp: [string, number][] = [
    ["100 Thin", 100],
    ["200 Extra Light", 200],
    ["300 Light", 300],
    ["400 Regular", 400],
    ["500 Medium", 500],
    ["600 Semi Bold", 600],
    ["700 Bold", 700],
    ["800 Extra Bold", 800],
    ["900 Black", 900],
  ];
  for (const [label, weight] of ramp) {
    assert.deepEqual(
      apply(adPlainText(), "fontWeight", label),
      updateNode("text_proof_stat", {
        kind: set({ ...adPlainText().kind, font_weight: weight }),
      }),
      label,
    );
  }
});

it("§1.2 Weight: a label outside the ramp is refused — the WEB lane's vocabulary included", () => {
  for (const value of ["Semi Bold", "Bold", "600", "650 Custom", ""]) {
    assert.equal(apply(adPlainText(), "fontWeight", value), null, value);
  }
});

// ══ §1.2 row 5 — H-alignment (4 toggles, §2 delta row 2) ════════════════════

it("§1.2 H-alignment: left/center/right/justify pass straight through to TextAlign", () => {
  const aligns: TextAlign[] = ["left", "center", "right", "justify"];
  for (const align of aligns) {
    assert.deepEqual(
      apply(adPlainText(), "horizontalAlignment", align),
      updateNode("text_proof_stat", {
        kind: set({ ...adPlainText().kind, align }),
      }),
      align,
    );
  }
});

it("§1.2 H-alignment: a value outside the four toggles is refused", () => {
  for (const value of ["start", "middle", "END", ""]) {
    assert.equal(apply(adPlainText(), "horizontalAlignment", value), null, value);
  }
});

// ══ §1.2 row 6 — V-alignment (dummy labels → engine VerticalAlign) ══════════

/** UNCOVERED by the harvest: BOTH harvested text nodes hug their height, and
 * the V-alignment control is disabled in exactly that case (hydrate's
 * `valignDisabled`). One field edited (`size`) — the fixed height is the
 * node's own `group_proof` slot height (104), not an invented number. */
function fixedHeightText(): { node: Node; scene: Scene } {
  return withNodeField("text_proof_stat", "size", {
    height: { kind: "fixed", value: 104 },
    width: { kind: "fixed", value: 256 },
  });
}

it("§1.2 V-alignment: the dummy's top/middle/bottom map onto the engine's top/center/bottom", () => {
  const { node, scene } = fixedHeightText();
  const pairs: [string, VerticalAlign][] = [
    ["top", "top"],
    ["middle", "center"],
    ["bottom", "bottom"],
  ];
  for (const [label, valign] of pairs) {
    assert.deepEqual(
      apply(node, "verticalAlignment", label, scene),
      updateNode("text_proof_stat", {
        kind: set({ ...node.kind, valign }),
      }),
      label,
    );
  }
});

it("§1.2 V-alignment: a HUG-height node is refused — hydrate disables that control", () => {
  assert.equal(apply(adPlainText(), "verticalAlignment", "middle"), null);
  assert.equal(apply(adTokenText(), "verticalAlignment", "bottom"), null);
});

it("§1.2 V-alignment: the ENGINE's own word is not the dummy's vocabulary and is refused", () => {
  const { node, scene } = fixedHeightText();
  assert.equal(apply(node, "verticalAlignment", "center", scene), null);
  assert.equal(apply(node, "verticalAlignment", "baseline", scene), null);
});

// ══ §1.2 row 7 — Stroke colour + width (width 0 clears) ═════════════════════

it("§1.2 Stroke colour: a hex keeps the node's existing width and paint id", () => {
  // `auto_row_copy` carries the harvest's real stroke (`stroke_card`, 2px).
  // The stroke rows are kind-agnostic because hydrate's stroke mapping is one
  // path for every kind (scene-hydrate.ts:390-401).
  assert.deepEqual(
    apply(adAutoLayout(), "strokeColor", "#00FF00"),
    updateNode("auto_row_copy", {
      strokes: set([
        {
          id: "stroke_card",
          paint: { color: { kind: "hex", value: "#00ff00" }, kind: "solid" },
          width: 2,
          width_token: null,
        },
      ]),
    }),
  );
});

it("§1.2 Stroke colour: the `none` sentinel clears the strokes", () => {
  assert.deepEqual(
    apply(adAutoLayout(), "strokeColor", COLOR_NONE),
    updateNode("auto_row_copy", { strokes: set([]) }),
  );
});

it("§1.2 Stroke colour: on a STROKELESS node the resulting width is 0, which clears", () => {
  assert.deepEqual(
    apply(adPlainText(), "strokeColor", "#FF0000"),
    updateNode("text_proof_stat", { strokes: set([]) }),
  );
});

it("§1.2 Stroke colour: a non-hex, non-`none` value is refused", () => {
  for (const value of ["rgb(0,0,0)", "#FFF", "$brand.line", ""]) {
    assert.equal(apply(adAutoLayout(), "strokeColor", value), null, value);
  }
});

it("§1.2 Stroke width: a positive width keeps the node's existing paint verbatim", () => {
  assert.deepEqual(
    apply(adAutoLayout(), "strokeWidth", "6"),
    updateNode("auto_row_copy", {
      strokes: set([
        {
          id: "stroke_card",
          // The stored paint, byte-identical — a width edit is not a colour
          // edit, so it detaches nothing (§1.6 binds raw COLOUR writes).
          paint: { color: { kind: "hex", value: "#2E2470" }, kind: "solid" },
          width: 6,
          width_token: null,
        },
      ]),
    }),
  );
});

it("§1.2 Stroke width: exactly 0 clears the stroke", () => {
  assert.deepEqual(
    apply(adAutoLayout(), "strokeWidth", "0"),
    updateNode("auto_row_copy", { strokes: set([]) }),
  );
});

it("§1.2 Stroke width: a negative, unparseable or empty width is refused", () => {
  for (const value of ["-2", "abc", "", "  ", "-"]) {
    assert.equal(apply(adAutoLayout(), "strokeWidth", value), null, value);
  }
});

it("§1.2 Stroke width: a STROKELESS node is refused — the colour would have to be invented", () => {
  assert.equal(apply(adPlainText(), "strokeWidth", "4"), null);
});

// ══ §1.2 row 8 — Position X/Y (transform; pinned → absolute_box) ════════════

it("§1.2 Position: an unpinned, unmanaged node writes its transform", () => {
  // `text_proof_stat`'s parent is `group_proof` (a GROUP, not an auto-layout),
  // so the node is not solver-managed and owns its own geometry.
  assert.deepEqual(
    apply(adPlainText(), "position.x", "180"),
    updateNode("text_proof_stat", {
      transform: set({ ...adPlainText().transform, x: 180 }),
    }),
  );
  assert.deepEqual(
    apply(adPlainText(), "position.y", "-24"),
    updateNode("text_proof_stat", {
      transform: set({ ...adPlainText().transform, y: -24 }),
    }),
  );
});

it("§1.2 Position: a LAYOUT-MANAGED node is refused (the solver owns its geometry)", () => {
  // `text_headline` is a child of the `auto_row_copy` auto-layout.
  assert.equal(apply(adTokenText(), "position.x", "10"), null);
  assert.equal(apply(adTokenText(), "position.y", "10"), null);
});

it("§1.2 Position: an unparseable or empty value is refused", () => {
  for (const value of ["abc", "", "  ", "-", "1e400"]) {
    assert.equal(apply(adPlainText(), "position.x", value), null, value);
  }
  assert.equal(apply(adPlainText(), "position.x", 180), null);
});

/** UNCOVERED by the harvest: `position_mode` appears nowhere in it, so no
 * harvested node is pinned. TWO fields are edited here, not one, because a
 * pin and its page-space box are jointly required to express the state (a
 * `position_mode` alone is the boxless-pin case, tested separately below);
 * the box is the node's own real geometry (transform 72,368 + size 320x10),
 * not an invented rectangle. */
function pinnedRect(): { node: Node; scene: Scene } {
  const scene = clone(SCENE);
  const node = scene.nodes.rect_accent_bar;
  node.position_mode = "absolute";
  node.absolute_box = { height: 10, width: 320, x: 72, y: 368 };
  return { node, scene };
}

it("§1.2 Position: a PINNED node writes its absolute_box, not its transform", () => {
  const { node, scene } = pinnedRect();
  assert.deepEqual(
    apply(node, "position.x", "180", scene),
    updateNode("rect_accent_bar", {
      // Width/height are unchanged, so the engine builder bakes no size.
      absolute_box: set({ height: 10, width: 320, x: 180, y: 368 }),
    }),
  );
  assert.deepEqual(
    apply(node, "position.y", "400", scene),
    updateNode("rect_accent_bar", {
      absolute_box: set({ height: 10, width: 320, x: 72, y: 400 }),
    }),
  );
});

it("§1.2 Position: a PINNED node with no resolvable box is refused", () => {
  // Exactly one field edited. `computed` is null on every harvested node, so
  // this pin has no box at all — nothing truthful to patch.
  const { node, scene } = withNodeField(
    "rect_accent_bar",
    "position_mode",
    "absolute",
  );
  assert.equal(apply(node, "position.x", "180", scene), null);
});

// ══ §1.2 row 8 — Rotation (transform, pass-through) ═════════════════════════

it("§1.2 Rotation: the number passes through raw — no degree/radian conversion", () => {
  assert.deepEqual(
    apply(adPlainText(), "rotation", "45"),
    updateNode("text_proof_stat", {
      transform: set({ ...adPlainText().transform, rotation: 45 }),
    }),
  );
});

it("§1.2 Rotation: a PINNED node rotates on its TRANSFORM (the box is position/size only)", () => {
  const { node, scene } = pinnedRect();
  assert.deepEqual(
    apply(node, "rotation", "45", scene),
    updateNode("rect_accent_bar", {
      transform: set({ ...node.transform, rotation: 45 }),
    }),
  );
});

it("§1.2 Rotation: a layout-managed node and an unparseable value are refused", () => {
  assert.equal(apply(adTokenText(), "rotation", "45"), null);
  assert.equal(apply(adPlainText(), "rotation", "abc"), null);
  assert.equal(apply(adPlainText(), "rotation", ""), null);
});

// ══ §1.0 header — Lock (and the lock gate over every other row) ═════════════

it("§1.0 Lock: a boolean writes Node.locked", () => {
  assert.deepEqual(
    apply(adPlainText(), "locked", true),
    updateNode("text_proof_stat", { locked: set(true) }),
  );
});

it("§1.0 Lock: a non-boolean lock value is refused", () => {
  assert.equal(apply(adPlainText(), "locked", "true"), null);
  assert.equal(apply(adPlainText(), "locked", 1), null);
});

it("§1.0 Lock: a locked node refuses every row — except the unlock that frees it", () => {
  const { node, scene } = withNodeField("text_proof_stat", "locked", true);
  const rows: [string, unknown][] = [
    ["textColor", "#FF00AA"],
    ["fontFamily", "Inter Tight"],
    ["fontSize", "48"],
    ["fontWeight", "700 Bold"],
    ["horizontalAlignment", "center"],
    ["verticalAlignment", "middle"],
    ["strokeColor", "#00FF00"],
    ["strokeWidth", "4"],
    ["position.x", "180"],
    ["position.y", "180"],
    ["rotation", "45"],
  ];
  for (const [property, value] of rows) {
    assert.equal(apply(node, property, value, scene), null, property);
  }
  assert.deepEqual(
    apply(node, "locked", false, scene),
    updateNode("text_proof_stat", { locked: set(false) }),
  );
});

// ══ The null contract's catch-all ═══════════════════════════════════════════

it("null contract: an unknown property writes nothing", () => {
  assert.equal(apply(adPlainText(), "notAProperty", "x"), null);
  assert.equal(apply(adPlainText(), "buttonLabel", "Primary"), null);
});

it("null contract: rows owned by a LATER lane write nothing today", () => {
  // AD3.1 is the §1.2 text schema only. When the Layout/Shape/Auto-Layout
  // lanes extend this same switch they move these lines out of this test.
  for (const property of ["opacity", "radius.all", "gap", "fillMode", "sizePreset"]) {
    assert.equal(apply(adAutoLayout(), property, "4"), null, property);
  }
});

it("null contract: a non-text node never reaches updateTextNode (which throws)", () => {
  for (const property of [
    "fontFamily",
    "fontSize",
    "fontWeight",
    "horizontalAlignment",
    "verticalAlignment",
  ]) {
    assert.equal(apply(adRect(), property, "left"), null, property);
    assert.equal(apply(adAutoLayout(), property, "16"), null, property);
  }
});
