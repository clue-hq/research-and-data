import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import type {
  Node,
  NodeId,
  Operation,
  Scene,
  TextNode,
  TextSpan,
} from "../engine/scene/contracts";
import type { WorkspaceViewport } from "../engine/scene/workspaceViewport";
import { AD_PAGE_ID, HARVESTED_AD_PAGE } from "./__fixtures__/scene-nodes";
import { sceneArtboardModel } from "./scene-canvas-view";
import {
  MIN_TEXT_EDIT_SIZE_PX,
  SCENE_TEXT_EDIT_INTENT,
  SCENE_TEXT_STYLE_INTENT,
  domFontFamilyStack,
  sceneDoubleClickEffect,
  sceneTextEditModel,
  textEditCommitOperations,
  textEditSurfaceHeight,
} from "./scene-text-edit";

/**
 * Rung B (rich-text plan, 2026-08-24): the pure decisions behind double-click
 * inline text editing — what a double-click resolves to, what geometry and
 * style the DOM overlay is drawn with, and what a committed draft writes.
 *
 * Every case runs against AD2.2's harvested bytes (the seeded
 * `doc_ad22linkedinsquare00000000001`), never a hand-written shape. The
 * harvest carries `computed: null` on every node — the honest at-rest state —
 * so a case that needs a laid-out box injects the geometry the engine's
 * relayout would produce, on a CLONE, exactly as the AD4.C suite does.
 */

function clone(scene: Scene): Scene {
  return JSON.parse(JSON.stringify(scene)) as Scene;
}

/**
 * Plan 3 (item E): the one shape the harvest lacks — a BUTTON, an auto-layout
 * whose only child is text — made by moving the real headline into the real
 * copy row (AD2.4's one-field-edit technique), never by inventing a node.
 * `auto_row_copy` becomes a button: its only child is `text_headline`.
 */
function sceneWithButton(): Scene {
  const next = clone(HARVESTED_AD_PAGE);
  for (const node of Object.values(next.nodes)) {
    node.children = node.children.filter((id) => id !== "text_headline");
  }
  for (const page of Object.values(next.pages)) {
    page.children = page.children.filter((id) => id !== "text_headline");
  }
  next.nodes.auto_row_copy.children = ["text_headline"];
  return next;
}

/** `text_proof_stat`'s laid-out box: a plain (non-token) text node, so its
 * descriptor fill resolves with no brand kit loaded. */
const STAT_BOX = { x: 780, y: 149, width: 256, height: 36 };

function sceneWithLaidOutStat(): Scene {
  const scene = clone(HARVESTED_AD_PAGE);
  scene.nodes.text_proof_stat.computed = {
    layout_bounds: { ...STAT_BOX },
    render_bounds: { ...STAT_BOX },
  };
  return scene;
}

function artboardFor(scene: Scene) {
  const artboard = sceneArtboardModel(scene, AD_PAGE_ID);
  assert.ok(artboard);
  return artboard;
}

const UNIT_VIEWPORT: WorkspaceViewport = { zoom: 1, pan: { x: 0, y: 0 } };

function modelFor(
  scene: Scene,
  {
    editingNodeId = "text_proof_stat" as NodeId | null,
    viewport = UNIT_VIEWPORT,
  } = {},
) {
  return sceneTextEditModel({
    artboard: artboardFor(scene),
    editingNodeId,
    pageId: AD_PAGE_ID,
    scene,
    viewport,
  });
}

/* -------------------------------------------------------------------------
 * The double-click itself — drill one level, then the caret
 *
 * Selection model v2 (founder rulings 2026-09-04) replaces Rung B's drill-OUT
 * to the top-level container and Plan 3's button shortcut: the double-click
 * now drills one representable level TOWARD the pointer, and opens the caret
 * only once the text itself is what is selected. The engine's hit stack
 * (outer→inner) is the input, so these cases name real ancestry from the
 * harvest — `text_proof_stat` in `group_proof` in `auto_row_copy` in
 * `frame_ad_root`.
 * ---------------------------------------------------------------------- */

const stackToHeadline = ["frame_ad_root", "auto_row_copy", "text_headline"];
const stackToStat = [
  "frame_ad_root",
  "auto_row_copy",
  "group_proof",
  "text_proof_stat",
];

