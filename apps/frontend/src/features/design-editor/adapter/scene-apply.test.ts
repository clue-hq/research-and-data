import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { it } from "node:test";
import { fileURLToPath } from "node:url";
import type { InspectorBackgroundFill } from "@/features/chat-shell/hooks/use-inspector-controller";
import type {
  AssetPlacement,
  AssetRecord,
  Node,
  NodePatch,
  PageId,
  PagePatch,
  PageSize,
  Scene,
  TextAlign,
  TextNode,
  VerticalAlign,
} from "../engine/scene/contracts";
import {
  nodePatch,
  pagePatch,
  set,
  updateNodeLayout,
} from "../engine/scene/operations";
import { normalizePageSize } from "../engine/scene/pageGeometry";
import { setKitTokenMaps, setTokenColorMap } from "../engine/scene/renderAdapter";
import type { KitTokenMaps } from "../engine/scene/tokenColors";
import { adBrandKit } from "./__fixtures__/brand-kit-colors";
import {
  AD_PAGE_ID,
  HARVESTED_AD_PAGE,
  adAutoLayout,
  adEllipse,
  adFrame,
  adGroup,
  adImage,
  adPlainText,
  adRect,
  adTokenText,
} from "./__fixtures__/scene-nodes";
import { buildScenePalette, type ScenePalette } from "./scene-palette";
import {
  COLOR_NONE,
  backgroundFillCommits,
  hydrateSceneCanvasState,
  hydrateSceneInspectorState,
  radiusCommitText,
} from "./scene-hydrate";
import {
  sceneCanvasChangeToOperation,
  sceneChangeToOperation,
  sceneImagePlacementOperations,
  sceneImageReplacementTarget,
} from "./scene-apply";

/**
 * AD3.1: this file IS the ad-inspector mapping contract's §1.2 (text schema)
 * write table — one `it` per control row, each citing its row, plus the null
 * contract's refusals. The twin of the website lane's `apply.test.ts`.
 *
 * AD4.0 step 1 adds §1.1's SIZE rows at the foot of the file. They exercise the
 * second exported function (`sceneCanvasChangeToOperation`), because those rows
 * target the PAGE and the canvas selection carries no node at all. Step 2 adds
 * §1.1's BACKGROUND rows after them — the same function, but landing on the
 * page's ROOT FRAME (the founder ruling), so they assert `update_node`.
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

for (const missing of ["pending", "role", "size", "leading", "tracking", "family-alias",
  "wrapped-family-alias", "raw-family-alias", "wrapped-raw-family-alias", "constructor", "__proto__"] as const) {
  it(`refuses typography edits with ${missing} brand values without disabling content edits`, () => {
    const scene = structuredClone(SCENE);
    const node = scene.nodes.text_headline;
    if (node.kind.kind !== "text") throw new Error("expected text");
    node.kind = { ...node.kind, font_family: "Inter", font_size: 16, font_weight: 400,
      style_token: "$type.headline", font_size_token: "$type.size",
      line_height_token: "$type.leading", letter_spacing_token: "$type.tracking" };
    const canvasMaps: KitTokenMaps = { colors: {}, typography: {
      "type.headline": { fontFamily: "Season Mix", fontSize: 80, fontWeight: 500 },
    }, numbers: { "type.size": 67.5, "type.leading": 1.12, "type.tracking": -0.6 } };
    const maps = structuredClone(canvasMaps);
    if (missing === "role") delete maps.typography["type.headline"];
    if (missing === "size") delete maps.numbers["type.size"];
    if (missing === "leading") delete maps.numbers["type.leading"];
    if (missing === "tracking") delete maps.numbers["type.tracking"];
    if (missing === "family-alias") maps.typography["type.headline"].fontFamily = "$font.brand";
    if (missing === "wrapped-family-alias") maps.typography["type.headline"].fontFamily = " token(font.brand) ";
    if (missing === "constructor" || missing === "__proto__") node.kind.style_token = missing;
    if (missing === "raw-family-alias" || missing === "wrapped-raw-family-alias") {
      node.kind = { ...node.kind, style_token: null, font_size_token: null,
        line_height_token: null, letter_spacing_token: null,
        font_family: missing === "raw-family-alias" ? "$type.headline" : " token(type.headline) " };
    }
    setKitTokenMaps(canvasMaps);
    const before = JSON.stringify(scene);
    try {
      for (const [property, value] of [["fontSize", "72"], ["fontFamily", "Mona Sans"], ["fontWeight", "700 Bold"]]) {
        assert.equal(sceneChangeToOperation({ property, value, selectionId: node.id }, node, scene, null,
          missing === "pending" ? null : maps), null);
      }
      assert.notEqual(sceneChangeToOperation({ property: "content", value: "Revised headline", selectionId: node.id },
        node, scene, null, null), null);
      assert.equal(JSON.stringify(scene), before);
    } finally {
      setTokenColorMap({});
    }
  });
}
/** The page's root frame — the node §1.1's Background rows write. */
const AD_ROOT_FRAME_ID = "frame_ad_root";

function clone(scene: Scene): Scene {
  return JSON.parse(JSON.stringify(scene)) as Scene;
}

function apply(
  node: Node,
  property: string,
  value: unknown,
  scene: Scene = SCENE,
  palette: ScenePalette | null = null,
): ReturnType<typeof sceneChangeToOperation> {
  return sceneChangeToOperation(
    { property, selectionId: node.id, value },
    node,
    scene,
    palette,
  );
}

/** AD4.0 step 3: the document's REAL brand vocabulary — built from the kit the
 * seeded ad is bound to (`__fixtures__/brand-kit-colors`). Passed only by the
 * §1.6 token rows; every other row is handed `null`, which is also the state a
 * document with no attached kit is in. */