test("R2: a double-click on a selected text node opens an edit session on it", () => {
  assert.deepEqual(
    sceneDoubleClickEffect({
      gestureDisabled: false,
      stack: stackToStat,
      pageId: AD_PAGE_ID,
      scene: HARVESTED_AD_PAGE,
      selectedNodeId: "text_proof_stat",
    }),
    { kind: "edit", nodeId: "text_proof_stat" },
  );
});

test("R2: with an ancestor selected, a double-click drills one level and opens no caret", () => {
  assert.deepEqual(
    sceneDoubleClickEffect({
      gestureDisabled: false,
      stack: stackToStat,
      pageId: AD_PAGE_ID,
      scene: HARVESTED_AD_PAGE,
      selectedNodeId: "auto_row_copy",
    }),
    { kind: "select", nodeId: "group_proof" },
  );
  assert.deepEqual(
    sceneDoubleClickEffect({
      gestureDisabled: false,
      stack: stackToStat,
      pageId: AD_PAGE_ID,
      scene: HARVESTED_AD_PAGE,
      selectedNodeId: "group_proof",
    }),
    { kind: "select", nodeId: "text_proof_stat" },
  );
});

test("R2: the button — plate selected drills to the label; label selected opens the caret", () => {
  const scene = sceneWithButton();
  assert.deepEqual(
    sceneDoubleClickEffect({
      gestureDisabled: false,
      stack: stackToHeadline,
      pageId: AD_PAGE_ID,
      scene,
      selectedNodeId: "auto_row_copy",
    }),
    { kind: "select", nodeId: "text_headline" },
  );
  assert.deepEqual(
    sceneDoubleClickEffect({
      gestureDisabled: false,
      stack: stackToHeadline,
      pageId: AD_PAGE_ID,
      scene,
      selectedNodeId: "text_headline",
    }),
    { kind: "edit", nodeId: "text_headline" },
  );
});

test("the caret's refusals hold: a locked node decides nothing, a locked run says so", () => {
  // Gate G-H (task 4, scene live-streaming rung A): the run's refusal is its
  // own kind rather than `none`, so the host can put the lock's sentence in
  // front of the human instead of leaving a caret that mysteriously never
  // appears.
  const scene = sceneWithButton();
  scene.nodes.text_headline.locked = true;
  assert.deepEqual(
    sceneDoubleClickEffect({
      gestureDisabled: false,
      stack: stackToHeadline,
      pageId: AD_PAGE_ID,
      scene,
      selectedNodeId: "text_headline",
    }),
    { kind: "none" },
  );
  assert.deepEqual(
    sceneDoubleClickEffect({
      gestureDisabled: true,
      stack: stackToHeadline,
      pageId: AD_PAGE_ID,
      scene: sceneWithButton(),
      selectedNodeId: "text_headline",
    }),
    { kind: "locked" },
  );
});

test("a LOCKED node under an agent run still reports the node lock, not the run", () => {
  // The node's own lock is a document fact and outranks the transient run: the
  // caret would not open even after the agent finishes, so promising otherwise
  // would be the wrong sentence.
  const scene = clone(HARVESTED_AD_PAGE);
  scene.nodes.text_headline.locked = true;
  assert.deepEqual(
    sceneDoubleClickEffect({
      gestureDisabled: true,
      stack: stackToHeadline,
      pageId: AD_PAGE_ID,
      scene,
      selectedNodeId: "text_headline",
    }),
    { kind: "none" },
  );
});

test("selection-for-inspection survives the lock: a locked run still DRILLS", () => {
  // The whole of what the lock forbids is CHANGING the document. Drilling is a
  // selection, not a write — looking at what is inside a container to inspect
  // it stays live — so it must resolve exactly as it does with the lock off.
  // Only the caret above is gated.
  const drill = {
    stack: stackToStat,
    pageId: AD_PAGE_ID,
    scene: HARVESTED_AD_PAGE,
    selectedNodeId: "auto_row_copy",
  };
  const unlocked = sceneDoubleClickEffect({ ...drill, gestureDisabled: false });
  assert.deepEqual(unlocked, { kind: "select", nodeId: "group_proof" });
  assert.deepEqual(
    sceneDoubleClickEffect({ ...drill, gestureDisabled: true }),
    unlocked,
  );
});

test("Ruling C-9 does not apply: a layout-MANAGED text node still opens a session", () => {
  // `text_headline` is a child of the `auto_row_copy` row — solver-owned. A
  // content edit re-solves the layout, so no freeze-on-grab fires for it.
  assert.deepEqual(
    sceneDoubleClickEffect({
      gestureDisabled: false,
      stack: stackToHeadline,
      pageId: AD_PAGE_ID,
      scene: HARVESTED_AD_PAGE,
      selectedNodeId: "text_headline",
    }),
    { kind: "edit", nodeId: "text_headline" },
  );
});

test("a double-click whose selection is neither the hit nor its ancestor re-selects the click target", () => {
  assert.deepEqual(
    sceneDoubleClickEffect({
      gestureDisabled: false,
      stack: stackToStat,
      pageId: AD_PAGE_ID,
      scene: HARVESTED_AD_PAGE,
      selectedNodeId: "text_headline",
    }),
    { kind: "select", nodeId: "group_proof" },
  );
});

test("a double-click on nothing, or with no scene, decides nothing", () => {
  assert.deepEqual(
    sceneDoubleClickEffect({
      gestureDisabled: false,
      stack: [],
      pageId: AD_PAGE_ID,
      scene: HARVESTED_AD_PAGE,
      selectedNodeId: "group_proof",
    }),
    { kind: "none" },
  );
  assert.deepEqual(
    sceneDoubleClickEffect({
      gestureDisabled: false,
      stack: stackToStat,
      pageId: AD_PAGE_ID,
      scene: null,
      selectedNodeId: null,
    }),
    { kind: "none" },
  );
});

/* -------------------------------------------------------------------------
 * The commit — ONE batch, or nothing at all
 * ---------------------------------------------------------------------- */

test("a changed draft commits as ONE update_node batch (one undo frame)", () => {
  const node = HARVESTED_AD_PAGE.nodes.text_proof_stat;
  const operations = textEditCommitOperations(node, "4.1x faster triage");
  assert.ok(operations);
  assert.equal(operations.length, 1);
  const [operation] = operations;
  assert.equal(operation.kind, "update_node");
  assert.equal(operation.node_id, "text_proof_stat");
  assert.deepEqual(operation.patch.kind, {
    kind: "set",
    value: { ...node.kind, content: "4.1x faster triage" },
  });
});

test("an unchanged draft writes NOTHING — a blur that typed nothing is not an edit", () => {
  const node = HARVESTED_AD_PAGE.nodes.text_proof_stat;
  assert.equal(textEditCommitOperations(node, node.kind.content as string), null);
});

test("the empty string is a legal commit — a node that says nothing is a real edit", () => {
  const operations = textEditCommitOperations(
    HARVESTED_AD_PAGE.nodes.text_proof_stat,
    "",
  );
  assert.ok(operations);
  assert.equal(operations.length, 1);
});

test("a locked node commits nothing — the write-side lock gate, restated", () => {
  const scene = clone(HARVESTED_AD_PAGE);
  scene.nodes.text_proof_stat.locked = true;
  assert.equal(textEditCommitOperations(scene.nodes.text_proof_stat, "new"), null);
});

test("a non-text node commits nothing", () => {
  assert.equal(
    textEditCommitOperations(HARVESTED_AD_PAGE.nodes.ellipse_proof_dot, "new"),
    null,
  );
});

test("D10: a node the reload took away commits nothing", () => {
  assert.equal(textEditCommitOperations(null, "new"), null);
});

test("the write says which surface it came from", () => {
  assert.equal(SCENE_TEXT_EDIT_INTENT, "canvas: text edit");
});

/* -------------------------------------------------------------------------
 * Rung C: the spans channel — the relaxed null contract
 *
 * Rung B committed on ONE question ("did the content change?"). Rung C's
 * toolbar can change a node without touching a character of it, so the question
 * becomes "did the content OR the spans change?", and both channels ride the
 * same single `update_node` batch. The rung-B cases above are unchanged and
 * still hold: a caller that passes no spans channel gets exactly rung B's
 * write.
 * ---------------------------------------------------------------------- */