const AD_PALETTE = buildScenePalette(adBrandKit());

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
  for (const value of ["", "  ", "#FFF", "rebeccapurple", "123456", COLOR_NONE]) {
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

// ══ Rung A — Text content (the Typography section's first row) ══════════════

it("rung A Text: a string writes only the text kind's content", () => {
  assert.deepEqual(
    apply(adPlainText(), "content", "4.1x faster triage"),
    updateNode("text_proof_stat", {
      kind: set({ ...adPlainText().kind, content: "4.1x faster triage" }),
    }),
  );
  // Multiline is the whole point of the textarea: the newline rides through
  // verbatim, it is not a commit terminator here.
  assert.deepEqual(
    apply(adPlainText(), "content", "3.4x\nfaster triage"),
    updateNode("text_proof_stat", {
      kind: set({ ...adPlainText().kind, content: "3.4x\nfaster triage" }),
    }),
  );
});

it("rung A Text: an EMPTY string is a legal commit — clearing text is a real edit", () => {
  // Unlike `fontFamily`, which refuses "" (an unnamed family is not a family),
  // an emptied text node is a node that says nothing, and it survives.
  assert.deepEqual(
    apply(adPlainText(), "content", ""),
    updateNode("text_proof_stat", {
      kind: set({ ...adPlainText().kind, content: "" }),
    }),
  );
});

it("rung A Text: a non-string value is refused rather than coerced", () => {
  assert.equal(apply(adPlainText(), "content", 34), null);
  assert.equal(apply(adPlainText(), "content", true), null);
  assert.equal(apply(adPlainText(), "content", null), null);
});

it("rung A Text: a NON-text node is refused (updateTextNode throws on one)", () => {
  assert.equal(apply(adRect(), "content", "hello"), null);
  assert.equal(apply(adAutoLayout(), "content", "hello"), null);
  assert.equal(apply(adImage(), "content", "hello"), null);
});

it("rung A Text: a LOCKED text node refuses the content row like every other", () => {
  const { node, scene } = withNodeField("text_proof_stat", "locked", true);
  assert.equal(apply(node, "content", "4.1x faster triage", scene), null);
  assert.equal(apply(node, "content", "", scene), null);
});

/* Rung C upgrade (founder-visible item 6): before rung C an inspector content
 * edit let the engine's D4 rule clear every span on the node. It now remaps
 * them with the same conservative prefix/suffix diff the caret session's
 * untracked path uses — styling inside the unchanged prefix and suffix
 * survives, styling over the changed middle is trimmed or dropped. */

/** The harvested stat with `faster` bolded — the same span the session tests
 * use, so both surfaces are proven over one document shape. */
function adSpannedText(): { node: Node; scene: Scene } {
  const scene = clone(SCENE);
  const node = scene.nodes.text_proof_stat;
  (node.kind as TextNode).spans = [{ start: 5, end: 11, font_weight: 700 }];
  return { node, scene };
}

it("rung C Text: an edit AFTER every span keeps the styling, re-authored so D4 cannot clear it", () => {
  const { node, scene } = adSpannedText();
  // The maintained vector is byte-identical here (the edit is past the last
  // span), which the engine reads as a stale carry-forward and clears. The
  // commit therefore re-authors it as the same styling in a different shape.
  assert.deepEqual(
    apply(node, "content", "3.4x faster triage!", scene),
    updateNode("text_proof_stat", {
      kind: set({
        ...node.kind,
        content: "3.4x faster triage!",
        spans: [
          { start: 5, end: 6, font_weight: 700 },
          { start: 6, end: 11, font_weight: 700 },
        ],
      }),
    }),
  );
});

it("rung C Text: an edit BEFORE a span carries the span with the text it styles", () => {
  const { node, scene } = adSpannedText();
  assert.deepEqual(
    apply(node, "content", "Up to 3.4x faster triage", scene),
    updateNode("text_proof_stat", {
      kind: set({
        ...node.kind,
        content: "Up to 3.4x faster triage",
        spans: [{ start: 11, end: 17, font_weight: 700 }],
      }),
    }),
  );
});

it("rung C Text: an edit THROUGH a styled run trims it to what is still attributable", () => {
  const { node, scene } = adSpannedText();
  assert.deepEqual(
    apply(node, "content", "3.4x fXr triage", scene),
    updateNode("text_proof_stat", {
      kind: set({
        ...node.kind,
        content: "3.4x fXr triage",
        spans: [
          { start: 5, end: 6, font_weight: 700 },
          { start: 7, end: 8, font_weight: 700 },
        ],
      }),
    }),
  );
});

it("rung C Text: clearing the text drops the spans it can no longer index", () => {
  const { node, scene } = adSpannedText();
  assert.deepEqual(
    apply(node, "content", "", scene),
    updateNode("text_proof_stat", {
      kind: set({ ...node.kind, content: "", spans: [] }),
    }),
  );
});

it("rung C Text: a SECOND edit on an already-split node does not regenerate the split", () => {
  // F1 (review 2026-08-24, P1). The inspector reaches the same D4 collision the
  // caret session does: `text_proof_stat` here holds what a previous suffix edit
  // wrote — one bold run stored as two adjacent same-style spans. Remapping a
  // fresh suffix edit normalizes them back together, and the pre-F1 guard
  // compared that against the NORMALIZED stored vector, matched, and re-split it
  // into exactly the bytes the document already held — so the engine cleared the
  // styling. Compared RAW (what the engine compares), the merge already differs.
  const scene = clone(SCENE);
  const node = scene.nodes.text_proof_stat;
  (node.kind as TextNode).spans = [
    { start: 5, end: 6, font_weight: 700 },
    { start: 6, end: 11, font_weight: 700 },
  ];
  const operation = apply(node, "content", "3.4x faster triage!!", scene);
  assert.deepEqual(
    operation,
    updateNode("text_proof_stat", {
      kind: set({
        ...node.kind,
        content: "3.4x faster triage!!",
        spans: [{ start: 5, end: 11, font_weight: 700 }],
      }),
    }),
  );
});

it("rung C Text: an UNSPLITTABLE span restates a no-op channel rather than dying", () => {
  // F2 (review 2026-08-24, P3-1): a one-character styled run — the coloured "!"
  // — has no interior boundary to split, so before F2 it went out byte-identical
  // and the engine cleared it. `text_proof_stat`'s node states no underline, so
  // `underline: false` is its own base: identical pixels, different bytes.
  const scene = clone(SCENE);
  const node = scene.nodes.text_proof_stat;
  (node.kind as TextNode).spans = [{ start: 17, end: 18, font_weight: 700 }];
  assert.deepEqual(
    apply(node, "content", "3.4x faster triage!", scene),
    updateNode("text_proof_stat", {
      kind: set({
        ...node.kind,
        content: "3.4x faster triage!",
        spans: [{ start: 17, end: 18, font_weight: 700, underline: false }],
      }),
    }),
  );
});

it("rung C Text: a node with NO spans still writes the content channel alone", () => {
  // Unchanged from rung A: nothing to remap, so nothing about the write moves.
  assert.deepEqual(
    apply(adPlainText(), "content", "4.1x faster triage"),
    updateNode("text_proof_stat", {
      kind: set({ ...adPlainText().kind, content: "4.1x faster triage" }),
    }),
  );
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

it("A9: a colour on a STROKELESS node MINTS a stroke at upstream's default width", () => {
  // Ruling A9 (standing) replaces AD3.1's refusal. AD3.1 read a strokeless
  // node's width as the 0 the panel displays and cleared, which left §1.2's
  // ratified Stroke row permanently dead on exactly the kinds where strokes
  // are common. §1.5's "editor semantics govern everywhere" makes upstream's
  // own default the lift: `RawStyleSection.tsx:38` commits
  // `solidStroke(node, hex, node.strokes[0]?.width ?? 1)`.
  assert.deepEqual(
    apply(adPlainText(), "strokeColor", "#FF0000"),
    updateNode("text_proof_stat", {
      strokes: set([
        {
          id: "paint_text_proof_stat_stroke",
          paint: { color: { kind: "hex", value: "#ff0000" }, kind: "solid" },
          width: 1,
          width_token: null,
        },
      ]),
    }),
  );
});

it("A9: a stored ZERO-width stroke still clears — the panel says the node has none", () => {
  // The minting rule is about a node with NO stroke. A stored zero-width one
  // is a stroke the width field truthfully shows as 0, and a zero-width stroke
  // is not a stroke, so this keeps AD3.1's clear.
  const { node, scene } = withNodeField("auto_row_copy", "strokes", [
    { ...adAutoLayout().strokes[0], width: 0 },
  ]);
  assert.deepEqual(
    apply(node, "strokeColor", "#FF0000", scene),
    updateNode("auto_row_copy", { strokes: set([]) }),
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

it("A9: a width on a COLOURLESS node mints upstream's own default stroke colour", () => {
  // The other direction of the same ruling. AD3.1 refused rather than "mint
  // upstream's hardcoded teal"; A9 rules that adopting the constant IS the
  // lift and refusing is the divergence. `RawStyleSection.tsx:52` commits
  // `solidStroke(node, hexInputValueFromStroke(node), value)`, whose
  // no-stroke return is `#256c70` (`:185-191`).
  assert.deepEqual(
    apply(adPlainText(), "strokeWidth", "4"),
    updateNode("text_proof_stat", {
      strokes: set([
        {
          id: "paint_text_proof_stat_stroke",
          paint: { color: { kind: "hex", value: "#256c70" }, kind: "solid" },
          width: 4,
          width_token: null,
        },
      ]),
    }),
  );
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

it("§1.2 Position: a PINNED node with no resolvable box writes its transform", () => {
  // Exactly one field edited. `computed` is null on every harvested node, so
  // this pin has no box at all — and the inspector is SHOWING `transform.x`
  // for it (`scene-hydrate.ts:350-356` falls back to the transform), so the
  // write must land there too. Upstream agrees: `ObjectSection.tsx`'s
  // `emitPosition` falls through to `emitTransform` in exactly this state.
  const { node, scene } = withNodeField(
    "rect_accent_bar",
    "position_mode",
    "absolute",
  );
  assert.deepEqual(
    apply(node, "position.x", "180", scene),
    updateNode("rect_accent_bar", {
      transform: set({ ...adRect().transform, x: 180 }),
    }),
  );
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

// ══ §1.4 Layout — Dimensions W/H (AD4.B step 1) ═════════════════════════════
//
// Semantics VERIFIED against the MVP editor's own W/H write
// (`subsystems/clue-design/apps/editor/src/components/inspector/ObjectSection.tsx`
// `emitExtent`): a pinned node's page-space box takes the number, and every
// other node has that ONE axis rewritten to a Fixed dimension — so a W/H typed
// on a hug or fill axis FLIPS it to fixed rather than being refused. The ad
// panel's "Width fixed"/"Height fixed" inputs commit this same property (the
// MVP's `SizingSection` writes the identical `{kind:"fixed"}` there), so there
// is one write path, not two.

it("§1.4 Dimensions: W rewrites that axis to a fixed size and leaves the other axis alone", () => {
  assert.deepEqual(
    apply(adRect(), "width", "400"),
    updateNode("rect_accent_bar", {
      size: set({
        height: { kind: "fixed", value: 10 },
        width: { kind: "fixed", value: 400 },
      }),
    }),
  );
  assert.deepEqual(
    apply(adRect(), "height", "24"),
    updateNode("rect_accent_bar", {
      size: set({
        height: { kind: "fixed", value: 24 },
        width: { kind: "fixed", value: 320 },
      }),
    }),
  );
});

it("§1.4 Dimensions: a HUG axis flips to fixed — the MVP's `emitExtent`, not a refusal", () => {
  // `auto_row_copy` is width-fixed 1056, height HUG.
  assert.deepEqual(
    apply(adAutoLayout(), "height", "160"),
    updateNode("auto_row_copy", {
      size: set({
        height: { kind: "fixed", value: 160 },
        width: { kind: "fixed", value: 1056 },
      }),
    }),
  );
});

it("§1.4 Dimensions: a PINNED node's W/H ride the absolute box (which bakes the fixed size)", () => {
  const { node, scene } = pinnedRect();
  assert.deepEqual(
    apply(node, "width", "400", scene),
    updateNode("rect_accent_bar", {
      // The engine builder bakes the box's size as Fixed on any RESIZE
      // (`operations.ts::updateNodeAbsoluteBox`) — the size-spec ↔ box
      // invariant, and upstream's identical behaviour.
      absolute_box: set({ height: 10, width: 400, x: 72, y: 368 }),
      size: set({
        height: { kind: "fixed", value: 10 },
        width: { kind: "fixed", value: 400 },
      }),
    }),
  );
});

it("§1.4 Dimensions: a size below 1, an unparseable one and an empty box are refused", () => {
  // The MVP's fixed-size fields are `min={1}`; the ad's are free text, so the
  // same floor is a refusal here rather than a browser-enforced minimum — the
  // §1.2 font-size row's rule exactly.
  for (const value of ["0", "0.5", "-4", "abc", "", "  ", "1e400"]) {
    assert.equal(apply(adRect(), "width", value), null, `width ${value}`);
    assert.equal(apply(adRect(), "height", value), null, `height ${value}`);
  }
  assert.equal(apply(adRect(), "width", 400), null, "a non-string is not a size");
});

// ══ §1.4 Layout — Opacity (OQ-3: shown as %, written 0–1) ═══════════════════

it("§1.4/OQ-3 Opacity: the typed percent is written as the engine's 0–1", () => {
  assert.deepEqual(
    apply(adRect(), "opacity", "50"),
    updateNode("rect_accent_bar", { opacity: set(0.5) }),
  );
  assert.deepEqual(
    apply(adRect(), "opacity", "0"),
    updateNode("rect_accent_bar", { opacity: set(0) }),
  );
});

it("§1.4/OQ-3 Opacity: a percent outside 0–100 is CLAMPED, at both ends", () => {
  // The one row on this lane that folds rather than refuses: the engine's
  // opacity is a bounded ratio (unlike a radius or a size, where an out-of-range
  // number names no intent), so the honest answer to "150%" is full opacity.
  assert.deepEqual(
    apply(adRect(), "opacity", "150"),
    updateNode("rect_accent_bar", { opacity: set(1) }),
  );
  assert.deepEqual(
    apply(adRect(), "opacity", "-5"),
    updateNode("rect_accent_bar", { opacity: set(0) }),
  );
});

it("§1.4/OQ-3 Opacity: text that names no number is refused, never folded to 0", () => {
  for (const value of ["abc", "", "  ", "-", "1e400"]) {
    assert.equal(apply(adRect(), "opacity", value), null, value);
  }
  assert.equal(apply(adRect(), "opacity", 50), null);
});

// ══ §1.4 Layout — Width/Height mode (OQ-2: Fixed | Hug | Fill) ══════════════

it("§1.4/OQ-2 Mode: Hug writes a bare `{kind:'hug'}` — the wire format carries NO value key", () => {
  const operation = apply(adImage(), "widthMode", "Hug");
  assert.deepEqual(
    operation,
    updateNode("image_hero", {
      size: set({
        height: { kind: "fixed", value: 676 },
        width: { kind: "hug" },
      }),
    }),
  );
  // Stated a second time, structurally: `Dimension`'s hug arm has no `value`
  // member at all (`contracts.ts`), and an extra one would be a shape the Rust
  // core does not accept.
  assert.ok(operation && operation.kind === "update_node");
  const size = operation.patch.size;
  assert.ok(size.kind === "set");
  assert.deepEqual(Object.keys(size.value.width), ["kind"]);
});

it("§1.4/OQ-2 Mode: Fill writes weight exactly 1 (§5 — fill weights have no v1 input)", () => {
  assert.deepEqual(
    apply(adImage(), "heightMode", "Fill"),
    updateNode("image_hero", {
      size: set({
        height: { kind: "fill", value: { weight: 1 } },
        width: { kind: "fixed", value: 1056 },
      }),
    }),
  );
});

it("§1.4/OQ-2 Mode: Fixed on an already-fixed axis keeps the size the node has", () => {
  assert.deepEqual(
    apply(adEllipse(), "widthMode", "Fixed"),
    updateNode("ellipse_proof_dot", {
      size: set({
        height: { kind: "fixed", value: 24 },
        width: { kind: "fixed", value: 24 },
      }),
    }),
  );
});

it("§1.4/OQ-2 Mode: Fixed on a HUG axis adopts the size the panel is SHOWING", () => {
  // Hydration's own derivation — the solved bounds — so the number the W/H box
  // displays is the number the flip writes. One field cloned and edited
  // (`computed` is null on every stored node; the live engine scene carries it).
  const scene = clone(SCENE);
  const node = scene.nodes.auto_row_copy;
  node.computed = {
    layout_bounds: { height: 148.55555, width: 1056, x: 72, y: 96 },
    render_bounds: { height: 148.55555, width: 1056, x: 72, y: 96 },
  };
  assert.equal(hydrateSceneInspectorState(node, scene).height, "148.556");
  assert.deepEqual(
    apply(node, "heightMode", "Fixed", scene),
    updateNode("auto_row_copy", {
      size: set({
        height: { kind: "fixed", value: 148.556 },
        width: { kind: "fixed", value: 1056 },
      }),
    }),
  );
});

it("§1.4/OQ-2 Mode: Fixed on an UNSOLVED hug axis writes nothing — no invented size", () => {
  // The panel's W/H box is empty in this state (proven in `scene-hydrate.test.ts`),
  // so there is no number to adopt. The MVP substitutes a hardcoded 120 here;
  // this lane's null contract refuses instead, the same way the radius row
  // refuses where upstream folds to 0.
  assert.equal(adAutoLayout().computed, null);
  assert.equal(apply(adAutoLayout(), "heightMode", "Fixed"), null);
});

it("§1.4/OQ-2 Mode: a label outside Fixed/Hug/Fill writes nothing", () => {
  for (const value of ["fixed", "hug", "Token", "", "constructor", "toString"]) {
    assert.equal(apply(adRect(), "widthMode", value), null, `widthMode ${value}`);
    assert.equal(apply(adRect(), "heightMode", value), null, `heightMode ${value}`);
  }
});

// ══ Plan 4 item F: "Fit to text" ═══════════════════════════════════════════
//
// The text inspector's one-click way out of a fixed height the copy outgrew.
// UNCOVERED-by-harvest: both harvested texts HUG, so the fixed-height case is
// the harvested stat with its height (and only its height) replaced — the
// width the fixture carries (256) rides through untouched, which is the whole
// point of ruling R6.

it("Plan 4 Fit to text: a fixed-height text box flips its height to hug, width untouched", () => {
  const { node, scene } = adSpannedText();
  const fixed = {
    ...node,
    size: {
      width: { kind: "fixed" as const, value: 256 },
      height: { kind: "fixed" as const, value: 216 },
    },
  };
  assert.deepEqual(
    apply(fixed, "fitToText", "1", scene),
    updateNode(fixed.id, {
      size: set({
        height: { kind: "hug" },
        width: { kind: "fixed", value: 256 },
      }),
    }),
  );
});

it("Plan 4 Fit to text: a hugging text box writes nothing; a non-text node writes nothing", () => {
  const { node, scene } = adSpannedText();
  const hugging = {
    ...node,
    size: { ...node.size, height: { kind: "hug" as const } },
  };
  assert.equal(apply(hugging, "fitToText", "1", scene), null);
  assert.equal(apply(adRect(), "fitToText", "1"), null);
});

// ══ §1.4 Auto Layout — Direction · Wrap · Gap · Grow · Pad · Align ══════════
//
// AD4.B step 2. TWO homes, so two kinds of operation: Direction and Wrap live
// on the node KIND (`AutoLayoutNode`) and ride `updateAutoLayoutNode`;
// Gap/Grow/Padding/Align live on `Node.layout` (`AutoLayoutProps`) and ride
// `updateNodeLayout`. Both carry the SAME kind guard — `auto_layout` — because
// that is hydrate's condition for these rows (the file header's standing rule)
// and because `updateAutoLayoutNode` THROWS on anything else.
//
// §1.4/OQ-2: tokens (`gap_token`/`padding_token`) and fill weights stay off the
// surface, so a spread that PRESERVES them is what keeps a write from silently
// dropping a binding no control on this panel can restate.

it("§1.4 Auto Layout Direction: the dummy's horizontal/vertical becomes the engine's row/column", () => {
  assert.deepEqual(
    apply(adAutoLayout(), "direction", "vertical"),
    updateNode("auto_row_copy", {
      kind: set({ direction: "column", kind: "auto_layout", wrap: false }),
    }),
  );
  assert.deepEqual(
    apply(adAutoLayout(), "direction", "horizontal"),
    updateNode("auto_row_copy", {
      kind: set({ direction: "row", kind: "auto_layout", wrap: false }),
    }),
  );
});

it("§1.4 Auto Layout Direction: a word outside the dummy's vocabulary writes nothing", () => {
  // The ENGINE's own spellings are not in the panel's vocabulary and are
  // therefore not accepted, exactly as `VALIGN_VALUES` refuses `center`.
  for (const value of ["row", "column", "Row", "", "constructor", "toString"]) {
    assert.equal(apply(adAutoLayout(), "direction", value), null, value);
  }
});

it("§1.4 Auto Layout Wrap: the BOOLEAN the select reports writes Node.kind.wrap", () => {
  // The §1.0 lock's posture, and the web lane's own row 22 (`apply.ts:331`):
  // a two-state control reports a boolean, so it resolves ahead of the string
  // coercion the rest of the switch shares. `state.wrap` IS a boolean
  // (`InspectorPresentationState`), so the display labels never cross this seam.
  assert.deepEqual(
    apply(adAutoLayout(), "wrap", true),
    updateNode("auto_row_copy", {
      kind: set({ direction: "row", kind: "auto_layout", wrap: true }),
    }),
  );
  assert.deepEqual(
    apply(adAutoLayout(), "wrap", false),
    updateNode("auto_row_copy", {
      kind: set({ direction: "row", kind: "auto_layout", wrap: false }),
    }),
  );
});

it("§1.4 Auto Layout Wrap: a non-boolean is refused — a display label is not the value", () => {
  for (const value of ["Wrap", "No wrap", "true", 1, null]) {
    assert.equal(apply(adAutoLayout(), "wrap", value), null, String(value));
  }
});

it("§1.4 Auto Layout Gap: a finite number rewrites gap and leaves every other layout prop alone", () => {
  assert.deepEqual(
    apply(adAutoLayout(), "gap", "12"),
    updateNodeLayout(adAutoLayout(), {
      align_x: "start",
      align_y: "center",
      gap: 12,
      grow: 0,
      padding: [40, 44, 40, 44],
    }),
  );
  // Zero is a REAL gap, not an empty box — the §1.4 stroke-width rule.
  assert.deepEqual(
    apply(adAutoLayout(), "gap", "0"),
    updateNodeLayout(adAutoLayout(), {
      align_x: "start",
      align_y: "center",
      gap: 0,
      grow: 0,
      padding: [40, 44, 40, 44],
    }),
  );
});

it("§1.4 Auto Layout Grow: a finite number rewrites grow alone", () => {
  assert.deepEqual(
    apply(adAutoLayout(), "grow", "2"),
    updateNodeLayout(adAutoLayout(), {
      align_x: "start",
      align_y: "center",
      gap: 32,
      grow: 2,
      padding: [40, 44, 40, 44],
    }),
  );
});

it("§1.4 Auto Layout Gap/Grow/Padding: a negative, unparseable or empty value writes nothing", () => {
  // The radius row's rule: the ad's fields are free text, so a number the
  // engine cannot hold is REFUSED rather than folded to 0 (which would be a
  // silent guess at an intent the box does not state).
  for (const value of ["-1", "-0.5", "abc", "", "  ", "1e400"]) {
    assert.equal(apply(adAutoLayout(), "gap", value), null, `gap ${value}`);
    assert.equal(apply(adAutoLayout(), "grow", value), null, `grow ${value}`);
    for (const side of ["top", "right", "bottom", "left"]) {
      assert.equal(
        apply(adAutoLayout(), `padding.${side}`, value),
        null,
        `padding.${side} ${value}`,
      );
    }
  }
  assert.equal(apply(adAutoLayout(), "gap", 12), null, "a non-string is not a gap");
});

it("§1.4 Auto Layout Padding: each box replaces exactly ONE slot of [top, right, bottom, left]", () => {
  // The tuple order is the wire format's (`AutoLayoutProps.padding`), and
  // hydrate destructures it the same way — so a transposed pair here would move
  // the user's number to the wrong side of the box.
  const base = {
    align_x: "start",
    align_y: "center",
    gap: 32,
    grow: 0,
  } as const;
  assert.deepEqual(
    apply(adAutoLayout(), "padding.top", "8"),
    updateNodeLayout(adAutoLayout(), { ...base, padding: [8, 44, 40, 44] }),
  );
  assert.deepEqual(
    apply(adAutoLayout(), "padding.right", "8"),
    updateNodeLayout(adAutoLayout(), { ...base, padding: [40, 8, 40, 44] }),
  );
  assert.deepEqual(
    apply(adAutoLayout(), "padding.bottom", "8"),
    updateNodeLayout(adAutoLayout(), { ...base, padding: [40, 44, 8, 44] }),
  );
  assert.deepEqual(
    apply(adAutoLayout(), "padding.left", "8"),
    updateNodeLayout(adAutoLayout(), { ...base, padding: [40, 44, 40, 8] }),
  );
});

it("§1.4 Auto Layout Align: one commit moves ONE axis and carries the other from the node", () => {
  // Two selects, two independent commits. `updateAutoLayoutAlignment` takes
  // BOTH anchors, so the untouched axis has to be read off the node — otherwise
  // choosing an Align X would silently reset Align Y to the engine's `start`.
  assert.deepEqual(
    apply(adAutoLayout(), "alignX", "Space between"),
    updateNodeLayout(adAutoLayout(), {
      align_x: "space_between",
      align_y: "center",
      gap: 32,
      grow: 0,
      padding: [40, 44, 40, 44],
    }),
  );
  assert.deepEqual(
    apply(adAutoLayout(), "alignY", "Stretch"),
    updateNodeLayout(adAutoLayout(), {
      align_x: "start",
      align_y: "stretch",
      gap: 32,
      grow: 0,
      padding: [40, 44, 40, 44],
    }),
  );
});

it("§1.4 Auto Layout Align: a label outside the five anchors writes nothing", () => {
  for (const value of ["start", "space between", "Middle", "", "constructor", "toString"]) {
    assert.equal(apply(adAutoLayout(), "alignX", value), null, `alignX ${value}`);
    assert.equal(apply(adAutoLayout(), "alignY", value), null, `alignY ${value}`);
  }
});

it("§1.4/L10 Auto Layout: a layout-LESS node seeds `defaultLayoutProps()` — the values it hydrates", () => {
  // RULING L10's write half. `Node.layout` is optional in the wire format, and
  // the section renders for such a node all the same (hydration states the
  // engine's defaults for it — proven in `scene-hydrate.test.ts`), so a commit
  // must build a WHOLE `AutoLayoutProps` from those same defaults rather than
  // refuse. The harvest's one auto-layout node carries a layout, so the field is
  // cloned away (the AD2.4/AD2.5 derived-fixture technique).
  const scene = clone(SCENE);
  const node = scene.nodes.auto_row_copy;
  node.layout = null;
  assert.deepEqual(
    apply(node, "gap", "16", scene),
    updateNodeLayout(node, {
      align_x: "start",
      align_y: "start",
      gap: 16,
      grow: 0,
      padding: [0, 0, 0, 0],
    }),
  );
  assert.deepEqual(
    apply(node, "padding.bottom", "24", scene),
    updateNodeLayout(node, {
      align_x: "start",
      align_y: "start",
      gap: 0,
      grow: 0,
      padding: [0, 0, 24, 0],
    }),
  );
  assert.deepEqual(
    apply(node, "alignY", "End", scene),
    updateNodeLayout(node, {
      align_x: "start",
      align_y: "end",
      gap: 0,
      grow: 0,
      padding: [0, 0, 0, 0],
    }),
  );
});

it("Task40: numeric gap replaces its binding and preserves padding binding and layout mode", () => {
  // Intentional correction: a numeric edit must reach export. Preserving its
  // hidden token previously made the user's input ineffective. Undo retains
  // the original binding through the authored inverse, not this new layout.
  const scene = clone(SCENE);
  const node = scene.nodes.auto_row_copy;
  node.layout = {
    ...adAutoLayout().layout!,
    gap_token: "$space.md",
    layout_mode: "stack",
    padding_token: "$space.lg",
  };
  assert.deepEqual(
    apply(node, "gap", "12", scene),
    updateNodeLayout(node, {
      align_x: "start",
      align_y: "center",
      gap: 12,
      gap_token: undefined,
      grow: 0,
      layout_mode: "stack",
      padding: [40, 44, 40, 44],
      padding_token: "$space.lg",
    }),
  );
});

it("§1.4 Auto Layout: a NON-auto-layout node writes nothing on every Auto Layout row", () => {
  // The write's kind condition is hydrate's (the file header's standing rule):
  // the Auto Layout section renders for the `auto_layout` kind alone — OQ-1
  // suppresses it for a plain Frame and no other schema carries it — and
  // `updateAutoLayoutNode` THROWS on a non-auto-layout node, so a missing guard
  // would be a crash rather than a bad write.
  const rows: [string, unknown][] = [
    ["direction", "vertical"],
    ["wrap", true],
    ["gap", "12"],
    ["grow", "2"],
    ["padding.top", "8"],
    ["padding.right", "8"],
    ["padding.bottom", "8"],
    ["padding.left", "8"],
    ["alignX", "Center"],
    ["alignY", "Center"],
  ];
  for (const [property, value] of rows) {
    assert.equal(apply(adRect(), property, value), null, `rect ${property}`);
    assert.equal(apply(adFrame(), property, value), null, `frame ${property}`);
    assert.equal(apply(adImage(), property, value), null, `image ${property}`);
    assert.equal(apply(adPlainText(), property, value), null, `text ${property}`);
  }
});

// ══ §1.4 Shape — Fill (the NODE's own fill, §1.6 policy) ════════════════════
//
// AD4.B step 3. The same two properties §1.1's Background rows carry, but
// addressed at the SELECTED NODE rather than the page's root frame — which is
// exactly what hydrate already states for every non-text kind
// (`scene-hydrate.ts`'s fill branch: text → `textColor`, everything else →
// `backgroundColor`). The write's kind condition is therefore hydrate's, the
// file header's standing rule, and the two rows share §1.1's own helpers
// (`backgroundFillsOperation` → `paintKey` + `paintFill`) rather than restating
// the policy a third time.
//
// OQ-6: the GROUP schema renders neither a Shape nor a Stroke section, so no
// group fill row exists in the panel. That is a PRESENTATION fact and it is
// deliberately not re-stated as an adapter refusal: hydrate states a group's
// fill like every other non-text kind, and a kind guard here that hydrate does
// not have is the drift the standing rule exists to prevent.

it("§1.4 Shape Fill: a hex writes ONE solid fill and reuses the paint id the node already carries", () => {
  assert.deepEqual(
    apply(adEllipse(), "backgroundColor", "#FF00AA"),
    updateNode("ellipse_proof_dot", {
      fills: set([
        {
          id: "paint_dot",
          paint: { color: { kind: "hex", value: "#ff00aa" }, kind: "solid" },
        },
      ]),
    }),
  );
});

it("§1.4 Shape Fill: a node with NO fill mints the editor's own paint id", () => {
  // `group_proof` is the harvest's own fill-less node — real bytes, no derived
  // fixture needed. It is a GROUP, whose panel renders no Shape section at all
  // (OQ-6); the row still maps, because hydrate states its fill and the write's
  // kind condition is hydrate's. The panel hiding a control is not the adapter's
  // business, exactly as the kind-agnostic radius row already establishes.
  assert.deepEqual(
    apply(adGroup(), "backgroundColor", "#FF00AA"),
    updateNode("group_proof", {
      fills: set([
        {
          id: "paint_group_proof_fill",
          paint: { color: { kind: "hex", value: "#ff00aa" }, kind: "solid" },
        },
      ]),
    }),
  );
});

it("§1.4 Shape Fill: the `none` sentinel CLEARS the fills — §1.2's stroke row, fill-side", () => {
  // Unlike §1.1's canvas Background (whose swatch lives under a fill-type
  // select and can therefore never raise the sentinel), this row is a BARE
  // swatch on a kind whose honest fill-less state hydrate spells `none`
  // (`paintState`). Committing that state means the node has no fill.
  assert.deepEqual(
    apply(adEllipse(), "backgroundColor", COLOR_NONE),
    updateNode("ellipse_proof_dot", { fills: set([]) }),
  );
});

it("§1.6 guard: a GRADIENT-filled node is not writable through the single swatch", () => {
  // `rect_accent_bar` is the harvest's real 3-stop linear gradient. A bare
  // swatch cannot SHOW a gradient, so a solid write here would destroy one the
  // user never saw — the §1.2 Color row's rule, and the reason §1.1's
  // Background swatch is exempt (a fill-type select made that switch explicit)
  // does not apply to this row.
  assert.equal(apply(adRect(), "backgroundColor", "#FF00AA"), null);
  assert.equal(apply(adRect(), "backgroundColor", COLOR_NONE), null);
  assert.equal(
    apply(adRect(), "tokenBackgroundColor", "surface.brand", SCENE, AD_PALETTE),
    null,
  );
});

it("§1.6 guard: a MULTI-LAYER fill is not writable through either Shape Fill row", () => {
  const { node, scene } = withNodeField("ellipse_proof_dot", "fills", [
    ...adEllipse().fills,
    ...adFrame().fills,
  ]);
  assert.equal(apply(node, "backgroundColor", "#FF00AA", scene), null);
  assert.equal(
    apply(node, "tokenBackgroundColor", "surface.brand", scene, AD_PALETTE),
    null,
  );
});

it("§1.4 Shape Fill: a TEXT node is refused — hydrate routes ITS fill to textColor", () => {
  // The exact inverse of the §1.2 Color row's "a NON-text node is refused".
  // Together the two say the fill of any node is writable through exactly one
  // property, so no schema can address a fill the panel is not showing.
  assert.equal(apply(adPlainText(), "backgroundColor", "#FF00AA"), null);
  assert.equal(apply(adTokenText(), "backgroundColor", "#FF00AA"), null);
  assert.equal(
    apply(adPlainText(), "tokenBackgroundColor", "surface.brand", SCENE, AD_PALETTE),
    null,
  );
});

it("§1.4 Shape Fill: anything that is not a hex or the sentinel is refused, never guessed black", () => {
  for (const value of ["", "  ", "#FFF", "rebeccapurple", "123456"]) {
    assert.equal(apply(adEllipse(), "backgroundColor", value), null, value);
  }
  assert.equal(apply(adEllipse(), "backgroundColor", 16711680), null);
});

it("§1.6 Shape Fill: a brand swatch binds the node's fill to the TOKEN, keeping the paint id", () => {
  assert.deepEqual(
    apply(adEllipse(), "tokenBackgroundColor", "surface.brand", SCENE, AD_PALETTE),
    updateNode("ellipse_proof_dot", {
      fills: set([
        { id: "paint_dot", paint: { kind: "token", token: "surface.brand" } },
      ]),
    }),
  );
});

it("§1.6 Shape Fill: a label the kit does not define, and NO palette at all, write nothing", () => {
  assert.equal(
    apply(adEllipse(), "tokenBackgroundColor", "not.a.token", SCENE, AD_PALETTE),
    null,
  );
  assert.equal(apply(adEllipse(), "tokenBackgroundColor", "surface.brand"), null);
});

it("§1.6 Shape Fill: re-committing the paint the node ALREADY wears is NOT a write", () => {
  // `backgroundFillsOperation`'s standing rule, inherited whole: `ColorControl`
  // re-commits its hex on blur whether or not it moved, so without this guard
  // opening and closing the picker would mint a document version and an undo
  // step that change nothing. `paintKey` folds the two spellings of one token
  // (`$text.inverse` and the bare name the picker reports) onto one identity.
  assert.equal(apply(adEllipse(), "backgroundColor", "#EA2261"), null);
  const { node, scene } = withNodeField("ellipse_proof_dot", "fills", [
    ...adTokenText().fills,
  ]);
  assert.equal(
    apply(node, "tokenBackgroundColor", "text.inverse", scene, AD_PALETTE),
    null,
  );
  // A DIFFERENT token on the same node is a real change, and keeps the id.
  assert.deepEqual(
    apply(node, "tokenBackgroundColor", "surface.brand", scene, AD_PALETTE),
    updateNode("ellipse_proof_dot", {
      fills: set([
        { id: "paint_headline", paint: { kind: "token", token: "surface.brand" } },
      ]),
    }),
  );
});

it("§4: a LOCKED node refuses both Shape Fill rows", () => {
  const { node, scene } = withNodeField("ellipse_proof_dot", "locked", true);
  assert.equal(apply(node, "backgroundColor", "#FF00AA", scene), null);
  assert.equal(apply(node, "backgroundColor", COLOR_NONE, scene), null);
  assert.equal(
    apply(node, "tokenBackgroundColor", "surface.brand", scene, AD_PALETTE),
    null,
  );
});

// ══ §1.4 Shape/Stroke — the rows AD4.B step 3 only had to BIND ══════════════

it("§1.4 Shape/Stroke: the newly bound schemas reach the EXISTING radius and stroke rows", () => {
  // The radius and stroke rows carry NO kind guard, deliberately (the file
  // header says so), precisely so the rect / ellipse / auto-layout schemas
  // inherit them rather than needing a second implementation. Step 3 binds the
  // controls; this is the proof the events they now raise land.
  assert.deepEqual(
    apply(adRect(), "radius.all", "8"),
    updateNode("rect_accent_bar", {
      corner: set({
        bottom_left: 8,
        bottom_right: 8,
        top_left: 8,
        top_right: 8,
        token: null,
      }),
    }),
  );
  assert.deepEqual(
    apply(adAutoLayout(), "strokeWidth", "3"),
    updateNode("auto_row_copy", {
      strokes: set([
        {
          id: "stroke_card",
          paint: { color: { kind: "hex", value: "#2E2470" }, kind: "solid" },
          width: 3,
          width_token: null,
        },
      ]),
    }),
  );
  // A9 on an ellipse: a colour on a strokeless node mints upstream's width.
  assert.deepEqual(
    apply(adEllipse(), "strokeColor", "#FF00AA"),
    updateNode("ellipse_proof_dot", {
      strokes: set([
        {
          id: "paint_ellipse_proof_dot_stroke",
          paint: { color: { kind: "hex", value: "#ff00aa" }, kind: "solid" },
          width: 1,
          width_token: null,
        },
      ]),
    }),
  );
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

it("§1.0 Lock: a locked AUTO-LAYOUT node refuses every Auto Layout row (AD4.B step 2)", () => {
  // Stated on its own node because the row set above runs on a TEXT node,
  // which the §1.4 Auto Layout rows refuse for their kind guard alone — that
  // would prove nothing about the lock.
  const { node, scene } = withNodeField("auto_row_copy", "locked", true);
  const rows: [string, unknown][] = [
    ["direction", "vertical"],
    ["wrap", true],
    ["gap", "12"],
    ["grow", "2"],
    ["padding.top", "8"],
    ["padding.right", "8"],
    ["padding.bottom", "8"],
    ["padding.left", "8"],
    ["alignX", "Center"],
    ["alignY", "Center"],
  ];
  for (const [property, value] of rows) {
    assert.equal(apply(node, property, value, scene), null, property);
  }
  assert.deepEqual(
    apply(node, "locked", false, scene),
    updateNode("auto_row_copy", { locked: set(false) }),
  );
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
    // AD4.B step 1's §1.4 rows join the same global gate.
    ["width", "400"],
    ["height", "400"],
    ["opacity", "50"],
    ["widthMode", "Hug"],
    ["heightMode", "Fill"],
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
  // AD4.A took `radius.*` and `fillMode` out of it — §1.3's two rows are
  // mapped now, and their own cases below cover them (the radius row is
  // deliberately kind-agnostic, so it WRITES on this very node). AD4.B step 1
  // took `opacity` out for the same reason (§1.4's Layout section), step 2
  // took `gap` and its Auto Layout siblings, and step 3 took
  // `backgroundColor`/`tokenBackgroundColor` — the Shape section's Fill row,
  // node-addressed (their own cases are above).
  //
  // What is LEFT is `backgroundFill`, the fill-TYPE select. §1.1's canvas
  // function maps it on the page's root frame, but no ad NODE schema offers a
  // fill-type control at all (§1.4's Shape section is one bare swatch), so a
  // node-addressed event carrying it is nobody's row.
  for (const node of [adAutoLayout(), adRect(), adEllipse()]) {
    assert.equal(apply(node, "backgroundFill", { type: "solid" }), null, node.id);
  }
});

it("null contract: the §1.1 CANVAS rows never write through the node function", () => {
  // AD4.0 maps these — but on the PAGE, through the sibling function below.
  // A node-addressed event carrying one of them is somebody else's row.
  for (const property of ["sizePreset", "customWidth", "customHeight"]) {
    assert.equal(apply(adAutoLayout(), property, "1080"), null, property);
    assert.equal(apply(adPlainText(), property, "1080"), null, property);
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

// ══ §1.1 row 1 — the CANVAS (page) size preset + Custom W/H ═════════════════
//
// A second function, because these rows target a PAGE: the canvas selection is
// the EMPTY selection, so there is no Node to hand an adapter. Same harvested
// bytes, same null contract.

function applyCanvas(
  property: string,
  value: unknown,
  scene: Scene = SCENE,
  pageId: PageId = AD_PAGE_ID,
  palette: ScenePalette | null = null,
): ReturnType<typeof sceneCanvasChangeToOperation> {
  // `selectionId: null` is the honest canvas addressing — the caller's gate
  // proves it; the adapter holds no selection either way.
  return sceneCanvasChangeToOperation(
    { property, selectionId: null, value },
    scene,
    pageId,
    palette,
  );
}

/** The expected operation, through the ENGINE's own page-patch builder: only
 * `size` is `set`, so a write that also touched the page's name, bleed, safe
 * area or background would fail loudly. */
function updatePage(pageId: string, patch: Partial<PagePatch>) {
  return { kind: "update_page", page_id: pageId, patch: pagePatch(patch) };
}

/**
 * The canonical page size the engine mints for an authored PX size — a `pt`
 * layout box, the authored px on `source`, the export size on `output.raster`,
 * `preset: "custom"`, and an orientation DERIVED from the numbers
 * (`engine/scene/pageGeometry.ts::normalizePageSize`, the same helper the
 * standalone editor's own custom-size write goes through).
 *
 * Spelled out here rather than called, so these tests state the bytes they
 * expect instead of restating the implementation.
 */
function pxPage(width: number, height: number): PageSize {
  return {
    height,
    orientation: width > height ? "landscape" : "portrait",
    output: { raster: { height_px: height, width_px: width } },
    preset: "custom",
    source: { height, unit: "px", width },
    unit: "pt",
    width,
  };
}

/** genad2 Task 6: the same expectation for a PHYSICAL page — the shape
 * `normalizePageSize` mints for `mm`/`in`. The conversion is restated here
 * (rather than borrowed from the port) so the expected numbers are this test's
 * own statement; the expression order matches `pageGeometry.ts::unitToPoints`
 * exactly, because float multiplication is not associative. */
function physicalPage(
  width: number,
  height: number,
  unit: "in" | "mm",
): PageSize {
  const toPoints = (value: number) =>
    unit === "mm" ? (value * 72) / 25.4 : value * 72;
  return {
    height: toPoints(height),
    orientation: width > height ? "landscape" : "portrait",
    output: { physical: { height, unit, width } },
    preset: "custom",
    source: { height, unit, width },
    unit: "pt",
    width: toPoints(width),
  };
}

/** genad2 Task 6: a `pt` page. `pt` is already the canonical unit, so the
 * normalizer mints NO `output` at all — the key is absent, not undefined. */
function ptPage(width: number, height: number): PageSize {
  return {
    height,
    orientation: width > height ? "landscape" : "portrait",
    preset: "custom",
    source: { height, unit: "pt", width },
    unit: "pt",
    width,
  };
}

it("§1.1 Size preset: each of the three ratified labels writes its exact px size", () => {
  const presets: [string, number, number][] = [
    ["Linkedin square (1:1) - 1200x1200", 1200, 1200],
    ["Instagram portrait (4:5) - 1080x1350", 1080, 1350],
    ["Story (9:16) - 1080x1920", 1080, 1920],
  ];
  for (const [label, width, height] of presets) {
    assert.deepEqual(
      applyCanvas("sizePreset", label),
      updatePage(AD_PAGE_ID, { size: set(pxPage(width, height)) }),
      label,
    );
  }
});

it('§1.1 Size preset: "Custom" names no size — the W/H inputs carry it — so it writes nothing', () => {
  assert.equal(applyCanvas("sizePreset", "Custom"), null);
});

it("§1.1 Size preset: a label the select does not offer writes nothing", () => {
  for (const value of [
    // §2.1's RETIRED LinkedIn value — a stale label must not resize the page.
    "Linkedin square (1:1) - 1024x1024",
    "Instagram portrait (4:5)",
    "linkedin_ad",
    "",
  ]) {
    assert.equal(applyCanvas("sizePreset", value), null, value);
  }
  assert.equal(applyCanvas("sizePreset", 1200), null);
});

it("§1.1 Custom W: the typed width keeps the HEIGHT the inspector is showing", () => {
  // The harvested page displays 1200x1200 px (hydrate's `pageDisplaySize` reads
  // `output.raster` first), so a width edit must land 1080x1200.
  assert.deepEqual(
    applyCanvas("customWidth", "1080"),
    updatePage(AD_PAGE_ID, { size: set(pxPage(1080, 1200)) }),
  );
});

it("§1.1 Custom H: the typed height keeps the WIDTH the inspector is showing", () => {
  assert.deepEqual(
    applyCanvas("customHeight", "1920"),
    updatePage(AD_PAGE_ID, { size: set(pxPage(1200, 1920)) }),
  );
});

it("§1.1 Custom W/H: the preserved dimension is what the panel DISPLAYS, not the layout box", () => {
  // UNCOVERED by the harvest, and the sharp edge of the px trap: a fractional
  // authored px size is the one shape whose pt box and px raster differ (the
  // raster rounds). This page is minted by the engine's own normalizer, so it
  // is a real shape, not an invented one — its box is 628.4 while the panel
  // shows 628, and the write must keep the number on screen.
  const scene = clone(SCENE);
  scene.pages[AD_PAGE_ID].size = normalizePageSize({
    height: 628.4,
    preset: "custom",
    unit: "px",
    width: 1200,
  });
  assert.equal(scene.pages[AD_PAGE_ID].size.height, 628.4);
  assert.equal(hydrateSceneCanvasState(scene, AD_PAGE_ID).customHeight, "628");
  assert.deepEqual(
    applyCanvas("customWidth", "1080", scene),
    updatePage(AD_PAGE_ID, { size: set(pxPage(1080, 628)) }),
  );
});

/**
 * CONSCIOUS TRIP-WIRE REWRITE — 2026-08-23, genad2 Task 6
 * (`docs/superpowers/plans/2026-08-23-agent-authored-pages.md`).
 *
 * This slot used to hold "§1.1 Custom W/H: the written size is CANONICAL
 * whatever unit the stored page carries", which pinned that a page carrying
 * `mm` still wrote px. That pin was written when §1.1 was px-only and the only
 * page in the world was the seeded 1200x1200 ad; under the agent-authored-pages
 * ruling the design agent births pages in mm and in, and the behaviour it
 * guarded is DATA LOSS — an A4 page's width edit silently converted the
 * document to raster and dropped `output.physical`.
 *
 * The half of it that was never about destruction survives verbatim below as
 * the source-precedence pin: what the write reads is the page's AUTHORED unit
 * (`size.source.unit`), not the stale box unit, so the original fixture — a px
 * source under a hand-edited `mm` box — still writes px, and the output is
 * still the engine's canonical shape rather than a `{...page.size}` spread.
 */
it("Task 6: an mm page's H commit stays MILLIMETRES and keeps output.physical", () => {
  const scene = clone(SCENE);
  scene.pages[AD_PAGE_ID].size = normalizePageSize({
    height: 297,
    preset: "a4",
    unit: "mm",
    width: 210,
  });
  assert.deepEqual(
    applyCanvas("customHeight", "300", scene),
    updatePage(AD_PAGE_ID, {
      size: set(physicalPage(210, 300, "mm")),
    }),
  );
  // The destroyed facts, named one at a time so a regression says which.
  const operation = applyCanvas("customHeight", "300", scene);
  assert.ok(operation && operation.kind === "update_page");
  const size = operation.patch.size;
  assert.ok(size.kind === "set");
  assert.deepEqual(size.value.output, {
    physical: { height: 300, unit: "mm", width: 210 },
  });
  assert.equal(size.value.source?.unit, "mm");
  assert.equal(size.value.output?.raster, undefined);
});

it("Task 6: an inches page's W commit stays INCHES", () => {
  const scene = clone(SCENE);
  scene.pages[AD_PAGE_ID].size = normalizePageSize({
    height: 11,
    preset: "us_letter",
    unit: "in",
    width: 8.5,
  });
  assert.deepEqual(
    applyCanvas("customWidth", "17", scene),
    updatePage(AD_PAGE_ID, { size: set(physicalPage(17, 11, "in")) }),
  );
});

it("Task 6: the AUTHORED unit decides, not the stored box unit", () => {
  // The original pin's fixture, kept: ONE field edited (the page's geometry
  // unit) over a px `source`. `pageDisplaySize` reads the source, so the `mm`
  // here is the stale box it always was and the write is still canonical px —
  // a `pt` box, a freshly minted px source and raster, never the `mm` riding
  // through and never the plan's `{...page.size}` spread.
  const scene = clone(SCENE);
  scene.pages[AD_PAGE_ID].size.unit = "mm";
  assert.deepEqual(
    applyCanvas("customHeight", "1350", scene),
    updatePage(AD_PAGE_ID, { size: set(pxPage(1200, 1350)) }),
  );
});

it("Task 6: the stored preset survives a commit that still matches it, and only then", () => {
  // Engine semantics (`lumen-core/page_geometry.rs::page_size_for_preset`): a4
  // is 210x297 mm short-side-first, so a re-typed 297 is still A4 (portrait or
  // landscape) and anything else is `custom`. Before this, EVERY W/H commit
  // stamped `custom` — a no-op re-type demoted an A4 document to a custom size.
  const a4 = clone(SCENE);
  a4.pages[AD_PAGE_ID].size = normalizePageSize({
    height: 297,
    preset: "a4",
    unit: "mm",
    width: 210,
  });
  const preserved = applyCanvas("customHeight", "297", a4);
  assert.ok(preserved && preserved.kind === "update_page");
  assert.ok(preserved.patch.size.kind === "set");
  assert.equal(preserved.patch.size.value.preset, "a4");
  const demoted = applyCanvas("customHeight", "300", a4);
  assert.ok(demoted && demoted.kind === "update_page");
  assert.ok(demoted.patch.size.kind === "set");
  assert.equal(demoted.patch.size.value.preset, "custom");
});

it("Task 6: px pages keep stamping custom — the preset row's labels are CLIENT vocabulary", () => {
  // The three select labels are px sizes this client named; none of them is an
  // engine `PagePreset`, so that row writes `custom` exactly as it always did,
  // and a `linkedin_ad` page resized to one of them is no longer a linkedin_ad.
  const banner = clone(SCENE);
  banner.pages[AD_PAGE_ID].size = normalizePageSize({
    height: 627,
    preset: "linkedin_ad",
    unit: "px",
    width: 1200,
  });
  assert.deepEqual(
    applyCanvas("sizePreset", "Story (9:16) - 1080x1920", banner),
    updatePage(AD_PAGE_ID, { size: set(pxPage(1080, 1920)) }),
  );
  // Its own numbers re-typed, though, are still a linkedin_ad banner.
  const preserved = applyCanvas("customHeight", "627", banner);
  assert.ok(preserved && preserved.kind === "update_page");
  assert.ok(preserved.patch.size.kind === "set");
  assert.equal(preserved.patch.size.value.preset, "linkedin_ad");
});

/** A page whose DISPLAYED size is not a usable number: the px metadata is
 * dropped so `pageDisplaySize` falls through to the canonical box (its
 * documented last resort), and that box carries the degenerate value. Derived
 * from the harvest, one dimension at a time. Note the box is a `pt` box, so
 * this page displays — and commits — `pt`; see the repair assertions below. */
function degeneratePage(axis: "height" | "width", value: number): Scene {
  const scene = clone(SCENE);
  const page = scene.pages[AD_PAGE_ID];
  page.size = { ...page.size, output: undefined, source: undefined };
  page.size[axis] = value;
  return scene;
}

it("§1.1 Custom W/H: a preserved dimension that is not a usable px number is REFUSED, never defaulted to 1", () => {
  // `normalizePageSize` substitutes 1 for any non-finite or non-positive
  // dimension (`pageGeometry.ts` `normalizePositiveDimension`) — a silent guess,
  // and exactly what the null contract forbids. The typed number is guarded, so
  // the preserved one must be too, or a broken page turns a width edit into a
  // 1px-tall document.
  for (const bad of [0, -20, 0.5, Number.NaN, Number.POSITIVE_INFINITY]) {
    assert.equal(
      applyCanvas("customWidth", "1080", degeneratePage("height", bad)),
      null,
      `height ${bad}`,
    );
    assert.equal(
      applyCanvas("customHeight", "1080", degeneratePage("width", bad)),
      null,
      `width ${bad}`,
    );
  }
  // The refusal is about the PRESERVED dimension only, so the broken axis is
  // still repairable by typing into it — the typed number replaces the value
  // that could not be stated, and nothing is guessed. Both axes, symmetrically.
  //
  // genad2 Task 6: the repair writes `pt`, not px. Stripping the px metadata is
  // exactly what makes this page fall through to the canonical box, and the box
  // is a `pt` box — so `pt` is what the panel now DISPLAYS for it, and the
  // commit lands in the unit the panel is showing. Nothing about this page ever
  // said px; the old expectation was §1.1's px hard-code, not a fact of the
  // document.
  assert.deepEqual(
    applyCanvas("customHeight", "1080", degeneratePage("height", 0)),
    updatePage(AD_PAGE_ID, { size: set(ptPage(1200, 1080)) }),
  );
  assert.deepEqual(
    applyCanvas("customWidth", "1080", degeneratePage("width", 0)),
    updatePage(AD_PAGE_ID, { size: set(ptPage(1080, 1200)) }),
  );
});

it("§1.1: orientation is RECOMPUTED from the written numbers, never spread from the old page", () => {
  assert.equal(SCENE.pages[AD_PAGE_ID].size.orientation, "portrait");
  const operation = applyCanvas("customWidth", "1920");
  assert.ok(operation && operation.kind === "update_page");
  const size = operation.patch.size;
  assert.ok(size.kind === "set");
  assert.equal(size.value.orientation, "landscape");
  assert.equal(size.value.preset, "custom");
  assert.equal(size.value.unit, "pt");
});

it("§1.1: the write is the exact inverse of hydrate — the written size re-hydrates as itself", () => {
  // The plan's literal `{...page.size}` spread fails HERE: it would keep the
  // harvested page's `source`/`output.raster` (1200x1200 px), and hydrate reads
  // the raster first — so the select would snap straight back to LinkedIn
  // square the moment the panel re-read the document.
  const rehydrate = (operation: ReturnType<typeof applyCanvas>) => {
    assert.ok(operation && operation.kind === "update_page");
    const size = operation.patch.size;
    assert.ok(size.kind === "set");
    const written = clone(SCENE);
    written.pages[AD_PAGE_ID].size = size.value;
    return hydrateSceneCanvasState(written, AD_PAGE_ID);
  };
  assert.equal(
    rehydrate(applyCanvas("sizePreset", "Story (9:16) - 1080x1920")).sizePreset,
    "Story (9:16) - 1080x1920",
  );
  const custom = rehydrate(applyCanvas("customWidth", "1080"));
  assert.equal(custom.sizePreset, "Custom");
  assert.equal(custom.customWidth, "1080");
  assert.equal(custom.customHeight, "1200");
});

it("§1.1 Custom W/H: NaN, below 1, empty and non-strings are refused", () => {
  // Both inputs are free-text `InspectorInput`s firing per KEYSTROKE, exactly
  // like §1.2's Size box, so "", "-" and "1e" are ordinary mid-edit events.
  for (const value of ["abc", "0", "-1", "0.5", "", "  ", "-", "1e", "1e400"]) {
    assert.equal(applyCanvas("customWidth", value), null, value);
    assert.equal(applyCanvas("customHeight", value), null, value);
  }
  assert.equal(applyCanvas("customWidth", 1080), null);
  assert.equal(applyCanvas("customHeight", Number.NaN), null);
});

it("§1.1 null contract: a page the live scene does not carry writes nothing", () => {
  assert.equal(
    applyCanvas("sizePreset", "Story (9:16) - 1080x1920", SCENE, "page_missing"),
    null,
  );
  assert.equal(applyCanvas("customWidth", "1080", SCENE, "page_missing"), null);
});

it("§1.1 null contract: the canvas function maps the SIZE and BACKGROUND rows only", () => {
  // §1.1 has exactly two rows. Every §1.2 row belongs to the node function,
  // and the header lock is a node row too — a page carries no lock.
  for (const property of ["locked", "fontSize", "position.x", "notAProperty"]) {
    assert.equal(applyCanvas(property, "12"), null, property);
  }
});

// ══ §1.1 row 2 — the CANVAS Background (the ROOT FRAME's fills) ═════════════
//
// The founder ruling: the Background control edits the root frame's fill, NOT
// the page's own `background` property. So these rows are raised by a
// page-addressed event and land on a NODE — the asymmetry `scene-apply.ts`'s
// header records. Two properties serve the one row: `backgroundColor` (the
// solid swatch's hex) and `backgroundFill` (the whole fill object, which is
// what the fill-type select and the gradient editor commit).

/** The harvested scene with the ROOT FRAME's fills replaced — one field, the
 * one these rows read and write.
 *
 * The fills are DEEP-copied: callers hand it paints lifted off other harvested
 * nodes (`adRect().fills`), and a shallow copy would alias the frozen
 * fixture's own objects — `rootRadialGradient` below edits the paint it is
 * given, which would otherwise rewrite `HARVESTED_AD_PAGE` for every later
 * test in the file. */
function withRootFills(fills: Node["fills"]): Scene {
  const scene = clone(SCENE);
  const root = scene.nodes[AD_ROOT_FRAME_ID];
  assert.ok(root, "fixture root frame missing");
  root.fills = JSON.parse(JSON.stringify(fills)) as Node["fills"];
  return scene;
}

/** The harvested LINEAR gradient (`rect_accent_bar`'s real 3-stop paint, angle
 * 90) moved onto the root frame — never an invented paint. */
function rootLinearGradient(): Scene {
  return withRootFills([...adRect().fills]);
}

/** The same harvested gradient as a RADIAL one: the harvest has no radial
 * paint (a real ad had no plausible one), so the one field the two kinds
 * differ by is edited — `radial_gradient` carries no `angle`. */
function rootRadialGradient(): Scene {
  const scene = rootLinearGradient();
  const paint = scene.nodes[AD_ROOT_FRAME_ID].fills[0].paint;
  assert.equal(paint.kind, "linear_gradient");
  scene.nodes[AD_ROOT_FRAME_ID].fills[0].paint = {
    kind: "radial_gradient",
    stops: paint.kind === "linear_gradient" ? paint.stops : [],
  };
  return scene;
}

/** The gradient above as the CONTROL states it — the exact object
 * `hydrateSceneCanvasState` produces for it, so these tests drive the write
 * with what the panel is actually holding. */
function harvestedGradientState(scene: Scene): InspectorBackgroundFill {
  const fill = hydrateSceneCanvasState(scene, AD_PAGE_ID).backgroundFill;
  assert.ok(fill, "the canvas state always states a background fill");
  return fill;
}

it("§1.1 Background: a hex writes ONE solid fill on the ROOT FRAME, reusing its paint id", () => {
  // The PAGE is untouched — `background` stays the empty array the harvest
  // carries — and the write names the frame, not the page.
  assert.deepEqual(SCENE.pages[AD_PAGE_ID].background, []);
  assert.deepEqual(
    applyCanvas("backgroundColor", "#FF00AA"),
    updateNode(AD_ROOT_FRAME_ID, {
      fills: set([
        {
          id: "paint_root_ink",
          paint: { color: { kind: "hex", value: "#ff00aa" }, kind: "solid" },
        },
      ]),
    }),
  );
});

it("§1.1 Background: a root frame with no fill mints the editor's own paint id", () => {
  assert.deepEqual(
    applyCanvas("backgroundColor", "#FF00AA", withRootFills([])),
    updateNode(AD_ROOT_FRAME_ID, {
      fills: set([
        {
          id: "paint_frame_ad_root_fill",
          paint: { color: { kind: "hex", value: "#ff00aa" }, kind: "solid" },
        },
      ]),
    }),
  );
});

it("§1.6: a raw hex on a TOKEN-bound root frame detaches the brand binding", () => {
  // The harvested `$text.inverse` token paint, moved onto the root frame. Same
  // ratified trade the §1.2 Color row makes, on the canvas schema.
  const scene = withRootFills([...adTokenText().fills]);
  assert.deepEqual(
    applyCanvas("backgroundColor", "#123ABC", scene),
    updateNode(AD_ROOT_FRAME_ID, {
      fills: set([
        {
          id: "paint_headline",
          paint: { color: { kind: "hex", value: "#123abc" }, kind: "solid" },
        },
      ]),
    }),
  );
});

it("§1.1 Background: with NO root frame nothing is written (AD2.4's null contract)", () => {
  const rootless = clone(SCENE);
  rootless.pages[AD_PAGE_ID].children = [];
  assert.equal(applyCanvas("backgroundColor", "#FF00AA", rootless), null);
  assert.equal(
    applyCanvas(
      "backgroundFill",
      harvestedGradientState(rootLinearGradient()),
      rootless,
    ),
    null,
  );
});

it("§4: a LOCKED root frame refuses both Background rows", () => {
  // "Lock gates every write path". The size rows have no lock to honour (a
  // Page carries none); these land on a node, which does.
  const locked = clone(SCENE);
  locked.nodes[AD_ROOT_FRAME_ID].locked = true;
  assert.equal(applyCanvas("backgroundColor", "#FF00AA", locked), null);
  const gradient = clone(rootLinearGradient());
  gradient.nodes[AD_ROOT_FRAME_ID].locked = true;
  assert.equal(
    applyCanvas("backgroundFill", { ...harvestedGradientState(gradient), angle: 12 }, gradient),
    null,
  );
});

it("§1.1 Background: anything that is not a hex is refused rather than guessed black", () => {
  for (const value of ["", "  ", "#FFF", "rebeccapurple", "123456"]) {
    assert.equal(applyCanvas("backgroundColor", value), null, value);
  }
  assert.equal(applyCanvas("backgroundColor", 16711680), null);
});

it('§1.1 Background: the "none" sentinel is refused — this control cannot raise it', () => {
  // `ColorControl` commits through `commitColor`, which fires `onColorChange`
  // ONLY for /^#[0-9A-F]{6}$/i (`inspector-primitives.tsx`), and its `none`
  // prop (a DISABLED swatch) is never passed by `BackgroundFillControl`. So
  // there is no clear-the-fills branch to build: the sentinel cannot reach
  // this seam, and an event carrying it is not from this control.
  assert.equal(applyCanvas("backgroundColor", COLOR_NONE), null);
});

it("§1.6 guard: a MULTI-LAYER fill is not writable through either Background row", () => {
  // The panel shows ONE fill and every write replaces the whole array, so a
  // second layer would be destroyed by a control that never showed it — the
  // upstream `isGradientGuarded` rationale, which holds here unchanged.
  const scene = withRootFills([...adFrame().fills, ...adRect().fills]);
  assert.equal(applyCanvas("backgroundColor", "#FF00AA", scene), null);
  assert.equal(
    applyCanvas("backgroundFill", { ...harvestedGradientState(scene), angle: 12 }, scene),
    null,
  );
});

it("§1.6 guard: a GRADIENT root frame IS writable through the swatch — the select made it explicit", () => {
  // DELIBERATE DIVERGENCE from the §1.2 Color row's gradient guard, and the
  // reason is the control: `textColor` is a bare swatch that cannot show a
  // gradient at all, so a write there would clobber one the user never saw.
  // The Background control has a FILL-TYPE SELECT above the swatch, and the
  // swatch is only rendered while that select says "Solid"
  // (`inspector-primitives.tsx` `BackgroundFillControl`) — so reaching this
  // row means the user asked for a solid on purpose. Refusing would dead-end
  // the gradient→solid transition, because the type select itself commits no
  // colour (see the `type: "solid"` row below).
  assert.deepEqual(
    applyCanvas("backgroundColor", "#FF00AA", rootLinearGradient()),
    updateNode(AD_ROOT_FRAME_ID, {
      fills: set([
        {
          id: "paint_accent_bar",
          paint: { color: { kind: "hex", value: "#ff00aa" }, kind: "solid" },
        },
      ]),
    }),
  );
});

it("§1.1 Background: a LINEAR gradient writes angle + the engine's 0–1 stop positions", () => {
  assert.deepEqual(
    applyCanvas("backgroundFill", {
      angle: 90,
      stops: [
        { color: "#533AFD", position: 0 },
        { color: "#8B5CF6", position: 25 },
        { color: "#EA2261", position: 100 },
      ],
      type: "linear-gradient",
    }),
    updateNode(AD_ROOT_FRAME_ID, {
      fills: set([
        {
          id: "paint_root_ink",
          paint: {
            angle: 90,
            kind: "linear_gradient",
            stops: [
              { color: { kind: "hex", value: "#533afd" }, position: 0 },
              { color: { kind: "hex", value: "#8b5cf6" }, position: 0.25 },
              { color: { kind: "hex", value: "#ea2261" }, position: 1 },
            ],
          },
        },
      ]),
    }),
  );
});

it("§1.1 Background: a RADIAL gradient writes its stops and DROPS the angle (§5 loss)", () => {
  // `Paint::RadialGradient { stops }` has no angle field (`contracts.ts`, and
  // `scene.rs:1203-1206` upstream). §8 authorizes no engine change, so the
  // angle the dummy's object always carries is dropped here — and the row
  // below proves the drop cannot become a phantom write.
  assert.deepEqual(
    applyCanvas("backgroundFill", {
      angle: 217,
      stops: [
        { color: "#533AFD", position: 0 },
        { color: "#EA2261", position: 100 },
      ],
      type: "radial-gradient",
    }),
    updateNode(AD_ROOT_FRAME_ID, {
      fills: set([
        {
          id: "paint_root_ink",
          paint: {
            kind: "radial_gradient",
            stops: [
              { color: { kind: "hex", value: "#533afd" }, position: 0 },
              { color: { kind: "hex", value: "#ea2261" }, position: 1 },
            ],
          },
        },
      ]),
    }),
  );
});

it('§1.1 Background: the fill object\'s "solid" type carries no colour, so it writes nothing', () => {
  // The ruling is "write the swatch's current colour"; the event does not
  // carry it (`onFillChange` is handed `{angle, stops, type}` and the swatch
  // colour is a separate prop), and in the only case that reaches here the
  // control is showing the dummy's seed rather than a document
  // colour. `stops[0]` is not it either — the stops are inert while solid.
  // Both refusals, and the founder-facing gap they leave, are argued in full
  // at `backgroundPaint`'s `solid` case.
  assert.equal(
    applyCanvas("backgroundFill", {
      angle: 0,
      stops: [
        { color: "#533AFD", position: 0 },
        { color: "#EA2261", position: 100 },
      ],
      type: "solid",
    }),
    null,
  );
});

it("§1.1 Background: the gradient stop count is the dummy's own 2–6 ceiling", () => {
  // The engine's floor is ONE stop (`dsl.rs` LUMD0239/LUMD0240) and it sets no
  // maximum; the DUMMY is the stricter authority here — its Add button is
  // `disabled` at 6 stops and every Remove is `disabled` at 2
  // (`inspector-primitives.tsx` `BackgroundFillControl`), which is the plan's
  // "2–6 stops". A list outside that range did not come from this control.
  const stop = (position: number) => ({ color: "#533AFD", position });
  const gradient = (count: number) => ({
    angle: 90,
    stops: Array.from({ length: count }, (_, index) => stop(index * 5)),
    type: "linear-gradient" as const,
  });
  for (const count of [0, 1, 7, 12]) {
    assert.equal(applyCanvas("backgroundFill", gradient(count)), null, `${count}`);
  }
  for (const count of [2, 3, 6]) {
    assert.ok(applyCanvas("backgroundFill", gradient(count)), `${count}`);
  }
});

it("§1.1 Background: ONE unmappable stop colour refuses the WHOLE write", () => {
  // Including the shape a token-bound stop hydrates as: `colorText` states a
  // token color as its `$name`, which is not a hex — so an angle drag on a
  // brand-bound gradient refuses rather than silently detaching every stop
  // (§1.6 licenses detaching on a raw COLOUR write, which this is not).
  for (const bad of ["$text.inverse", "none", "#FFF", "", 16711680, null]) {
    assert.equal(
      applyCanvas("backgroundFill", {
        angle: 90,
        stops: [
          { color: "#533AFD", position: 0 },
          { color: bad, position: 100 },
        ],
        type: "linear-gradient",
      }),
      null,
      String(bad),
    );
  }
});

it("§1.1 Background: a stop position outside 0–100% is refused, never clamped", () => {
  // The renderer CLAMPS a stop into 0–1 (`lumen-skia/src/render.rs:1875`) —
  // a silent substitution, which is exactly what the null contract forbids —
  // and the control's own input clamps to 0–100 before it ever commits, so an
  // out-of-range position did not come from this control.
  for (const position of [-1, 101, Number.NaN, Number.POSITIVE_INFINITY, "50"]) {
    assert.equal(
      applyCanvas("backgroundFill", {
        angle: 90,
        stops: [
          { color: "#533AFD", position: 0 },
          { color: "#EA2261", position },
        ],
        type: "linear-gradient",
      }),
      null,
      String(position),
    );
  }
});

it("§1.1 Background: a non-finite linear ANGLE is refused; a radial ignores the angle entirely", () => {
  const linear = (angle: unknown) => ({
    angle,
    stops: [
      { color: "#533AFD", position: 0 },
      { color: "#EA2261", position: 100 },
    ],
    type: "linear-gradient",
  });
  for (const angle of [Number.NaN, Number.POSITIVE_INFINITY, "90", null]) {
    assert.equal(applyCanvas("backgroundFill", linear(angle)), null, String(angle));
  }
  // A finite angle outside the control's 0–360 clamp is still WRITTEN: the
  // engine stores `angle: f64` verbatim and rotation is modular, so nothing is
  // substituted and nothing is guessed (unlike a clamped position).
  assert.ok(applyCanvas("backgroundFill", linear(-45)), "-45");
  assert.ok(
    applyCanvas("backgroundFill", { ...linear(Number.NaN), type: "radial-gradient" }),
    "radial ignores NaN",
  );
});

it("§1.1 Background: a value that is not a fill object writes nothing", () => {
  for (const value of [null, "#FF00AA", 42, [], { type: "conic-gradient" }, {}]) {
    assert.equal(applyCanvas("backgroundFill", value), null, JSON.stringify(value));
  }
});

it("§1.1 Background: a mapped paint identical to the one already stored is NOT a write", () => {
  // The dummy's fill object ALWAYS carries an angle; `radial_gradient` cannot
  // store one. Without this rule, dragging the angle control on a radial fill
  // would persist a document version per drag tick whose paint is byte-for-
  // byte what was already there.
  const scene = rootRadialGradient();
  const shown = harvestedGradientState(scene);
  assert.equal(shown.type, "radial-gradient");
  assert.equal(applyCanvas("backgroundFill", { ...shown, angle: 217 }, scene), null);
  assert.equal(applyCanvas("backgroundFill", shown, scene), null);
  // A real change to the same fill still writes.
  assert.ok(
    applyCanvas(
      "backgroundFill",
      { ...shown, stops: [...shown.stops.slice(0, -1), { color: "#FFFFFF", position: 100 }] },
      scene,
    ),
    "a changed stop still writes",
  );
});

it("§1.1 Background: re-committing the colour the frame already has is NOT a write", () => {
  // `ColorControl` commits on blur whether or not the hex changed, and the
  // comparison is on the CANONICAL paint — the harvested `#0E0B2E` and the
  // control's upper-cased `#0E0B2E` are the same colour, not a document
  // version.
  assert.equal(applyCanvas("backgroundColor", "#0E0B2E"), null);
  assert.equal(applyCanvas("backgroundColor", "#0e0b2e"), null);
  assert.ok(applyCanvas("backgroundColor", "#0E0B2F"), "a different colour writes");
});

it("§1.1 Background: the linear round trip preserves the angle and every stop", () => {
  // hydrate(apply(x)) === x, on the exact object the control holds.
  const scene = clone(SCENE);
  const shown: InspectorBackgroundFill = {
    angle: 137,
    stops: [
      { color: "#533AFD", position: 0 },
      { color: "#8B5CF6", position: 25 },
      { color: "#EA2261", position: 100 },
    ],
    type: "linear-gradient",
  };
  assert.deepEqual(harvestedGradientState(rehydrateBackground(scene, shown)), shown);
});

it("§1.1 Background: the radial round trip loses EXACTLY the angle, and nothing else", () => {
  // The recorded §5 loss, pinned: the angle reverts to 0 on the next reload
  // (the engine has no field for it, and §8 authorizes no engine change), the
  // stops and the type survive intact.
  const shown: InspectorBackgroundFill = {
    angle: 217,
    stops: [
      { color: "#533AFD", position: 0 },
      { color: "#EA2261", position: 60 },
    ],
    type: "radial-gradient",
  };
  assert.deepEqual(harvestedGradientState(rehydrateBackground(clone(SCENE), shown)), {
    ...shown,
    angle: 0,
  });
});

/** The scene as it stands AFTER the Background write the control's state asks
 * for — the operation applied to the root frame by hand, because these tests
 * hold no engine. */
function rehydrateBackground(scene: Scene, fill: InspectorBackgroundFill): Scene {
  const operation = applyCanvas("backgroundFill", fill, scene);
  assert.ok(operation && operation.kind === "update_node", "the write is a node update");
  const fills = operation.patch.fills;
  assert.ok(fills.kind === "set", "the patch sets fills");
  const written = clone(scene);
  written.nodes[AD_ROOT_FRAME_ID].fills = fills.value;
  return written;
}

// ══ Ruling A15.2 — one mode switch is ONE document version ══════════════════

it("A15.2: a gradient → SOLID switch produces EXACTLY ONE operation, and it is the colour", () => {
  // The handler returns two commits (the type, so the control renders the
  // swatch; then the colour, the only row that carries one). This is the
  // property that matters: run BOTH through the adapter against the scene the
  // panel is showing and exactly one operation comes out, so one click is one
  // document version — never two, and never a lost write to the one-in-flight
  // discipline.
  const scene = rootLinearGradient();
  const shown = harvestedGradientState(scene);
  const operations = backgroundFillCommits(
    shown,
    { ...shown, type: "solid" },
    hydrateSceneCanvasState(scene, AD_PAGE_ID).backgroundColor ?? "",
  )
    .map((commit) => applyCanvas(commit.property, commit.value, scene))
    .filter((operation) => operation !== null);
  assert.equal(operations.length, 1);
  assert.deepEqual(
    operations[0],
    updateNode(AD_ROOT_FRAME_ID, {
      fills: set([
        {
          id: "paint_accent_bar",
          // The outgoing gradient's FIRST STOP — a colour the document has.
          paint: { color: { kind: "hex", value: "#533afd" }, kind: "solid" },
        },
      ]),
    }),
  );
});

it("A15.2: a SOLID → gradient switch is one operation carrying the colour on screen", () => {
  // Defect 1, end to end: the harvested frame is solid `#0E0B2E`; a user who
  // has just committed `#2E7D32` and then picks a gradient must get THAT
  // colour, not the one the panel was born with.
  const shown = hydrateSceneCanvasState(SCENE, AD_PAGE_ID).backgroundFill;
  assert.ok(shown, "the canvas state always states a background fill");
  const operations = backgroundFillCommits(
    shown,
    { ...shown, type: "linear-gradient" },
    "#2E7D32",
  )
    .map((commit) => applyCanvas(commit.property, commit.value, SCENE))
    .filter((operation) => operation !== null);
  assert.equal(operations.length, 1);
  assert.deepEqual(
    operations[0],
    updateNode(AD_ROOT_FRAME_ID, {
      fills: set([
        {
          id: "paint_root_ink",
          paint: {
            angle: 0,
            kind: "linear_gradient",
            stops: [
              { color: { kind: "hex", value: "#2e7d32" }, position: 0 },
              { color: { kind: "hex", value: "#2e7d32" }, position: 1 },
            ],
          },
        },
      ]),
    }),
  );
});

// ══ §1.6 — a brand swatch writes a TOKEN (AD4.0 step 3) ════════════════════
//
// The other half of the row every colour control above already owns: a pick
// from the Theme tab reports the token's LABEL, and the write binds the paint
// to that brand token instead of burning in a hex. The label is validated
// against the document's own palette, so a label the picker never rendered —
// including the dummy's fixture palette when no kit is attached — is not a
// write.

it("§1.6 Color: a brand swatch binds the text fill to the TOKEN, keeping the paint id", () => {
  assert.deepEqual(
    apply(adPlainText(), "tokenTextColor", "text.inverse", SCENE, AD_PALETTE),
    updateNode("text_proof_stat", {
      fills: set([
        { id: "paint_stat", paint: { kind: "token", token: "text.inverse" } },
      ]),
    }),
  );
});

it("§1.6 Color: the token is written BARE — the `$` is author-facing sugar", () => {
  // Upstream's own writer takes the catalog's bare name
  // (`ColorSwatchControl.tsx:38-41` → `tokenFill`, whose token comes from
  // `BrandTokenCatalog`) while rendering it as `$${token}`. The kit's keys are
  // bare too, so bare is the canonical stored form and both spellings resolve
  // to one entry.
  //
  // Proven on the seeded headline, whose stored fill really is the sugared
  // `$text.inverse`, by picking a DIFFERENT token: the `$` is not carried over
  // from the paint being replaced. (Re-picking `text.inverse` itself is the
  // no-op FIX 1 covers, which is the same fold seen from the other side.)
  assert.deepEqual(
    apply(adTokenText(), "tokenTextColor", "surface.card", SCENE, AD_PALETTE),
    updateNode("text_headline", {
      fills: set([
        { id: "paint_headline", paint: { kind: "token", token: "surface.card" } },
      ]),
    }),
  );
});

it("§1.6 ROUND TRIP on real data: token → hex detaches, hex → token re-binds", () => {
  // `text_headline` really is token-filled (`$text.inverse`), so both legs run
  // against the document as it is stored, not against a derived shape.
  const detach = apply(adTokenText(), "textColor", "#123ABC");
  assert.deepEqual(
    detach,
    updateNode("text_headline", {
      fills: set([
        {
          id: "paint_headline",
          paint: { color: { kind: "hex", value: "#123abc" }, kind: "solid" },
        },
      ]),
    }),
  );
  // The detached node, exactly as the engine would hold it after that write —
  // a DEEP copy, so the shared fixture is untouched.
  const detached = clone(SCENE);
  detached.nodes.text_headline.fills = [
    { id: "paint_headline", paint: { color: { kind: "hex", value: "#123abc" }, kind: "solid" } },
  ];
  assert.deepEqual(
    apply(
      detached.nodes.text_headline,
      "tokenTextColor",
      "text.inverse",
      detached,
      AD_PALETTE,
    ),
    updateNode("text_headline", {
      fills: set([
        // The SAME paint id survives the whole round trip.
        { id: "paint_headline", paint: { kind: "token", token: "text.inverse" } },
      ]),
    }),
  );
});

it("§1.6 Color: a label this document's kit does not define is NOT a write", () => {
  // Labels the retired fixture palette used to offer (no palette exists any
  // more, but a stale label could still arrive). Writing `{kind:"token",
  // token:"Primary"}` would bind the ad to a token nothing can resolve.
  for (const label of ["Primary", "Dark", "Subtle"]) {
    assert.equal(
      apply(adPlainText(), "tokenTextColor", label, SCENE, AD_PALETTE),
      null,
      label,
    );
  }
  // A ramp and the kit's legacy alias RESOLVE but are not offered, so no pick
  // can have produced them either.
  assert.equal(
    apply(adPlainText(), "tokenTextColor", "palette.primary.600", SCENE, AD_PALETTE),
    null,
  );
  assert.equal(
    apply(adPlainText(), "tokenTextColor", "accent.primary", SCENE, AD_PALETTE),
    null,
  );
  assert.equal(apply(adPlainText(), "tokenTextColor", "", SCENE, AD_PALETTE), null);
  assert.equal(apply(adPlainText(), "tokenTextColor", 7, SCENE, AD_PALETTE), null);
});

it("§1.6 Color: with NO palette every token row refuses — nothing validates the label", () => {
  assert.equal(apply(adPlainText(), "tokenTextColor", "text.inverse"), null);
  assert.equal(apply(adAutoLayout(), "tokenStrokeColor", "border.brand"), null);
  assert.equal(applyCanvas("tokenBackgroundColor", "text.inverse"), null);
});

it("§1.6 Color: the token row keeps the §1.2 guards — kind, gradient, multi-fill, lock", () => {
  // The write's kind condition is hydrate's kind condition, so a rect's fill
  // is `backgroundColor`'s and a token pick on it is not this row.
  assert.equal(apply(adRect(), "tokenTextColor", "text.inverse", SCENE, AD_PALETTE), null);
  const gradient = withNodeField("text_proof_stat", "fills", [...adRect().fills]);
  assert.equal(
    apply(gradient.node, "tokenTextColor", "text.inverse", gradient.scene, AD_PALETTE),
    null,
  );
  const layered = withNodeField("text_proof_stat", "fills", [
    ...adPlainText().fills,
    ...adTokenText().fills,
  ]);
  assert.equal(
    apply(layered.node, "tokenTextColor", "text.inverse", layered.scene, AD_PALETTE),
    null,
  );
  const locked = withNodeField("text_proof_stat", "locked", true);
  assert.equal(
    apply(locked.node, "tokenTextColor", "text.inverse", locked.scene, AD_PALETTE),
    null,
  );
});

it("§1.6 Stroke: a brand swatch binds the stroke paint and keeps the width verbatim", () => {
  assert.deepEqual(
    apply(adAutoLayout(), "tokenStrokeColor", "border.brand", SCENE, AD_PALETTE),
    updateNode("auto_row_copy", {
      strokes: set([
        {
          id: "stroke_card",
          paint: { kind: "token", token: "border.brand" },
          width: 2,
          width_token: null,
        },
      ]),
    }),
  );
});

it("A9: a brand swatch on a STROKELESS node mints the same default width", () => {
  // Identical to the hex row's rule, for the identical reason — A9 applies to
  // both halves of the Stroke row, or the row is coherent in only one of them.
  assert.deepEqual(
    apply(adPlainText(), "tokenStrokeColor", "border.brand", SCENE, AD_PALETTE),
    updateNode("text_proof_stat", {
      strokes: set([
        {
          id: "paint_text_proof_stat_stroke",
          paint: { kind: "token", token: "border.brand" },
          width: 1,
          width_token: null,
        },
      ]),
    }),
  );
});

it("§1.6 Background: a brand swatch binds the ROOT FRAME's fill to the token", () => {
  assert.deepEqual(
    applyCanvas("tokenBackgroundColor", "surface.brand", SCENE, AD_PAGE_ID, AD_PALETTE),
    updateNode(AD_ROOT_FRAME_ID, {
      fills: set([
        { id: "paint_root_ink", paint: { kind: "token", token: "surface.brand" } },
      ]),
    }),
  );
});

it("§1.6 Background: re-picking the token the frame ALREADY has writes nothing, `$` or not", () => {
  // Standing ruling: a change that produces a Paint identical to the stored
  // one is not a write. The two spellings of one token are the same binding —
  // the harvested `$text.inverse` and the bare name the picker reports — so
  // re-picking it must not mint a document version that changes only sugar.
  const scene = withRootFills([...adTokenText().fills]);
  assert.equal(
    applyCanvas("tokenBackgroundColor", "text.inverse", scene, AD_PAGE_ID, AD_PALETTE),
    null,
  );
  // A DIFFERENT token on the same frame is a real change, and keeps the id.
  assert.deepEqual(
    applyCanvas("tokenBackgroundColor", "surface.brand", scene, AD_PAGE_ID, AD_PALETTE),
    updateNode(AD_ROOT_FRAME_ID, {
      fills: set([
        { id: "paint_headline", paint: { kind: "token", token: "surface.brand" } },
      ]),
    }),
  );
});

it("§1.6 Background: the token row keeps the §1.1 refusals — no root, locked, multi-fill", () => {
  const rootless = clone(SCENE);
  rootless.pages[AD_PAGE_ID].children = [];
  assert.equal(
    applyCanvas("tokenBackgroundColor", "surface.brand", rootless, AD_PAGE_ID, AD_PALETTE),
    null,
  );
  const locked = clone(SCENE);
  locked.nodes[AD_ROOT_FRAME_ID].locked = true;
  assert.equal(
    applyCanvas("tokenBackgroundColor", "surface.brand", locked, AD_PAGE_ID, AD_PALETTE),
    null,
  );
  const layered = withRootFills([...adFrame().fills, ...adRect().fills]);
  assert.equal(
    applyCanvas("tokenBackgroundColor", "surface.brand", layered, AD_PAGE_ID, AD_PALETTE),
    null,
  );
});

// ══ FIX 1 (review) — the no-op guarantee binds ALL THREE token rows ═════════
//
// Step 3 shipped it on the Background row only (`backgroundFillsOperation`),
// so re-picking the swatch a TEXT node or a STROKE already wears minted a
// document version — and on the seeded headline it changed nothing but the
// `$` sugar, with the picker already showing that swatch as pressed. The
// `$`-folding `paintKey` was there; the two node rows just never asked it.

it("FIX 1: re-picking the token a TEXT node already wears writes nothing, `$` or not", () => {
  // `text_headline`'s stored fill is `{kind:"token", token:"$text.inverse"}`
  // and the picker reports the bare name — one binding, two spellings.
  assert.equal(
    apply(adTokenText(), "tokenTextColor", "text.inverse", SCENE, AD_PALETTE),
    null,
  );
  // A DIFFERENT token is a real change and still writes, keeping the paint id.
  assert.deepEqual(
    apply(adTokenText(), "tokenTextColor", "surface.brand", SCENE, AD_PALETTE),
    updateNode("text_headline", {
      fills: set([
        { id: "paint_headline", paint: { kind: "token", token: "surface.brand" } },
      ]),
    }),
  );
});

it("FIX 1: a token pick over a HEX fill is a change — detaching is never a no-op", () => {
  assert.deepEqual(
    apply(adPlainText(), "tokenTextColor", "text.inverse", SCENE, AD_PALETTE),
    updateNode("text_proof_stat", {
      fills: set([
        { id: "paint_stat", paint: { kind: "token", token: "text.inverse" } },
      ]),
    }),
  );
});

it("FIX 1: re-picking the token a STROKE already wears writes nothing", () => {
  // UNCOVERED by the harvest: no harvested stroke is token-bound. One field of
  // a DEEP copy carries the harvested stroke with a token paint, so the
  // comparison runs against otherwise-real bytes.
  const { node, scene } = withNodeField("auto_row_copy", "strokes", [
    { ...adAutoLayout().strokes[0], paint: { kind: "token", token: "$border.brand" } },
  ]);
  assert.equal(
    apply(node, "tokenStrokeColor", "border.brand", scene, AD_PALETTE),
    null,
  );
  assert.deepEqual(
    apply(node, "tokenStrokeColor", "border.subtle", scene, AD_PALETTE),
    updateNode("auto_row_copy", {
      strokes: set([
        {
          id: "stroke_card",
          paint: { kind: "token", token: "border.subtle" },
          width: 2,
          width_token: null,
        },
      ]),
    }),
  );
});

it("FIX 1: a stroke whose WIDTH TOKEN the write would clear is still a change", () => {
  // `strokeWith` always writes `width_token: null` (upstream's own rule on a
  // raw width edit), so an identical paint over a width-token-bound stroke is
  // NOT an identical stroke — the comparison is the whole stroke, not just its
  // paint, or this write would be silently dropped.
  const { node, scene } = withNodeField("auto_row_copy", "strokes", [
    {
      ...adAutoLayout().strokes[0],
      paint: { kind: "token", token: "border.brand" },
      width_token: "stroke.width.hairline",
    },
  ]);
  assert.deepEqual(
    apply(node, "tokenStrokeColor", "border.brand", scene, AD_PALETTE),
    updateNode("auto_row_copy", {
      strokes: set([
        {
          id: "stroke_card",
          paint: { kind: "token", token: "border.brand" },
          width: 2,
          width_token: null,
        },
      ]),
    }),
  );
});

// ══ FIX 4 (review) — the `$` fold matches the engine's, exactly ════════════

it("FIX 4: the token fold strips `$` and NOTHING else — no trimming the engine does not do", () => {
  // `resolveTokenColor` strips a leading `$` and looks the name up verbatim,
  // so `" surface.brand"` is a DIFFERENT (and unresolvable) token to the
  // engine. Folding whitespace here would have made the two compare equal and
  // left such a document unrepairable: picking the real token would be read as
  // a no-op and write nothing.
  const { node, scene } = withNodeField("text_proof_stat", "fills", [
    { id: "paint_stat", paint: { kind: "token", token: " surface.brand" } },
  ]);
  assert.deepEqual(
    apply(node, "tokenTextColor", "surface.brand", scene, AD_PALETTE),
    updateNode("text_proof_stat", {
      fills: set([
        { id: "paint_stat", paint: { kind: "token", token: "surface.brand" } },
      ]),
    }),
  );
});

// ══ AD4.A / §1.3 row 1 — Mode (Fit | Fill | Crop) ═══════════════════════════
//
// The harvested `image_hero` carries `fit: "cover"` (the dummy's "Fill") and a
// real focal point, which is what makes the preserve-everything-else assertions
// worth making: Gate G-C ships NO focal control, so the focal point can only
// ride along untouched or be silently destroyed.

/** The harvested image's whole stored placement, deep-copied. */
function heroPlacement(): AssetPlacement {
  return JSON.parse(JSON.stringify(adImage().asset_placement)) as AssetPlacement;
}

it("§1.3 Mode: `Fit` writes `contain` and preserves every other placement field", () => {
  assert.deepEqual(
    apply(adImage(), "fillMode", "Fit"),
    updateNode("image_hero", {
      asset_placement: set({ ...heroPlacement(), fit: "contain" }),
    }),
  );
});

it("§1.3 Mode: `Crop` writes `crop` and the node's FOCAL POINT rides along untouched (G-C)", () => {
  // The whole point of the row under G-C, which ships no focal control: the
  // seeded focal point is 0.5/0.42 and the crop window is computed FROM it
  // (`lumen-export/src/svg.rs::focal_crop_geometry`), so a write that dropped
  // it would recentre the image the moment the user chose Crop. `heroPlacement`
  // is the node's whole stored placement, so this asserts the preservation of
  // every field, not just that one.
  assert.deepEqual(
    apply(adImage(), "fillMode", "Crop"),
    updateNode("image_hero", {
      asset_placement: set({ ...heroPlacement(), fit: "crop" }),
    }),
  );
});

it("§1.3 Mode: `Fill` on a `cover` image writes NOTHING — a change that changes nothing is not a write", () => {
  assert.equal(apply(adImage(), "fillMode", "Fill"), null);
});

it("§1.3 Mode: an image with NO asset_placement MINTS one rather than refusing", () => {
  // UNCOVERED by the harvest: `image_hero` carries a full placement.
  // `asset_placement` is `Option` + `skip_serializing_if` in the core, so its
  // absence is a real stored shape.
  //
  // Upstream's own image inspector reads `node.asset_placement ?? {}` and
  // emits `{...placement, fit}` (`ImageInspectorSection.tsx:80-87,198-210`), so
  // minting is the LIFT and refusing would be the divergence — and refusing
  // would leave the select showing a mode the document never got (the standing
  // "a control may not display a value the document does not have" rule).
  const { node, scene } = withNodeField("image_hero", "asset_placement", undefined);
  assert.deepEqual(
    apply(node, "fillMode", "Crop", scene),
    updateNode("image_hero", { asset_placement: set({ fit: "crop" }) }),
  );
});

it("§1.3 Mode: `Fit` on a placement-less image writes nothing — absent fit IS `contain`", () => {
  // `Some(Contain) | None => "xMidYMid meet"` (`lumen-export/src/svg.rs:1759-1770`),
  // and the rasterizer's `(_, Some(ratio))` arm agrees — so such a node already
  // renders exactly what "Fit" asks for. (Unreachable from the select, which is
  // already showing "Fit" for it and fires no change event when the same option
  // is re-picked; the guard is stated because the row's rule is "compare against
  // the fit the node effectively has", not "against a stored key".)
  const { node, scene } = withNodeField("image_hero", "asset_placement", undefined);
  assert.equal(apply(node, "fillMode", "Fit", scene), null);
});

it("§1.3 Mode: a NON-IMAGE node writes nothing — the write's kind guard is hydrate's", () => {
  // `scene-hydrate.ts` states `fillMode` for an image node and nothing else, so
  // accepting it for a text or a rect would write a property that node does not
  // hydrate (the file header's standing rule).
  assert.equal(apply(adPlainText(), "fillMode", "Fill"), null);
  assert.equal(apply(adRect(), "fillMode", "Fill"), null);
  assert.equal(apply(adFrame(), "fillMode", "Fill"), null);
});

it("§1.3 Mode: a label outside the three, and a non-string value, write nothing", () => {
  for (const label of ["Stretch", "Tile", "cover", "fill", "", "FIT"]) {
    assert.equal(apply(adImage(), "fillMode", label), null, label);
  }
  assert.equal(apply(adImage(), "fillMode", 1), null, "a number is not a label");
});

it("§1.3 Mode: a LOCKED image writes nothing (§4)", () => {
  const { node, scene } = withNodeField("image_hero", "locked", true);
  assert.equal(apply(node, "fillMode", "Fit", scene), null);
});

// ══ AD4.A / §1.3 row 2 — Radius (all + four corners) ════════════════════════
//
// The corner-order trap, precisely: the TS/Rust struct order is TL, TR, BR, BL
// while the stored bytes read TL, TR, BL, BR. Both sides serialize BY FIELD
// NAME, so key order cannot break correctness on its own — but any positional
// thinking (a tuple, an array, `Object.values`) transposes BR and BL silently.
// The harvested image is the one node that fails loudly: BL 96, BR 32.

it("§1.3 Radius: ONE corner is written and the other three are untouched — the BR/BL trap", () => {
  // `image_hero` is the node that fails LOUDLY on a transposition: it is the
  // asymmetric one (BL 96, BR 32), so a positional build — a tuple, an array,
  // an `Object.values()` — would move the 96 into `bottom_right` and leave
  // `bottom_left` holding the 24 this write aimed at the other corner. Only
  // `bottom_right` may move here, and `bottom_left` must still read 96.
  assert.deepEqual(
    apply(adImage(), "radius.bottomRight", "24"),
    updateNode("image_hero", {
      corner: set({
        bottom_left: 96,
        bottom_right: 24,
        top_left: 32,
        top_right: 32,
        token: null,
      }),
    }),
  );
});

it("§1.3 Radius: each named corner writes its OWN field", () => {
  const base = { bottom_left: 96, bottom_right: 32, top_left: 32, top_right: 32 };
  const cases = [
    ["radius.topLeft", { ...base, top_left: 7 }],
    ["radius.topRight", { ...base, top_right: 7 }],
    ["radius.bottomLeft", { ...base, bottom_left: 7 }],
    ["radius.bottomRight", { ...base, bottom_right: 7 }],
  ] as const;
  for (const [property, expected] of cases) {
    assert.deepEqual(
      apply(adImage(), property, "7"),
      updateNode("image_hero", { corner: set({ ...expected, token: null }) }),
      property,
    );
  }
});

it("§1.3 Radius: `all` writes all four corners in one operation", () => {
  assert.deepEqual(
    apply(adImage(), "radius.all", "12"),
    updateNode("image_hero", {
      corner: set({
        bottom_left: 12,
        bottom_right: 12,
        top_left: 12,
        top_right: 12,
        token: null,
      }),
    }),
  );
});

it("§1.3 Radius: a raw write CLEARS `corner.token` (§4), and clearing it is itself a change", () => {
  // UNCOVERED by the harvest: no harvested node is radius-token-bound. One
  // field of a DEEP copy carries the real corners plus a token.
  const { node, scene } = withNodeField("image_hero", "corner", {
    bottom_left: 96,
    bottom_right: 32,
    top_left: 32,
    top_right: 32,
    token: "radius.card",
  });
  // The same four numbers the node already has — but the write would DETACH
  // its token, and the renderer prefers a resolved token over the numbers
  // (`renderAdapter.ts:270-301`), so this is a real change, not a no-op. The
  // exact shape of `sameStroke`'s `width_token` rule.
  assert.deepEqual(
    apply(node, "radius.bottomRight", "32", scene),
    updateNode("image_hero", {
      corner: set({
        bottom_left: 96,
        bottom_right: 32,
        top_left: 32,
        top_right: 32,
        token: null,
      }),
    }),
  );
});

it("§1.3 Radius: a corner that already holds the typed number writes nothing", () => {
  // The fan-out rule: the ad schema passes no `onApplyAll`, so ONE all-corners
  // gesture dispatches several corner events, and every corner that already
  // held that value would otherwise mint an empty document version and an
  // empty undo step. `rect_accent_bar` is uniform at 5, so all five properties
  // are no-ops on it.
  for (const property of [
    "radius.all",
    "radius.bottomLeft",
    "radius.bottomRight",
    "radius.topLeft",
    "radius.topRight",
  ]) {
    assert.equal(apply(adRect(), property, "5"), null, property);
  }
  // On the ASYMMETRIC image, only the corner that matches is a no-op.
  assert.equal(apply(adImage(), "radius.bottomRight", "32"), null, "BR already 32");
  assert.ok(apply(adImage(), "radius.bottomLeft", "32"), "BL is 96, so 32 is a change");
});

it("§1.3 Radius: an unparseable or NEGATIVE value writes nothing, and is never clamped", () => {
  // Upstream SUBSTITUTES here (`normalizeCornerRadius` folds a negative and a
  // non-finite to 0, `RawStyleSection.tsx:181-183`) because its field is an
  // `<input type="number" min="0">` that cannot produce one. The ad's field is
  // free text, so the same substitution would be a silent guess — the null
  // contract's own case, settled the way §1.2's stroke width settles it.
  for (const value of ["", " ", "-1", "abc", "1e", "24px", "NaN"]) {
    assert.equal(apply(adImage(), "radius.all", value), null, JSON.stringify(value));
  }
  assert.equal(apply(adImage(), "radius.all", 12), null, "a number is not a typed field");
});

it("§1.3 Radius: a fractional radius is rounded the way the editor rounds, not refused", () => {
  // `roundForEditor` is upstream's own (`fields.tsx:174`), applied at the one
  // site upstream applies it to a radius (`normalizeCornerRadius`).
  assert.deepEqual(
    apply(adImage(), "radius.all", "12.34567"),
    updateNode("image_hero", {
      corner: set({
        bottom_left: 12.346,
        bottom_right: 12.346,
        top_left: 12.346,
        top_right: 12.346,
        token: null,
      }),
    }),
  );
});

it("§1.3 Radius: the row is KIND-AGNOSTIC — hydrate's radius mapping has no kind guard either", () => {
  // Lane B's rectangle and auto-layout schemas reach this same code path; the
  // standing rule is that the write's kind condition IS hydrate's, and
  // hydrate reads `node.corner` for every kind.
  assert.deepEqual(
    apply(adAutoLayout(), "radius.topLeft", "4"),
    updateNode("auto_row_copy", {
      corner: set({
        bottom_left: 96,
        bottom_right: 32,
        top_left: 4,
        top_right: 32,
        token: null,
      }),
    }),
  );
  assert.ok(apply(adEllipse(), "radius.all", "9"), "an ellipse writes too");
});

it("§1.3 Radius: a LOCKED node writes nothing (§4)", () => {
  const { node, scene } = withNodeField("image_hero", "locked", true);
  for (const property of ["radius.all", "radius.topLeft"]) {
    assert.equal(apply(node, property, "8", scene), null, property);
  }
});

it("RULING A26: the scan button is ONE all-corners write, never four corner writes", () => {
  // The clobber this replaces: the scan button used to fire four synchronous
  // `onChange(corner, values.all)` calls, and the write listener's scene is a
  // passive-effect ref over React state — so all four events read the SAME
  // pre-burst node while every radius operation writes the whole `CornerRadii`.
  // The fourth clobbered the first three. On the seeded ad's 32/32/96/32 image
  // a scan of 24 landed 32/32/96/24: one corner moved, four undo steps.
  //
  // Half one, the component: the scan button now dispatches through
  // `commitAll`, which fires a single `radius.all`. Read off disk because a
  // `.tsx` cannot be imported under this runner (`tsx --test`, no DOM) — the
  // technique `scene-hydrate.test.ts`'s vocabulary guard already uses.
  const source = readFileSync(
    join(
      dirname(fileURLToPath(import.meta.url)),
      "../../chat-shell/components/inspector-primitives.tsx",
    ),
    "utf8",
  );
  const applyAll = source.slice(
    source.indexOf("const applyAll = () => {"),
    source.indexOf("\n  };", source.indexOf("const applyAll = () => {")),
  );
  assert.ok(applyAll.length > 0, "applyAll not found in inspector-primitives.tsx");
  assert.ok(
    applyAll.includes("commitAll(radius.draft.all)"),
    "the scan button must commit the all field's DRAFT through commitAll",
  );
  for (const corner of ["topLeft", "topRight", "bottomLeft", "bottomRight"]) {
    assert.ok(
      !applyAll.includes(corner),
      `the scan button must not fan out to ${corner} — four events cannot compose into one document`,
    );
  }

  // Half two, the adapter: that one event writes all four corners at once.
  assert.deepEqual(
    apply(adImage(), "radius.all", "24"),
    updateNode("image_hero", {
      corner: set({
        bottom_left: 24,
        bottom_right: 24,
        top_left: 24,
        top_right: 24,
        token: null,
      }),
    }),
  );
  // Stated as the defect it replaces, so a regression cannot read as a pass:
  // the clobber's own result is NOT what this row produces.
  assert.notDeepEqual(
    (apply(adImage(), "radius.all", "24") as { patch: NodePatch }).patch.corner,
    set({
      bottom_left: 96,
      bottom_right: 24,
      top_left: 32,
      top_right: 32,
      token: null,
    }),
    "the fourth fan-out operation's result must not be what a scan produces",
  );
});

it("RULING A27: after an all-commit, re-typing a corner's PRE-commit number still writes", () => {
  // The trap this closes, browser-proven at the A26 review: with the document
  // at all-corners-24, typing 96 into bottom-left left the BOX reading 96 and
  // the DOCUMENT reading 24 — a silent no-op and a lying field at once — and it
  // blocked restoring the seeded document's own corners (32/32/96/32) by hand,
  // because every one of those numbers was exactly what the controller still
  // held. The cause was the corner fields' dirty check comparing the draft
  // against the `values` PROP (the controller's `state.radius`), which an ad
  // all-write does not move: it dispatches one `radius.all`, so the four corner
  // entries stay where they were.
  //
  // Half one, the component — and since AD4.R Task 7 the answer is DIFFERENT
  // PER LANE, because A27's premise only ever held on one of them (plan
  // `docs/superpowers/plans/2026-08-22-ad-inspector-mvp-state-model.md`,
  // §"Rulings superseded"). Read off disk for the reason the A26 guard above
  // states.
  const source = readFileSync(
    join(
      dirname(fileURLToPath(import.meta.url)),
      "../../chat-shell/components/inspector-primitives.tsx",
    ),
    "utf8",
  );
  const body = source.slice(
    source.indexOf("export function RadiusControls"),
    source.indexOf("type HsvColor"),
  );
  assert.ok(body.length > 0, "RadiusControls not found in inspector-primitives.tsx");

  // THE WEB LANE — A27 exactly as ratified, and untouched by Task 7. The web
  // inspector still seeds `state.radius` once at mount, so the local snapshot
  // is still the only thing there that knows what the document holds.
  assert.ok(
    body.includes("committed: values"),
    "the committed snapshot must still be SEEDED from the values prop at mount",
  );
  assert.ok(
    body.includes("radius.committed[corner]"),
    "a corner's dirty check must compare against the committed snapshot",
  );
  // The web ALL box's dirty check (`radius.draft.all !== radius.committed.all`)
  // is pinned by nothing else, and its negative survives Task 7 untouched: the
  // scene lane reads `values[corner]` (never `values.all`, even for `all`, which
  // it reaches as a corner key), so this still means what it always meant.
  assert.ok(
    !body.includes("values.all"),
    "the all field's dirty check must NOT compare against the values prop either",
  );

  // THE SCENE LANE — A27's premise is GONE. It was "an ad all-write does not
  // move the values prop", which was true only while that prop was a mount-time
  // copy of the document. Live hydration (Task 4) makes it the document itself,
  // moving in the same batch as the write, so comparing against it is not
  // merely safe — it is the one comparison that cannot go stale. The snapshot
  // that stood in for it is therefore deleted here, not merely bypassed.
  assert.ok(
    body.includes("fieldCommit(drafts[corner] ?? null, values[corner])"),
    "the scene lane's dirty check must compare the draft against the LIVE document value",
  );
  assert.ok(
    body.includes("fieldDisplay(drafts[corner] ?? null, values[corner])"),
    "the scene lane's boxes must project the LIVE document value",
  );

  // Half two, the adapter: the write path really does accept that re-type once
  // the component stops swallowing it. The scene is the document AS IT IS after
  // an all-commit of 24, and 96 is `image_hero`'s own pre-commit bottom-left —
  // the exact repro.
  const { node, scene } = withNodeField("image_hero", "corner", {
    bottom_left: 24,
    bottom_right: 24,
    top_left: 24,
    top_right: 24,
  });
  assert.deepEqual(
    apply(node, "radius.bottomLeft", "96", scene),
    updateNode("image_hero", {
      corner: set({
        bottom_left: 96,
        bottom_right: 24,
        top_left: 24,
        top_right: 24,
        token: null,
      }),
    }),
  );
});

it("null contract: a key inherited from Object.prototype is not a vocabulary entry", () => {
  // `TABLE[key]` finds `Object.prototype`'s own members for these labels — a
  // FUNCTION, which is `!== undefined`, so a `=== undefined` guard passes and
  // the row emits `fit: <Function>` / `font_weight: <Function>`. `JSON.stringify`
  // then DROPS that key, so a label outside the vocabulary would silently CLEAR
  // the field it was supposed to leave alone. Not reachable from the selects,
  // which offer only their own options — but a stored document is JSON and the
  // null contract is not a function of what the UI happens to offer.
  // `vocabulary()` (scene-hydrate.ts) closes every one of these lookups at once.
  const { node: fixedText, scene: fixedScene } = fixedHeightText();
  for (const key of [
    "constructor",
    "toString",
    "valueOf",
    "hasOwnProperty",
    "isPrototypeOf",
    "__proto__",
  ]) {
    assert.equal(apply(adImage(), "fillMode", key), null, `fillMode ${key}`);
    assert.equal(apply(adPlainText(), "fontWeight", key), null, `fontWeight ${key}`);
    assert.equal(
      apply(fixedText, "verticalAlignment", key, fixedScene),
      null,
      `verticalAlignment ${key}`,
    );
  }
});

it("RULING A29: a commit against a LOCKED node records NOTHING in the panel either", () => {
  // The adapter has always refused a locked node (§4, proven above). What it
  // could not do is stop the PANEL from recording that refused write: the
  // radius control asked only "would this text write?", never "did it LAND?",
  // so on a locked node a commit re-stated all five boxes and their `committed`
  // snapshot over a document nothing had touched. Two clicks reproduced it —
  // select the image, click the header lock, type 24 into All — and only
  // reselecting the node cleared the lie, because a successful write never
  // triggers a reload or a remount either (§4 / the AD3.2 keying rule) and the
  // panel had no other way back to the document. It also re-opened A27's trap
  // behind the lock: after unlocking, re-typing 24 compared equal to
  // `committed` and committed nothing. Under AD4.R the boxes derive, so there
  // is no snapshot to strand.
  const source = readFileSync(
    join(
      dirname(fileURLToPath(import.meta.url)),
      "../../chat-shell/components/inspector-primitives.tsx",
    ),
    "utf8",
  );
  const body = source.slice(
    source.indexOf("export function RadiusControls"),
    source.indexOf("type HsvColor"),
  );
  assert.ok(body.includes("locked = false,"), "RadiusControls must take the lock as data");
  const commitAll = body.indexOf("const commitAll");
  const cornerCommit = body.indexOf("const commit = () => {");
  assert.ok(commitAll >= 0 && cornerCommit > commitAll, "both commit paths not found");
  assert.ok(
    body.slice(commitAll, commitAll + 400).includes("if (locked)"),
    "the all-corners commit must record nothing on a locked node",
  );
  assert.ok(
    body.slice(cornerCommit, cornerCommit + 400).includes("if (locked) return;"),
    "a corner commit must record nothing on a locked node either — same trap",
  );

  // And the wiring: the lock that rides down is the HEADER controller's live
  // one, not a schema's mount-time seed. A successful write does not remount the
  // panel (§4 / the AD3.2 keying rule), so a seeded copy would still read
  // `false` one click after the user locked the node.
  const inspector = readFileSync(
    join(
      dirname(fileURLToPath(import.meta.url)),
      "../../chat-shell/components/image-inspector.tsx",
    ),
    "utf8",
  );
  assert.ok(
    inspector.includes("locked: headerController.state.locked,"),
    "the ad schemas must receive the header controller's LIVE lock",
  );
  assert.ok(
    inspector.includes("<RadiusControls locked={locked}"),
    "the image schema must pass that lock to RadiusControls",
  );

  // AD4.B step 1 (controller-authorized pin rewrite, recorded in the lane's
  // step-1 report): this pin used to read
  // `locked: dummySelection ? false : headerController.state.locked,`. The
  // four dummy schemas were hard-wired to `false` with no `onLockToggle`
  // because they had no controller to write through; binding them (AD4.B) gave
  // them one, so the ternary would now be the panel LYING about a locked node
  // to exactly the four schemas whose Layout rows the lock gates. The rewrite
  // is a strict superset of the old pin: the live-lock line is pinned
  // positively above, and the retired branch is pinned negatively here so it
  // cannot come back at either site (the schema object or the header).
  assert.ok(
    !inspector.includes("dummySelection ? false"),
    "no schema may be told its node is unlocked when the document says otherwise",
  );
  assert.ok(
    inspector.includes("locked={headerController.state.locked}"),
    "the header's own lock button must read the same live lock for every schema",
  );
});

/**
 * Source text with COMMENTS removed, so a prose MENTION of a hook is never
 * mistaken for a hook CALL. Block comments first, then line comments (the `:`
 * lookbehind spares a `https://`). Only used by the pin below, whose own
 * non-vacuity assertions prove the strip did not eat the code.
 */
function sourceWithoutComments(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, "\n")
    .replace(/(^|[^:])\/\/.*$/gm, "$1");
}

it("RULING L20: the four bound ad schemas hold NO state of their own", () => {
  // WHAT THIS GUARDS. AD4.R's state model says a bound control owns nothing:
  // every value it shows is a live projection of the document (`state.x` /
  // `values`), and every commit is a dispatch. The mechanical way that rule
  // dies is a control acquiring a LOCAL MIRROR or a MOUNT SEED —
  // `const [local, setLocal] = useState(props.value)` and then `value={local}`
  // — after which the panel shows the mirror and the document's answer arrives
  // a render late, or never (a successful write does not remount the panel:
  // §4 / the AD3.2 keying rule). Both shapes need a React state hook FIRST, so
  // the cheap pin is: no `useState`, no `useRef`, in the two files carrying the
  // four schemas AD4.B bound. Their ~40 rows had no guard of their own — the
  // rest of the AD4.R net reads `image-inspector.tsx` (`scene-hydrate.test.ts`,
  // `scene-image-ai.test.ts`) and `inspector-primitives.tsx` (A26/A27/A28/A31
  // above) only.
  //
  // COMMENTS ARE STRIPPED FIRST, and that is not a convenience: the file's own
  // prose names the hook it RETIRED ("`DummySection`'s own `useState(true)` …
  // onto the controller"). A raw string count would fail on the sentence that
  // documents the fix, so this pin reads the CODE and leaves the record alone.
  //
  // HOW TO AMEND THIS, LEGITIMATELY. Not every hook here would be a mirror: a
  // genuinely UI-ONLY piece of state the document does not own is allowed by
  // AD4.R — the lane's own precedent is `openSections`, which
  // `composeInspectorState` explicitly excludes from the live merge. Adding one
  // is a CONSCIOUS amendment, in this order: put it on the controller if the
  // panel already states that kind of thing there (which is exactly what AD4.B
  // step 1 did with the section open/closed state), and only if it truly cannot
  // live there, narrow this pin to name the ONE allowed site and say — citing
  // AD4.R — which document value it is not mirroring. Deleting the pin, or
  // widening it to "a useState here is fine", is the edit that must not happen.
  const here = dirname(fileURLToPath(import.meta.url));
  const files = [
    {
      // The four bound schemas themselves.
      anchors: ["export function AdDummyInspector", "onCommitValue"],
      name: "ad-dummy-inspectors.tsx",
      reactImport: 'import type { ReactNode } from "react";',
    },
    {
      // The palette/colour-row seam those schemas share (AD4.B step 3's move).
      anchors: ["export function useAdColorRow"],
      name: "inspector-color-row.ts",
      reactImport: 'import { createContext, useContext } from "react";',
    },
  ];
  for (const file of files) {
    const raw = readFileSync(
      join(here, "../../chat-shell/components/", file.name),
      "utf8",
    );
    const code = sourceWithoutComments(raw);
    // Non-vacuity: a broken strip that returned "" would satisfy every
    // `includes` below for the wrong reason.
    for (const anchor of file.anchors) {
      assert.ok(code.includes(anchor), `${file.name}: strip ate ${anchor}`);
    }
    for (const hook of ["useState", "useRef"]) {
      assert.equal(
        code.includes(hook),
        false,
        `${file.name} must hold no ${hook}: a bound row showing a local mirror or a mount seed would need one first (AD4.R — see this test's comment before adding UI-only state)`,
      );
    }
    // The other door, closed: a state hook has to be IMPORTED before it can be
    // called, so the file's single react import is pinned verbatim too.
    assert.equal(
      raw.split('from "react"').length - 1,
      1,
      `${file.name} must import from react exactly once`,
    );
    assert.ok(
      raw.includes(file.reactImport),
      `${file.name}'s react import must stay ${file.reactImport}`,
    );
  }
});

it("RULING A29: after a single-corner commit the `all` box re-derives — hydrate's own rule", () => {
  // `all` is not a stored field in the SCENE lane: hydration derives it from the
  // four corners, "the uniform value, or empty when the corners differ". So a
  // corner commit changes what `all` must read, and leaving it made the box
  // state a number the document does not have — then the dirty check swallowed
  // the very edit that would have put it right (type 5 into All to restore a
  // uniform 5: `draft.all === committed.all`, no commit at all), leaving only
  // the scan button, which applies whatever stale number the box is showing.
  //
  // The RULE is hydrate's and is asserted there, on the real document: a node at
  // {9,5,5,5} states `all: ""`.
  const { node } = withNodeField("rect_accent_bar", "corner", {
    bottom_left: 5,
    bottom_right: 5,
    top_left: 9,
    top_right: 5,
  });
  assert.equal(hydrateSceneInspectorState(node, SCENE).radius?.all, "");
  assert.equal(hydrateSceneInspectorState(adRect(), SCENE).radius?.all, "5");

  // AD4.R Task 7 (plan
  // `docs/superpowers/plans/2026-08-22-ad-inspector-mvp-state-model.md`,
  // §"Rulings superseded") retired the component MIRROR that used to reproduce
  // that rule locally (`uniformRadius` over the four committed corners). The
  // rule itself is untouched and is asserted above, on the real document —
  // what changed is who answers it. The scene lane's boxes are now projections
  // of the live `values` prop, so the derived `all` arrives from hydrate in the
  // same batch as the corner that moved: a mirror cannot lag it, because there
  // is no mirror.
  //
  // The WEB lane's `all` is its OWN Tailwind class (`rounded-[Npx]`), parsed
  // independently of the four corner classes (`adapter/hydrate.ts:259-266`), so
  // deriving there would erase a real class from the panel — the two lanes'
  // `all` are different facts, and that split is why the web lane keeps its
  // mount-seeded model.
  const source = readFileSync(
    join(
      dirname(fileURLToPath(import.meta.url)),
      "../../chat-shell/components/inspector-primitives.tsx",
    ),
    "utf8",
  );
  const cornerCommit = source.slice(
    source.indexOf("const commit = () => {"),
    source.indexOf("return (", source.indexOf("const commit = () => {")),
  );
  // The WEB lane's corner commit, unchanged: the raw text, and `all` keeps what
  // it had.
  assert.ok(
    cornerCommit.includes("committed: { ...current.committed, [corner]: typed },"),
    "the web lane must store the RAW text and leave `all` exactly as it was",
  );
  // The SCENE lane carries NO mirror. Pinned positively AND negatively, so that
  // re-introducing any of the retired ones — not merely the one deleted here —
  // fails loudly.
  const sceneArm = source.slice(
    source.indexOf("const sceneCommit = (corner: RadiusCorner) => {"),
    source.indexOf("return (", source.indexOf("const sceneCommit")),
  );
  assert.ok(sceneArm.length > 0, "the scene lane's commit not found");
  assert.ok(
    sceneArm.includes("fieldCommit("),
    "the scene lane must commit through the shared pure dirty check",
  );
  for (const mirror of ["uniformRadius(", "radiusCommitText(", "committed", "setRadius("]) {
    assert.ok(
      !sceneArm.includes(mirror),
      `the scene lane must carry no post-commit mirror — found ${mirror}`,
    );
  }

  // ── §4 / A29 and A26, FOR THE SCENE LANE ────────────────────────────────────
  // Both rulings' component halves are asserted elsewhere against `commitAll` /
  // `commit` / `applyAll` — the three functions the scene lane no longer calls.
  // Those guards are correct and stay untouched, but they leave this lane's
  // lock and its one-event scan pinned by NOTHING, so both are pinned here.
  //
  // A29 (§4): a locked node refuses every write, so a commit against one must
  // skip the doomed dispatch. Pinned as the guard expression actually written,
  // not merely the word, so weakening it to a no-op still fails.
  assert.ok(
    sceneArm.includes("if (commit === null || locked) return;"),
    "the scene lane's corner commit must skip the dispatch on a locked node",
  );
  const sceneApplyAll = source.slice(
    source.indexOf("const sceneApplyAll = () => {"),
    source.indexOf("return (", source.indexOf("const sceneApplyAll")),
  );
  assert.ok(sceneApplyAll.length > 0, "the scene lane's scan handler not found");
  assert.ok(
    sceneApplyAll.includes('if (value.trim() === "" || locked) return;'),
    "the scene lane's scan must dispatch nothing on a locked node",
  );
  // A26: ONE event. Four synchronous per-corner dispatches cannot compose into
  // one document — each reads the same pre-burst node, so the fourth clobbers
  // the first three (a scan of 24 over the seeded ad's 32/32/96/32 image landed
  // 32/32/96/24: one corner moved, four undo steps). Same negative shape the
  // A26 guard uses on the web lane's `applyAll`.
  for (const corner of ["topLeft", "topRight", "bottomLeft", "bottomRight"]) {
    assert.ok(
      !sceneApplyAll.includes(corner),
      `the scene lane's scan must not fan out to ${corner} — four events cannot compose into one document`,
    );
  }
  assert.ok(
    sceneApplyAll.includes('onChange("all", value)'),
    "the scene lane's scan must dispatch the single all-corners write",
  );
  // And the draft drop is UNCONDITIONAL — before the guard, as in `sceneCommit`.
  // Otherwise a refused scan leaves the box stating a number the document does
  // not have, which is the panel-lie class this task closes.
  assert.ok(
    sceneApplyAll.indexOf("setDrafts(") <
      sceneApplyAll.indexOf('if (value.trim() === "" || locked) return;'),
    "the scene lane's scan must drop the draft before deciding whether to dispatch",
  );
});

it("RULING A31: a corner stores what the WRITE produced, so `5.0` on a uniform node keeps All at `5`", () => {
  // The last gap in the A26→A31 chain, and it was A29's own derivation that
  // opened it: `commit` stored the RAW typed text while `uniformRadius` compares
  // the four committed corners as STRINGS. So typing `5.0` into one corner of a
  // uniformly-5 node wrote a correctly uniform document — `radiusCommit`
  // canonicalizes on the way out — while the All box saw `"5.0" !== "5"` and
  // blanked. Panel-only and self-healing on reselect, but the same class.
  //
  // Link 1: the two now speak one spelling, which is hydrate's own.
  assert.equal(radiusCommitText("5.0"), "5");
  assert.equal(radiusCommitText("007"), "7");
  assert.equal(radiusCommitText(" 5 "), "5");
  // Link 2: so the document really is untouched by that commit — it already
  // holds 5 in every corner, and `sameCorner` says so.
  assert.equal(
    apply(adRect(), "radius.topLeft", "5.0"),
    null,
    "`5.0` over a stored 5 writes nothing",
  );
  // Link 3 — AD4.R Task 7 (plan
  // `docs/superpowers/plans/2026-08-22-ad-inspector-mvp-state-model.md`,
  // §"Rulings superseded"). A31's fix was to store the canonical text the WRITE
  // produced, so the component's own string comparison of the four corners
  // would keep agreeing with hydrate's. Task 7 removed the disagreement's only
  // possible surface instead: the scene lane stores NO typed text at all, so
  // there is nothing left to spell differently from the document. Both halves
  // of the mismatch are gone — the stored copy AND the local re-derivation.
  //
  // Links 1 and 2 above are the adapter's, and stand unchanged: they are why a
  // `5.0` commit is honestly no write, which is what the panel now simply
  // displays rather than has to reproduce.
  const source = readFileSync(
    join(
      dirname(fileURLToPath(import.meta.url)),
      "../../chat-shell/components/inspector-primitives.tsx",
    ),
    "utf8",
  );
  const body = source.slice(
    source.indexOf("export function RadiusControls"),
    source.indexOf("type HsvColor"),
  );
  assert.ok(body.length > 0, "RadiusControls not found in inspector-primitives.tsx");
  assert.ok(
    !body.includes("radiusCommitText"),
    "the scene lane must not re-acquire a canonicalizing mirror — hydrate owns the spelling",
  );
  assert.ok(
    !body.includes("uniformRadius"),
    "the scene lane must not re-acquire a local `all` derivation — hydrate owns it",
  );
  // The WEB lane's corner commit still stores the raw typed text against its own
  // snapshot, which is A27 as ratified and is not this ruling's to move.
  const cornerCommit = source.slice(
    source.indexOf("const commit = () => {"),
    source.indexOf("return (", source.indexOf("const commit = () => {")),
  );
  assert.ok(
    cornerCommit.includes("if (typed === radius.committed[corner]) return;") &&
      cornerCommit.includes("committed: { ...current.committed, [corner]: typed },"),
    "the web lane keeps its own text against its own snapshot",
  );
});

it("RULING A28: a FRACTIONAL all-commit mirrors both halves, so the re-type after it still writes", () => {
  // The last known instance of the panel-lie class, browser-proven: a scan of
  // 12.5 wrote all four corners (v74) while the boxes still read 24.5/32/96/32,
  // because the mirror asked the dummy's INTEGER regex (`NUMERIC_RADIUS`) while
  // the write asked the adapter's finite-positive rule. `committed` did not
  // move either, so every re-type of one of those numbers compared equal and
  // was swallowed — the A27 trap, behind the decimal point.
  const source = readFileSync(
    join(
      dirname(fileURLToPath(import.meta.url)),
      "../../chat-shell/components/inspector-primitives.tsx",
    ),
    "utf8",
  );
  const body = source.slice(
    source.indexOf("export function RadiusControls"),
    source.indexOf("type HsvColor"),
  );
  // AD4.R Task 7 (plan
  // `docs/superpowers/plans/2026-08-22-ad-inspector-mvp-state-model.md`,
  // §"Rulings superseded") deleted the SCENE arm this ruling split off. A28
  // existed because ONE post-commit mirror could not serve two lanes: the web
  // lane's integer `clearsCorners` question refused the very values (12.5) the
  // scene lane's write accepted, so the scene boxes kept the old numbers and
  // `committed` did not move — A27's trap, behind the decimal point. The scene
  // lane now has no mirror to split: its boxes project the live document, which
  // moves in the same batch as the write, at the write's own spelling.
  //
  // So the ruling's surviving obligation is the WEB half — and it matters MORE
  // now, because it is what pins the branch this task left untouched.
  const webStart = body.indexOf("const clearsCorners");
  // BOUNDED at `applyAll`, so this reads `commitAll`'s F2 branch only. Every
  // offset is asserted before slicing, so a rename fails here with a message
  // rather than silently testing an empty string.
  const webEnd = body.indexOf("const applyAll");
  assert.ok(webStart >= 0, "commitAll's F2 branch not found");
  assert.ok(webEnd > webStart, "applyAll not found after commitAll");
  const webBranch = body.slice(webStart, webEnd);

  // The scene lane carries no mirror at all — the strongest form of "it does not
  // use the wrong rule", and the one that cannot rot as the rules change.
  assert.ok(
    !body.includes("const restate"),
    "the retired post-commit restate must not come back",
  );

  // The WEB lane's `clearsCorners` is untouched — same predicate, same argument.
  assert.ok(
    webBranch.includes("NUMERIC_RADIUS.test(value.trim())") &&
      webBranch.includes("onApplyAll(value, clearsCorners)"),
    "F2's clearsCorners must still be the integer regex, passed to onApplyAll",
  );
  assert.ok(
    !webBranch.includes("radiusCommitText"),
    "the web lane must not adopt the scene lane's rule",
  );

  // Why the split was needed at all, stated as the one-line fact it is: the
  // gate the mirror used to share with F2 refuses the value the write accepts.
  // (`radiusCommit`/`radiusCommitText`'s own vocabulary is proven in
  // `scene-hydrate.test.ts`; this is only the disagreement that caused it.)
  assert.equal(/^\d+$/.test("12.5"), false, "the old shared gate refused 12.5");
  assert.ok(apply(adImage(), "radius.all", "12.5"), "the write accepts 12.5");

  // And the adapter half of the repro: the document at all-corners-12.5, a
  // re-type of `image_hero`'s pre-scan bottom-left, still a write.
  const { node, scene } = withNodeField("image_hero", "corner", {
    bottom_left: 12.5,
    bottom_right: 12.5,
    top_left: 12.5,
    top_right: 12.5,
  });
  assert.deepEqual(
    apply(node, "radius.all", "12.5", scene),
    null,
    "re-committing the value the document already holds is still not a write",
  );
  assert.deepEqual(
    apply(node, "radius.bottomLeft", "96", scene),
    updateNode("image_hero", {
      corner: set({
        bottom_left: 96,
        bottom_right: 12.5,
        top_left: 12.5,
        top_right: 12.5,
        token: null,
      }),
    }),
  );
});

// ══ AD4.A / §1.3 row 1 — Replace image (upload → the canonical pair) ═════════
//
// The upload itself is transport (`hooks/use-scene-replace-image.ts`); THIS is
// the pure half — given the node the panel is showing and the record the upload
// minted, which operations does the document get, and when is it no write at
// all. The pair and its order are the engine's own
// (`buildNodePlacementOperations`), never rebuilt here.

/** A record the upload could have minted — a NEW asset, not the harvest's. */
function uploadedRecord(
  overrides: Partial<AssetRecord> = {},
): AssetRecord {
  return {
    id: "asset_upload_new",
    kind: "raster_image",
    label: "hero-v2.png",
    source: { kind: "uploaded", filename: "hero-v2.png", uploaded_by: null },
    status: "ready",
    ...overrides,
  };
}

it("§1.3 Replace image: the pair is upsert THEN place, and the WHOLE stored placement rides forward", () => {
  // ALT-TEXT RULING (2026-08-21): step 2 shipped this row overwriting the alt
  // text with the new asset's label. Step 3 adds an Alt-text control, which
  // makes that text user-authored accessibility content — so an upload no
  // longer renames a person's description to a filename.
  const record = uploadedRecord();
  const operations = sceneImagePlacementOperations(adImage(), record);
  assert.deepEqual(operations, [
    { asset: record, kind: "upsert_asset" },
    {
      asset_id: "asset_upload_new",
      kind: "place_asset_in_node",
      node_id: "image_hero",
      placement: {
        alt_text: "Brand gradient backdrop",
        fit: "cover",
        focal_point: { x: 0.5, y: 0.42 },
        preserve_transparency: false,
      },
    },
  ]);
});

it("§1.3 Replace image: an image with NO placement gets the alt text and nothing invented", () => {
  const scene = clone(SCENE);
  const node = scene.nodes.image_hero;
  assert.ok(node, "fixture node image_hero missing");
  delete node.asset_placement;
  const operations = sceneImagePlacementOperations(node, uploadedRecord());
  assert.ok(operations, "a placement-less image still takes a replacement");
  assert.deepEqual(operations[1], {
    asset_id: "asset_upload_new",
    kind: "place_asset_in_node",
    node_id: "image_hero",
    // NOT upstream's `fit: "cover"` default: an absent fit IS `contain` here
    // (`effectiveImageFit`), so minting one would change the picture.
    placement: { alt_text: "hero-v2.png" },
  });
});

it("§1.3 Replace image: the SAME asset with the same placement is not a write", () => {
  // The design API deduplicates by content, so re-picking the file the node
  // already carries mints the record it already has.
  assert.equal(
    sceneImagePlacementOperations(
      adImage(),
      uploadedRecord({
        id: "asset_ing_2b0928ca4f3a3c70",
        label: "Brand gradient backdrop",
      }),
    ),
    null,
  );
});

it("ALT-TEXT RULING: the same asset under a DIFFERENT label is NOT a write — a filename does not rename a description", () => {
  assert.equal(
    sceneImagePlacementOperations(
      adImage(),
      uploadedRecord({ id: "asset_ing_2b0928ca4f3a3c70", label: "renamed.jpg" }),
    ),
    null,
    "the stored description wins, so nothing about this node changed",
  );
});

it("ALT-TEXT RULING: an authored description survives a replace, a generate and an accept alike", () => {
  // One function, three flows — the whole point of the ruling. A NEW asset is
  // a real write on every path, and the description rides through each of them.
  for (const record of [
    uploadedRecord(),
    generatedRecord(),
    generatedRecord({ id: "asset_gen_edited", label: "make the sky warmer" }),
  ]) {
    const operations = sceneImagePlacementOperations(adImage(), record);
    assert.ok(operations, `a new asset ${record.id} is a write`);
    assert.equal(
      (operations[1] as { placement: AssetPlacement }).placement.alt_text,
      "Brand gradient backdrop",
      `the authored description survived ${record.id}`,
    );
  }
});

it("ALT-TEXT RULING: an image with NO description takes the record's label — the other direction", () => {
  const scene = clone(SCENE);
  const node = scene.nodes.image_hero;
  assert.ok(node, "fixture node image_hero missing");
  delete node.asset_placement?.alt_text;
  for (const [record, expected] of [
    [uploadedRecord(), "hero-v2.png"],
    [generatedRecord(), "a calm clinic reception, soft light"],
  ] as const) {
    const operations = sceneImagePlacementOperations(node, record);
    assert.ok(operations, `a new asset ${record.id} is a write`);
    assert.equal(
      (operations[1] as { placement: AssetPlacement }).placement.alt_text,
      expected,
    );
  }
});

it("§1.3 Replace image: a LOCKED image refuses (§4), and so does a non-image node", () => {
  const scene = clone(SCENE);
  const locked = scene.nodes.image_hero;
  assert.ok(locked, "fixture node image_hero missing");
  locked.locked = true;
  assert.equal(sceneImagePlacementOperations(locked, uploadedRecord()), null);
  assert.equal(sceneImageReplacementTarget(locked), null);
  assert.equal(sceneImagePlacementOperations(adTokenText(), uploadedRecord()), null);
  assert.equal(sceneImageReplacementTarget(adTokenText()), null);
  // The unlocked harvested image is the positive control for both.
  assert.ok(sceneImageReplacementTarget(adImage()), "an unlocked image accepts one");
});

it("FIX 4 / A32: the produced placement differs from the stored one in the ALT TEXT and nothing else", () => {
  // This is the invariant the reduced no-op guard rests on: the placement is
  // built as `{...stored, alt_text}`, so alt text is the only field that CAN
  // differ, and a guard comparing the other three would have three branches
  // that can never be false. A caller that ever builds it another way must
  // widen `sameAltText` again — which is why the invariant is pinned here, for
  // the one function all three placement flows now share.
  const stored = heroPlacement();
  const operations = sceneImagePlacementOperations(adImage(), uploadedRecord());
  assert.ok(operations, "the harvested image takes a replacement");
  const { placement } = operations[1] as { placement: AssetPlacement };
  assert.deepEqual(
    { ...placement, alt_text: stored.alt_text },
    stored,
    "every field except the alt text is the stored one, verbatim",
  );
  // Under the alt-text ruling this node's description also rides forward, so
  // the produced placement IS the stored one — the guard is live only for a
  // node with no description of its own (the test above).
  assert.equal(placement.alt_text, stored.alt_text);
});

// ══ AD4.A / §1.3 row 2 — Alt text ═══════════════════════════════════════════
//
// The one MANUAL row of the AI suite: upstream has no alt-text generator, so
// this is an ordinary `asset_placement` patch through the ordinary property
// seam, and its only subtlety is what "unchanged" means — the field displays
// `asset_placement.alt_text ?? ImageNode.alt ?? ""`, so the no-change guard has
// to ask the same question hydration answers.

it("§1.3 Alt text: a new description patches `asset_placement.alt_text` and nothing else", () => {
  assert.deepEqual(
    apply(adImage(), "altText", "Clinic reception at golden hour"),
    updateNode("image_hero", {
      asset_placement: set({
        ...heroPlacement(),
        alt_text: "Clinic reception at golden hour",
      }),
    }),
  );
});

it("§1.3 Alt text: re-committing the description the node already has is NOT a write", () => {
  assert.equal(apply(adImage(), "altText", "Brand gradient backdrop"), null);
});

it("§1.3 Alt text: CLEARING a description is a real write — an empty alt is a decorative image", () => {
  const operations = apply(adImage(), "altText", "");
  assert.deepEqual(
    operations,
    updateNode("image_hero", {
      asset_placement: set({ ...heroPlacement(), alt_text: "" }),
    }),
  );
});

it("§1.3 Alt text: with no stored alt_text the node's OWN `alt` is what counts as unchanged", () => {
  // The field displays `ImageNode.alt` when the placement carries none
  // (upstream's `placement.alt_text ?? node.kind.alt ?? ""`), so committing
  // that same text must not mint a document version that states nothing new.
  const scene = clone(SCENE);
  const node = scene.nodes.image_hero;
  assert.ok(node, "fixture node image_hero missing");
  delete node.asset_placement?.alt_text;
  assert.equal(
    apply(node, "altText", "Brand gradient backdrop", scene),
    null,
    "the node's own alt is what the box was showing",
  );
  const changed = apply(node, "altText", "Something else", scene);
  assert.ok(changed, "a different description IS a change");
});

it("§1.3 Alt text: an image with NO placement mints one, exactly as the Mode row does", () => {
  const scene = clone(SCENE);
  const node = scene.nodes.image_hero;
  assert.ok(node, "fixture node image_hero missing");
  delete node.asset_placement;
  assert.deepEqual(
    apply(node, "altText", "A new description", scene),
    updateNode("image_hero", {
      asset_placement: set({ alt_text: "A new description" }),
    }),
  );
});

it("§1.3 Alt text: a NON-image node writes nothing — the row is image-only, like Mode", () => {
  assert.equal(apply(adTokenText(), "altText", "anything"), null);
  assert.equal(apply(adRect(), "altText", "anything"), null);
  assert.equal(apply(adAutoLayout(), "altText", "anything"), null);
});

it("§1.3 Alt text: a LOCKED image writes nothing (§4), and a non-string value is refused", () => {
  const { node } = withNodeField("image_hero", "locked", true);
  assert.equal(apply(node, "altText", "anything"), null);
  assert.equal(apply(adImage(), "altText", 42), null);
  assert.equal(apply(adImage(), "altText", null), null);
});

// ══ AD4.A / §1.3 row 2 — the AI suite's document change ══════════════════════
//
// Generate and candidate-Accept apply the SAME canonical pair as the upload
// (the plan's own words), through the same engine builder — the only
// difference is which alt text the placement carries, and that difference is
// the whole reason there are two functions rather than one.

/** A record `/assets/generate` could have minted. */
function generatedRecord(overrides: Partial<AssetRecord> = {}): AssetRecord {
  return {
    id: "asset_gen_new",
    kind: "raster_image",
    label: "a calm clinic reception, soft light",
    source: { kind: "generated", model: "image-gen-v1", request_id: null },
    status: "ready",
    ...overrides,
  };
}

it("§1.3 Generate: the pair is upsert THEN place, into the SAME node", () => {
  const record = generatedRecord();
  const operations = sceneImagePlacementOperations(adImage(), record);
  assert.ok(operations, "the harvested image takes a generated picture");
  assert.deepEqual(
    operations.map((operation) => operation.kind),
    ["upsert_asset", "place_asset_in_node"],
    "the order is load-bearing: place_asset_in_node looks the record up first",
  );
  assert.deepEqual(operations[0], { asset: record, kind: "upsert_asset" });
  assert.equal(
    (operations[1] as { node_id: string }).node_id,
    "image_hero",
    "a regenerate replaces the picture, never the node",
  );
});

it("§1.3 Generate: the stored placement rides forward INCLUDING the user's alt text", () => {
  // Upstream's own behaviour (`currentPlacement` carries `alt_text` forward and
  // only `withDefaultAlt` fills a missing one), and since the 2026-08-21 ruling
  // it is every placement flow's behaviour on this lane.
  const operations = sceneImagePlacementOperations(adImage(), generatedRecord());
  assert.ok(operations, "the harvested image takes a generated picture");
  assert.deepEqual(
    (operations[1] as { placement: AssetPlacement }).placement,
    heroPlacement(),
    "fit, focal point, transparency AND alt text are the stored ones",
  );
});

it("§1.3 Generate: an image with NO alt text falls back to the asset's own label", () => {
  const scene = clone(SCENE);
  const node = scene.nodes.image_hero;
  assert.ok(node, "fixture node image_hero missing");
  delete node.asset_placement?.alt_text;
  const operations = sceneImagePlacementOperations(node, generatedRecord());
  assert.ok(operations, "a description-less image still takes a generated picture");
  assert.equal(
    (operations[1] as { placement: AssetPlacement }).placement.alt_text,
    "a calm clinic reception, soft light",
  );
});

it("§1.3 Generate: an image with NO placement mints nothing beyond the alt text", () => {
  // Not upstream's `currentPlacement` defaults (`fit: "cover"`, focal 0.5/0.5):
  // an absent fit IS `contain` on this lane (`effectiveImageFit`), so minting
  // `cover` would silently change the picture the user is looking at.
  const scene = clone(SCENE);
  const node = scene.nodes.image_hero;
  assert.ok(node, "fixture node image_hero missing");
  delete node.asset_placement;
  const operations = sceneImagePlacementOperations(node, generatedRecord());
  assert.ok(operations, "a placement-less image still takes a generated picture");
  assert.deepEqual((operations[1] as { placement: AssetPlacement }).placement, {
    alt_text: "a calm clinic reception, soft light",
  });
});

it("§1.3 Generate: the SAME asset the node already carries is NOT a write", () => {
  // Reachable in one gesture: `POST /assets/generate` keys a generation cache
  // on the prompt + model + size, so re-running an identical prompt returns
  // the very asset the node is already showing (`deduplicated: true`).
  assert.equal(
    sceneImagePlacementOperations(
      adImage(),
      generatedRecord({ id: "asset_ing_2b0928ca4f3a3c70" }),
    ),
    null,
  );
});

it("§4: a LOCKED image refuses a generated picture, and so does a non-image node", () => {
  const { node } = withNodeField("image_hero", "locked", true);
  assert.equal(sceneImagePlacementOperations(node, generatedRecord()), null);
  assert.equal(sceneImagePlacementOperations(adTokenText(), generatedRecord()), null);
});

it("A32: the generated placement differs from the stored one in the ALT TEXT and nothing else", () => {
  // The same invariant `sameAltText` rests on, re-pinned for the second caller
  // the guard's own comment names. `place_asset_in_node` REPLACES the whole
  // placement, so if this ever stops holding the no-op guard must widen with
  // it — and this test is what fails when it does.
  const stored = heroPlacement();
  const operations = sceneImagePlacementOperations(adImage(), generatedRecord());
  assert.ok(operations, "the harvested image takes a generated picture");
  const { placement } = operations[1] as { placement: AssetPlacement };
  assert.deepEqual({ ...placement, alt_text: stored.alt_text }, stored);
});

it("canonical spacing overrides one binding and materializes only the effective padding siblings", () => {
  const scene = clone(SCENE);
  const node = scene.nodes.auto_row_copy;
  node.layout = { ...node.layout!, gap:72, gap_token:"space.8", padding:[72,72,72,72], padding_token:"space.8" };
  const effective = { ...node, layout: { ...node.layout, gap:32, padding:[32,32,32,32] as [number,number,number,number] } };
  const operation = sceneChangeToOperation({ property:"padding.top", value:"40", selectionId:node.id }, node, scene, null, null, effective);
  assert.deepEqual(operation, updateNodeLayout(node, { ...node.layout, padding:[40,32,32,32], padding_token:undefined }));
  const state = hydrateSceneInspectorState(node, scene, null, effective);
  assert.equal(state.gap,"32");
  assert.deepEqual(state.padding,{ top:"32", right:"32", bottom:"32", left:"32" });
  assert.equal(sceneChangeToOperation({ property:"padding.top", value:"40", selectionId:node.id }, node, scene, null, null, null), null);
  assert.deepEqual(node.layout.padding,[72,72,72,72]);
  if (operation?.kind !== "update_node" || operation.patch.layout.kind !== "set") throw new Error("expected layout");
  const edited = { ...node, layout:operation.patch.layout.value };
  const second = sceneChangeToOperation({ property:"padding.left", value:"48", selectionId:node.id }, edited, scene, null, null, edited);
  assert.deepEqual(second, updateNodeLayout(edited, { ...edited.layout!, padding:[40,32,32,48] }));
});