/** `faster` in bold, over the harvested stat's 18 ASCII bytes. */
const BOLD_FASTER: TextSpan = { start: 5, end: 11, font_weight: 700 };

function spannedStat(): Node {
  const scene = clone(HARVESTED_AD_PAGE);
  const node = scene.nodes.text_proof_stat;
  textKind(node).spans = [BOLD_FASTER];
  return node;
}

/** The node's text kind, narrowed — every case here is about a text node. */
function textKind(node: Node): TextNode {
  assert.ok(node.kind.kind === "text");
  return node.kind;
}

/** The single `update_node` patch a committed batch carries. */
function committedKind(operations: Operation[] | null) {
  assert.ok(operations);
  assert.equal(operations.length, 1);
  const [operation] = operations;
  assert.ok(operation.kind === "update_node");
  return operation.patch.kind;
}

test("content and spans commit together, in ONE batch", () => {
  const node = HARVESTED_AD_PAGE.nodes.text_proof_stat;
  const operations = textEditCommitOperations(node, "3.4x faster triage!", [
    BOLD_FASTER,
  ]);
  assert.deepEqual(committedKind(operations), {
    kind: "set",
    value: {
      ...node.kind,
      content: "3.4x faster triage!",
      spans: [BOLD_FASTER],
    },
  });
});

test("a SPANS-ONLY change is a real edit — rung B's null contract, relaxed", () => {
  const node = HARVESTED_AD_PAGE.nodes.text_proof_stat;
  const operations = textEditCommitOperations(node, textKind(node).content, [
    BOLD_FASTER,
  ]);
  assert.deepEqual(committedKind(operations), {
    kind: "set",
    value: { ...node.kind, spans: [BOLD_FASTER] },
  });
});

test("clearing every span is a write, not a no-op", () => {
  // An EMPTY vector is a legitimate formatting result (un-bold the only bold
  // run) and must reach the engine as `spans: []`, never be read as "nothing
  // to write".
  const node = spannedStat();
  const operations = textEditCommitOperations(node, textKind(node).content, []);
  assert.deepEqual(committedKind(operations), {
    kind: "set",
    value: { ...node.kind, spans: [] },
  });
});

test("unchanged content AND unchanged spans write nothing", () => {
  const node = spannedStat();
  assert.equal(
    textEditCommitOperations(node, textKind(node).content, [BOLD_FASTER]),
    null,
  );
});

test("the stored spans' key ORDER does not make an unchanged vector look changed", () => {
  const node = spannedStat();
  // The wire hands spans back in the engine's serde order; the session builds
  // them in the contract's. Same span either way.
  assert.equal(
    textEditCommitOperations(node, textKind(node).content, [
      { font_weight: 700, end: 11, start: 5 },
    ]),
    null,
  );
});

test("D4: a content edit past every span SPLITS the vector so both survive", () => {
  // The engine clears spans when a content change carries a byte-identical
  // vector (`operations.rs:620-631`). Edits landing after the last span
  // legitimately maintain the same vector, so the commit re-authors it as a
  // semantically identical but structurally different one.
  const node = spannedStat();
  const operations = textEditCommitOperations(node, "3.4x faster triage!", [
    BOLD_FASTER,
  ]);
  assert.deepEqual(committedKind(operations), {
    kind: "set",
    value: {
      ...node.kind,
      content: "3.4x faster triage!",
      spans: [
        { start: 5, end: 6, font_weight: 700 },
        { start: 6, end: 11, font_weight: 700 },
      ],
    },
  });
});

test("a locked node refuses the spans channel too", () => {
  const node = spannedStat();
  node.locked = true;
  assert.equal(textEditCommitOperations(node, "anything", []), null);
});

test("D10: a node the reload took away refuses the spans channel too", () => {
  assert.equal(textEditCommitOperations(null, "anything", [BOLD_FASTER]), null);
});

test("an out-of-bounds vector is CLAMPED, never written as the engine would take it", () => {
  // The engine validates spans at LAYOUT, not at apply: an out-of-bounds span
  // applies clean and then silently drops the node out of measurement
  // (LUMV0906). So the commit is the last line of defence, and what it sends
  // always satisfies the five rules — here, an end past the string is clamped
  // to it rather than refused or forwarded.
  const node = HARVESTED_AD_PAGE.nodes.text_proof_stat;
  const operations = textEditCommitOperations(node, "3.4x faster triage", [
    { start: 5, end: 4000, font_weight: 700 },
  ]);
  assert.deepEqual(committedKind(operations), {
    kind: "set",
    value: {
      ...node.kind,
      spans: [{ start: 5, end: 18, font_weight: 700 }],
    },
  });
});

test("the STYLE write says which surface it came from", () => {
  assert.equal(SCENE_TEXT_STYLE_INTENT, "canvas: text style");
});

test("a formatting commit does not change what the overlay is KEYED on", () => {
  // The overlay is mounted `key={textEdit.nodeId}`, and a formatting action
  // commits mid-session: the scene comes straight back with new spans (and,
  // when the draft was dirty, new content). If either of those reached the key
  // the overlay would remount and throw away the live draft, the caret and the
  // selection the next toggle acts on. So the key must move for NEITHER.
  const before = modelFor(sceneWithLaidOutStat());
  const committed = sceneWithLaidOutStat();
  textKind(committed.nodes.text_proof_stat).spans = [BOLD_FASTER];
  textKind(committed.nodes.text_proof_stat).content = "3.4x faster triage!";
  const after = modelFor(committed);
  assert.ok(before && after);
  assert.equal(after.nodeId, before.nodeId);
  // …and the model DID move, so the assertion above is not vacuous.
  assert.notDeepEqual(after.text, before.text);
});

test("the overlay model carries the stored text kind, for the toolbar to read", () => {
  const scene = sceneWithLaidOutStat();
  textKind(scene.nodes.text_proof_stat).spans = [BOLD_FASTER];
  const model = modelFor(scene);
  assert.ok(model);
  // The toolbar's format reads run against the NODE (override semantics are
  // resolved against its own base), so the session needs the whole kind — not
  // just the string the caret edits.
  assert.equal(model.text.font_weight, 600);
  assert.deepEqual(model.text.spans, [BOLD_FASTER]);
  assert.equal(model.text.content, model.content);
});

/* -------------------------------------------------------------------------
 * The overlay model — geometry in stage px, style off the descriptor
 * ---------------------------------------------------------------------- */

test("the overlay covers the node's laid-out box, in stage px", () => {
  const model = modelFor(sceneWithLaidOutStat());
  assert.ok(model);
  assert.equal(model.nodeId, "text_proof_stat");
  assert.equal(model.left, STAT_BOX.x);
  assert.equal(model.top, STAT_BOX.y);
  assert.equal(model.width, STAT_BOX.width);
  assert.equal(model.height, STAT_BOX.height);
  assert.equal(model.rotation, 0);
});

test("2026-10-18: the overlay opens over every painted line, even past a box the copy outgrew", () => {
  const scene = sceneWithLaidOutStat();
  // A fixed box one line tall whose copy wraps to two: the engine paints the
  // second line below the box, and the caret must show it rather than clip it.
  scene.nodes.text_proof_stat.computed!.text_lines = [
    { x: STAT_BOX.x, y: STAT_BOX.y, width: 200, height: 36 },
    { x: STAT_BOX.x, y: STAT_BOX.y + 36, width: 120, height: 36 },
  ];
  const model = modelFor(scene);
  assert.ok(model);
  assert.equal(model.top, STAT_BOX.y);
  assert.equal(model.height, 72);
  // Width stays the box the engine wraps in, so the DOM wraps the same lines.
  assert.equal(model.left, STAT_BOX.x);
  assert.equal(model.width, STAT_BOX.width);
});

test("2026-10-18: lines painted above the box (bottom-aligned overflow) are covered too", () => {
  const scene = sceneWithLaidOutStat();
  scene.nodes.text_proof_stat.computed!.text_lines = [
    { x: STAT_BOX.x, y: STAT_BOX.y - 20, width: 300, height: 30 },
    { x: STAT_BOX.x, y: STAT_BOX.y + 10, width: 120, height: 26 },
  ];
  const model = modelFor(scene);
  assert.ok(model);
  assert.equal(model.top, STAT_BOX.y - 20);
  assert.equal(model.height, 56);
  assert.equal(model.width, STAT_BOX.width);
});

test("2026-10-18: lines inside the box leave the overlay on the box", () => {
  const scene = sceneWithLaidOutStat();
  scene.nodes.text_proof_stat.computed!.text_lines = [
    { x: STAT_BOX.x, y: STAT_BOX.y + 4, width: 120, height: 20 },
  ];
  const model = modelFor(scene);
  assert.ok(model);
  assert.equal(model.top, STAT_BOX.y);
  assert.equal(model.height, STAT_BOX.height);
});

test("2026-10-18: the edit surface grows to its text and never shrinks below the box", () => {
  // box 100, text 80 + 2px border: the box wins.
  assert.equal(textEditSurfaceHeight(100, 80, 2), 100);
  // box 100, text 160 + 2px border: the surface grows to show every line.
  assert.equal(textEditSurfaceHeight(100, 160, 2), 162);
});

test("the overlay edits the STORED content, not the painted text", () => {
  const scene = sceneWithLaidOutStat();
  // `text_transform` applies to painted glyphs only; the caret edits what is
  // stored, so the overlay must show the stored string unchanged.
  scene.nodes.text_proof_stat.kind.text_transform = "uppercase";
  const model = modelFor(scene);
  assert.ok(model);
  assert.equal(model.content, "3.4x faster triage");
});

/* -------------------------------------------------------------------------
 * The DOM font stack (D2)
 *
 * Found by the live walk, 2026-08-24: the overlay asked for `font-family:
 * Inter` and got a system SERIF, because nothing registers a DOM face under
 * the bare name "Inter" — `globals.css` imports `@fontsource-variable/inter`,
 * whose face registers as "Inter Variable", while the scene's own family
 * string (and CanvasKit's `INTER_FAMILY`) is "Inter". CanvasKit painted true
 * Inter under a serif caret, so the wrapping visibly disagreed.
 *
 * The stack is not a guess about one font: it is the general shape of this
 * repo's registration. `libraryFonts.ts` / `kitFonts.ts` add faces under the
 * DECLARED family (so a kit family hits entry one), fontsource-variable adds
 * a " Variable"-suffixed family (entry two), and `sans-serif` is the honest
 * floor. `features/projects/config/project-canvas-fonts.ts` already writes the
 * identical convention by hand for the same font.
 * ---------------------------------------------------------------------- */

test("the stack covers both the declared family and its Variable face", () => {
  assert.equal(domFontFamilyStack("Inter"), '"Inter", "Inter Variable", sans-serif');
});

test("a family with a space is quoted, so the stack stays parseable CSS", () => {
  assert.equal(
    domFontFamilyStack("PP Neue Montreal"),
    '"PP Neue Montreal", "PP Neue Montreal Variable", sans-serif',
  );
});

test("a family already named Variable is not suffixed twice", () => {
  assert.equal(domFontFamilyStack("Inter Variable"), '"Inter Variable", sans-serif');
});

test("a nameless family degrades to the generic, never to an empty stack", () => {
  // An empty first entry is invalid CSS and takes the WHOLE declaration down
  // with it, which is how a missing family would become a serif again.
  assert.equal(domFontFamilyStack(""), "sans-serif");
  assert.equal(domFontFamilyStack("   "), "sans-serif");
});

test("a family carrying quote characters cannot break out of its quotes", () => {
  assert.equal(
    domFontFamilyStack('Ev"il'),
    '"Ev\\"il", "Ev\\"il Variable", sans-serif',
  );
});

test("the overlay is style-matched to the painted node", () => {
  const model = modelFor(sceneWithLaidOutStat());
  assert.ok(model);
  assert.deepEqual(model.style, {
    color: "#C7C2F5",
    // D2: the node's family is "Inter"; what the DOM is asked for is the STACK
    // that actually resolves to it. Stronger than the bare family this pinned
    // before — it names the exact declaration, family included.
    fontFamily: '"Inter", "Inter Variable", sans-serif',
    fontSize: 26,
    fontStyle: "normal",
    fontWeight: 600,
    letterSpacing: 0,
    lineHeight: 1.35,
    textAlign: "left",
    valign: "top",
  });
});

test("block italic reaches the edit surface, so the caret sits in matching glyphs", () => {
  const scene = sceneWithLaidOutStat();
  scene.nodes.text_proof_stat.kind.italic = true;
  const model = modelFor(scene);
  assert.ok(model);
  assert.equal(model.style.fontStyle, "italic");
});

test("zoom scales the box AND the font metrics together", () => {
  const scene = sceneWithLaidOutStat();
  scene.nodes.text_proof_stat.kind.letter_spacing = 2;
  const model = modelFor(scene, {
    viewport: { zoom: 2, pan: { x: 0, y: 0 } },
  });
  assert.ok(model);
  assert.equal(model.left, STAT_BOX.x * 2);
  assert.equal(model.width, STAT_BOX.width * 2);
  assert.equal(model.height, STAT_BOX.height * 2);
  assert.equal(model.style.fontSize, 52);
  assert.equal(model.style.letterSpacing, 4);
  // A ratio, never a length — it must not be scaled.
  assert.equal(model.style.lineHeight, 1.35);
});

test("a pan moves the overlay with the pixels it sits over", () => {
  const model = modelFor(sceneWithLaidOutStat(), {
    viewport: { zoom: 1, pan: { x: 40, y: -25 } },
  });
  assert.ok(model);
  assert.equal(model.left, STAT_BOX.x + 40);
  assert.equal(model.top, STAT_BOX.y - 25);
});

test("a degenerate box still leaves a grabbable caret", () => {
  const scene = sceneWithLaidOutStat();
  scene.nodes.text_proof_stat.computed = {
    layout_bounds: { x: 10, y: 20, width: 0, height: 0 },
    render_bounds: { x: 10, y: 20, width: 0, height: 0 },
  };
  const model = modelFor(scene);
  assert.ok(model);
  assert.equal(model.width, MIN_TEXT_EDIT_SIZE_PX);
  assert.equal(model.height, MIN_TEXT_EDIT_SIZE_PX);
});

test("an unsolved node has no overlay — a guessed box would draw the caret elsewhere", () => {
  assert.equal(modelFor(HARVESTED_AD_PAGE), null);
});

test("D10: a node the reload took away closes the session", () => {
  const scene = sceneWithLaidOutStat();
  assert.equal(modelFor(scene, { editingNodeId: "text_gone" }), null);
});

test("a non-text node has no overlay", () => {
  const scene = clone(HARVESTED_AD_PAGE);
  scene.nodes.ellipse_proof_dot.computed = {
    layout_bounds: { ...STAT_BOX },
    render_bounds: { ...STAT_BOX },
  };
  assert.equal(modelFor(scene, { editingNodeId: "ellipse_proof_dot" }), null);
});

test("no session, no overlay", () => {
  assert.equal(modelFor(sceneWithLaidOutStat(), { editingNodeId: null }), null);
});

/* -------------------------------------------------------------------------
 * The edit surface's constant styling (D1)
 *
 * Found by the live walk, 2026-08-24, on the seeded DARK-NAVY ad: the textarea
 * resolved `color: #fff` (correct — the node's own fill) over an OPAQUE WHITE
 * surface, so the user typed blind and only the selection highlight made the
 * text legible at all. The colour is data and lives in the model above; the
 * surface is constant and lives in the stylesheet, so it is pinned here — the
 * same discipline `scene-image-ai.test.ts` keeps over `chat-shell.module.css`.
 * ---------------------------------------------------------------------- */

const OVERLAY_RULE = /\.textEditOverlay \{([^}]*)\}/.exec(
  readFileSync(
    new URL("../components/scene-artifact-canvas.module.css", import.meta.url),
    "utf8",
  ),
)?.[1];

test("the edit surface is TRANSPARENT, so the node's own fill stays legible", () => {
  assert.ok(OVERLAY_RULE);
  // Anything opaque re-introduces the defect on any artboard whose contrast
  // the node's fill was chosen against — white text on white being the walk's
  // own case.
  assert.match(OVERLAY_RULE, /background:\s*transparent;/);
  assert.doesNotMatch(OVERLAY_RULE, /background:\s*#/);
});

test("the edit border survives, so the session still says where it is", () => {
  assert.ok(OVERLAY_RULE);
  assert.match(OVERLAY_RULE, /border:\s*1px solid #256c70;/);
});
