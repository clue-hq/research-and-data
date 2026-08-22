import assert from "node:assert/strict";
import { it } from "node:test";
import type { Node, Rect, Scene } from "../engine/scene/contracts";
import { moveNodeToParent } from "../engine/scene/operations";
import {
  alignDistributeCommitOperation,
  alignNodesOperations,
  distributeNodesOperations,
} from "../engine/scene/alignDistribute";
import {
  canAlignNodes,
  canDistributeNodes,
  canGroupNodes,
  canUngroupNode,
  nodePageSpaceBox,
} from "../engine/scene/sceneQueries";
import {
  loadWasmModuleFromDisk,
  wasmArtifactPresent,
} from "../engine/scene/__tests__/wasm-module-loader";
import { WasmEngine } from "../engine/scene/wasmEngine";
import {
  AD_PAGE_ID,
  HARVESTED_AD_PAGE,
} from "./__fixtures__/scene-nodes";
import {
  arrangeEnablement,
  arrangeShortcut,
  zOrderOperation,
  zOrderShortcut,
  type ZOrderAction,
} from "./scene-arrange";

/**
 * AD4.B step 4 — the Arrange section's pure decisions.
 *
 * Every case runs over the HARVESTED page (real seeded bytes), and every
 * expected operation is built through the ENGINE's own `moveNodeToParent`, so a
 * write that names the wrong parent or the wrong index fails loudly instead of
 * agreeing with a hand-written literal.
 *
 * THE FIXTURE'S OWN SHAPE, which every case below leans on:
 *   page `page_linkedin_square` → children `[frame_ad_root]` (the root frame is
 *   the page's ONLY child);
 *   `frame_ad_root` → `[auto_row_copy, rect_accent_bar, line_divider,
 *   image_hero]` — four siblings under a PLAIN frame, so none is solver-managed
 *   and all four are direct-geometry-editable;
 *   `auto_row_copy` (an auto_layout with no `layout_mode`, i.e. a Stack) →
 *   `[text_headline, group_proof]` — both solver-managed, so neither can be
 *   grouped or aligned;
 *   `group_proof` → `[ellipse_proof_dot, text_proof_stat]`.
 */

const SCENE = HARVESTED_AD_PAGE;
const AD_ROOT_FRAME_ID = "frame_ad_root";
/** The root frame's four children, in document order — the z-order stack. */
const STACK = [
  "auto_row_copy",
  "rect_accent_bar",
  "line_divider",
  "image_hero",
] as const;
const ROOT_PARENT = { kind: "node", id: AD_ROOT_FRAME_ID } as const;

function clone(scene: Scene): Scene {
  return JSON.parse(JSON.stringify(scene)) as Scene;
}

/** A clone of the harvested scene with ONE field of one node replaced — the
 * AD2.4/AD2.5 derived-fixture technique (`scene-apply.test.ts`'s
 * `withNodeField`), so a locked/relocated case is still harvested bytes.
 * `base` lets the L19 cases below stack several one-field edits into a single
 * derived scene without ever hand-writing a node. */
function withNodeField<Field extends keyof Node>(
  nodeId: string,
  field: Field,
  value: Node[Field],
  base: Scene = SCENE,
): Scene {
  const scene = clone(base);
  const node = scene.nodes[nodeId];
  assert.ok(node, `fixture node ${nodeId} missing`);
  node[field] = value;
  return scene;
}

/** A page-space box for a node the solver never laid out, so the harvested
 * fixture can answer `nodePageSpaceBox` (which reads `computed.layout_bounds`,
 * or `absolute_box` for a pinned node). Real ad geometry, stacked so the three
 * boxes genuinely differ on both axes and align/distribute have work to do. */
function boxed(x: number, y: number, width = 120, height = 40): Rect {
  return { x, y, width, height };
}

function withGeometry(
  base: Scene,
  boxes: Readonly<Record<string, Rect>>,
): Scene {
  let scene = base;
  for (const [nodeId, box] of Object.entries(boxes)) {
    scene = withNodeField(
      nodeId,
      "computed",
      { layout_bounds: { ...box }, render_bounds: { ...box } },
      scene,
    );
  }
  return scene;
}

const ALL_ACTIONS: readonly ZOrderAction[] = [
  "front",
  "forward",
  "backward",
  "back",
];

/* ── z-order: the index math ─────────────────────────────────────────────── */

it("§1.5 z-order: the index is an insertion index into the siblings WITHOUT the moved node (remove-then-insert)", () => {
  // `Scene::move_node` (lumen-core `operations.rs:517-566`) detaches the node
  // FIRST and then inserts it at `index`, so a same-parent move counts against
  // a list of length n-1. `rect_accent_bar` sits at 1 of 4; one step forward
  // means "after the node that is currently at 2", i.e. insertion index 2.
  assert.deepEqual(
    zOrderOperation(SCENE, "rect_accent_bar", "forward"),
    moveNodeToParent("rect_accent_bar", ROOT_PARENT, 2),
  );
  // One step backward is insertion index i-1 — the position the previous
  // sibling occupies, which shifts up by one when this node leaves.
  assert.deepEqual(
    zOrderOperation(SCENE, "line_divider", "backward"),
    moveNodeToParent("line_divider", ROOT_PARENT, 1),
  );
});

it("§1.5 z-order: front is the LAST index of the post-detach list, back is 0", () => {
  // Later in `children` paints on top (the MVP editor's `ArrangeSection` sends
  // `moveAfterEdit(node, siblings[siblings.length - 1])` for "To front"), so
  // "front" is the end of the array. Post-detach length is 4-1 = 3.
  assert.deepEqual(
    zOrderOperation(SCENE, "auto_row_copy", "front"),
    moveNodeToParent("auto_row_copy", ROOT_PARENT, 3),
  );
  assert.deepEqual(
    zOrderOperation(SCENE, "image_hero", "back"),
    moveNodeToParent("image_hero", ROOT_PARENT, 0),
  );
});

it("§1.5 z-order: the move names the node's OWN parent, not the page", () => {
  // A nested node moves inside its own container — `group_proof` is a child of
  // `auto_row_copy`, so its parent ref is that node, never the page.
  assert.deepEqual(
    zOrderOperation(SCENE, "group_proof", "back"),
    moveNodeToParent("group_proof", { kind: "node", id: "auto_row_copy" }, 0),
  );
  assert.deepEqual(
    zOrderOperation(SCENE, "text_proof_stat", "back"),
    moveNodeToParent("text_proof_stat", { kind: "node", id: "group_proof" }, 0),
  );
});

/* ── z-order: the refusals ───────────────────────────────────────────────── */

it("§1.5 z-order: the top of the stack refuses front and forward, the bottom refuses backward and back", () => {
  assert.equal(zOrderOperation(SCENE, "image_hero", "front"), null);
  assert.equal(zOrderOperation(SCENE, "image_hero", "forward"), null);
  assert.deepEqual(
    zOrderOperation(SCENE, "image_hero", "backward"),
    moveNodeToParent("image_hero", ROOT_PARENT, 2),
  );

  assert.equal(zOrderOperation(SCENE, "auto_row_copy", "backward"), null);
  assert.equal(zOrderOperation(SCENE, "auto_row_copy", "back"), null);
  assert.deepEqual(
    zOrderOperation(SCENE, "auto_row_copy", "forward"),
    moveNodeToParent("auto_row_copy", ROOT_PARENT, 1),
  );
});

it("§1.5 z-order: an only child refuses every action (it is both top and bottom)", () => {
  // `frame_ad_root` is the page's only child, and every one-of-one node is at
  // once the front and the back of its stack.
  const soleChild = clone(SCENE);
  soleChild.nodes.auto_row_copy!.children = ["text_headline"];
  for (const action of ALL_ACTIONS) {
    assert.equal(
      zOrderOperation(soleChild, "text_headline", action),
      null,
      `${action} on an only child`,
    );
  }
});

it("§4 z-order: a LOCKED node writes nothing", () => {
  const locked = withNodeField("rect_accent_bar", "locked", true);
  for (const action of ALL_ACTIONS) {
    assert.equal(
      zOrderOperation(locked, "rect_accent_bar", action),
      null,
      `${action} on a locked node`,
    );
  }
});

it("§1.5 z-order: the page's ROOT FRAME is not reorderable", () => {
  // The artboard is not a layer in the stack; re-parenting it against its page
  // is meaningless. Proven with a SECOND page child so the refusal cannot be
  // the only-child rule in disguise.
  const twoPageChildren = clone(SCENE);
  twoPageChildren.pages[AD_PAGE_ID]!.children = [
    AD_ROOT_FRAME_ID,
    "line_divider",
  ];
  twoPageChildren.nodes[AD_ROOT_FRAME_ID]!.children = [
    "auto_row_copy",
    "rect_accent_bar",
    "image_hero",
  ];
  for (const action of ALL_ACTIONS) {
    assert.equal(
      zOrderOperation(twoPageChildren, AD_ROOT_FRAME_ID, action),
      null,
      `${action} on the root frame`,
    );
  }
  // …and the sibling that is NOT the root frame still moves, so the refusal is
  // about the artboard rather than about page-parented nodes as a class.
  assert.deepEqual(
    zOrderOperation(twoPageChildren, "line_divider", "back"),
    moveNodeToParent("line_divider", { kind: "page", id: AD_PAGE_ID }, 0),
  );
});

it("§1.5 z-order: a node the scene does not carry writes nothing", () => {
  for (const action of ALL_ACTIONS) {
    assert.equal(zOrderOperation(SCENE, "node_does_not_exist", action), null);
  }
});

/* ── z-order: the semantics, proven against the REAL engine ──────────────── */

if (!wasmArtifactPresent) {
  console.log(
    "[scene-arrange] the move_node parity case SKIPPED — no wasm artifact at " +
      "public/vendor/wasm; run `node scripts/copy-design-vendor.mjs`.",
  );
}

it(
  "§1.5 z-order: the real engine puts every step exactly where the math says",
  { skip: !wasmArtifactPresent },
  async () => {
    // The index math above is READ off `Scene::move_node`
    // (`crates/lumen-core/src/operations.rs:517-566`, remove-then-insert). This
    // case stops that being a reading: it applies each operation through the
    // SAME wasm engine the canvas holds and asserts the resulting sibling
    // order, so a semantics change upstream fails here instead of silently
    // sending every "forward" one place too far.
    const wasm = await loadWasmModuleFromDisk();
    const cases: readonly (readonly [string, ZOrderAction, readonly string[]])[] = [
      ["rect_accent_bar", "forward", ["auto_row_copy", "line_divider", "rect_accent_bar", "image_hero"]],
      ["rect_accent_bar", "front", ["auto_row_copy", "line_divider", "image_hero", "rect_accent_bar"]],
      ["line_divider", "backward", ["auto_row_copy", "line_divider", "rect_accent_bar", "image_hero"]],
      ["image_hero", "back", ["image_hero", "auto_row_copy", "rect_accent_bar", "line_divider"]],
      ["auto_row_copy", "front", ["rect_accent_bar", "line_divider", "image_hero", "auto_row_copy"]],
    ];
    for (const [nodeId, action, expected] of cases) {
      const scene = clone(SCENE);
      const engine = new WasmEngine(wasm, scene);
      const operation = zOrderOperation(scene, nodeId, action);
      assert.ok(operation, `${nodeId} / ${action} produced no operation`);
      const outcome = engine.applyOperations([operation]);
      assert.equal(outcome.accepted, true, `${nodeId} / ${action} was refused`);
      const children = outcome.scene.nodes[AD_ROOT_FRAME_ID]?.children;
      assert.deepEqual(children, [...expected], `${nodeId} / ${action}`);
      // …and it is still the same four nodes: a reorder never duplicates or
      // drops one, which is what a wrong index would eventually produce.
      assert.deepEqual(
        [...(children ?? [])].sort(),
        [...STACK].sort(),
        `${nodeId} / ${action} changed the membership of the stack`,
      );
    }
  },
);

/* ── enablement: z-order ─────────────────────────────────────────────────── */

it("§1.5 enablement: the z-order flags are the PRIMARY node's, and agree with the math exactly", () => {
  for (const nodeId of STACK) {
    const enablement = arrangeEnablement(SCENE, [nodeId, "rect_accent_bar"]);
    for (const action of ALL_ACTIONS) {
      assert.equal(
        enablement.zOrder[action],
        zOrderOperation(SCENE, nodeId, action) !== null,
        `${nodeId} / ${action}`,
      );
    }
  }
  // Stated positively at both edges so the loop above cannot pass vacuously.
  assert.deepEqual(arrangeEnablement(SCENE, ["image_hero"]).zOrder, {
    back: true,
    backward: true,
    forward: false,
    front: false,
  });
  assert.deepEqual(arrangeEnablement(SCENE, ["auto_row_copy"]).zOrder, {
    back: false,
    backward: false,
    forward: true,
    front: true,
  });
});

it("§1.5 enablement: an EMPTY selection enables nothing", () => {
  assert.deepEqual(arrangeEnablement(SCENE, []), {
    align: false,
    distribute: false,
    group: false,
    ungroup: false,
    zOrder: { back: false, backward: false, forward: false, front: false },
  });
});

it("§1.5 enablement: no scene enables nothing", () => {
  assert.deepEqual(arrangeEnablement(null, ["rect_accent_bar"]), {
    align: false,
    distribute: false,
    group: false,
    ungroup: false,
    zOrder: { back: false, backward: false, forward: false, front: false },
  });
});

/* ── enablement: align / distribute ──────────────────────────────────────── */

/** The stack's three leaf siblings — the selection the browser proof used. */
const THREE = ["rect_accent_bar", "line_divider", "image_hero"];
const TWO = ["rect_accent_bar", "line_divider"];

/** The same three siblings PINNED (`position_mode: "absolute"` + a real
 * `absolute_box`), which is the first of the two shapes
 * `alignDistributeCommitOperation` can express. Still harvested bytes: three
 * stacked one-field edits, no hand-written node. */
function pinnedTrio(): Scene {
  let scene = SCENE;
  // Deliberately uneven on BOTH axes, so align-left and distribute-vertical
  // each genuinely have a node to move.
  const boxes: Record<string, Rect> = {
    image_hero: boxed(70, 300),
    line_divider: boxed(40, 180),
    rect_accent_bar: boxed(10, 100),
  };
  for (const [nodeId, box] of Object.entries(boxes)) {
    scene = withNodeField(nodeId, "position_mode", "absolute", scene);
    scene = withNodeField(nodeId, "absolute_box", box, scene);
  }
  return scene;
}

/**
 * RULING L19 — the defect the live browser proof caught, pinned.
 *
 * DELIBERATE FLIP. Before L19 this case asserted `align === true` on `TWO` and
 * `distribute === true` on `THREE` — the engine's gate, taken at its word. It
 * is now FALSE, and the old assertions are gone on purpose rather than by
 * accident: they described enablement that could not commit.
 *
 * THE REFUSAL IS OURS, NOT THE ENGINE'S — the first two assertions say so out
 * loud (the same pattern the root-frame ungroup case uses).
 */
it("§1.5 · L19 enablement: children of a PLAIN FRAME refuse align and distribute — the commit can write nothing for them", () => {
  // The engine's own gates say YES: these are unlocked, not solver-managed, so
  // `isNodeDirectGeometryEditable` is true for every one of them.
  assert.equal(canAlignNodes(SCENE, TWO), true);
  assert.equal(canDistributeNodes(SCENE, THREE), true);

  // …but `alignDistributeCommitOperation` has exactly two branches — pinned
  // (`absolute_box`) and freehand (`transform`) — and the seeded artboard is a
  // PLAIN `frame` whose children carry no `position_mode`, so every member
  // falls off the end of that function and it returns null. Proven on a
  // derived fixture that DOES have resolvable boxes, so the empty batch below
  // can only be the null commit and not "never laid out":
  const laidOut = withGeometry(SCENE, {
    image_hero: boxed(70, 300),
    line_divider: boxed(40, 200),
    rect_accent_bar: boxed(10, 100),
  });
  for (const id of THREE) {
    const node = laidOut.nodes[id]!;
    const box = nodePageSpaceBox(laidOut, id);
    assert.ok(box, `${id} should have a resolvable box in this fixture`);
    assert.equal(
      alignDistributeCommitOperation(laidOut, node, box),
      null,
      `${id} is neither pinned nor freehand, so the commit writes nothing`,
    );
  }
  assert.deepEqual(alignNodesOperations(laidOut, [...THREE], "left"), []);
  assert.deepEqual(distributeNodesOperations(laidOut, [...THREE], "horizontal"), []);

  // So the buttons must be OFF. Enabling them is the dishonest enablement §1.5
  // forbids: the live proof clicked "Align top" and got no request, no new
  // version and no error — the click simply vanished.
  assert.equal(arrangeEnablement(SCENE, TWO).align, false);
  assert.equal(arrangeEnablement(SCENE, THREE).align, false);
  assert.equal(arrangeEnablement(SCENE, THREE).distribute, false);
  // The same holds once geometry exists — commit-reachability is about the
  // node's SHAPE, not about whether it has been laid out.
  assert.equal(arrangeEnablement(laidOut, THREE).align, false);
  assert.equal(arrangeEnablement(laidOut, THREE).distribute, false);
});

it("§1.5 · L19 enablement: PINNED members are commit-reachable — align at 2+, distribute at 3+, and the ops are real", () => {
  const pinned = pinnedTrio();
  // The count floors, restated on a selection that can actually commit.
  assert.equal(arrangeEnablement(pinned, ["rect_accent_bar"]).align, false);
  assert.equal(arrangeEnablement(pinned, TWO).align, true);
  assert.equal(arrangeEnablement(pinned, TWO).distribute, false);
  assert.equal(arrangeEnablement(pinned, THREE).align, true);
  assert.equal(arrangeEnablement(pinned, THREE).distribute, true);
  // The engine's gate is still the necessary half — never re-implemented, only
  // ANDed with reachability.
  assert.equal(canAlignNodes(pinned, THREE), true);
  assert.equal(canDistributeNodes(pinned, THREE), true);
  // End-to-end reachability: enabled means the batch is non-empty.
  assert.ok(alignNodesOperations(pinned, [...THREE], "left").length > 0);
  assert.ok(
    distributeNodesOperations(pinned, [...THREE], "vertical").length > 0,
  );
});

it("§1.5 · L19 enablement: FREEHAND children of a Free container are commit-reachable too", () => {
  // The commit's second branch. `auto_row_copy` is an auto_layout whose
  // `layout_mode` is unset (Stack) in the harvested bytes — its children are
  // solver-managed and the engine's own gate refuses them. Flip that ONE field
  // to "free" and they become freehand: the human owns their transforms, the
  // engine's gate opens, and the commit can express the move.
  const stack = SCENE.nodes.auto_row_copy!;
  const pair = ["text_headline", "group_proof"];
  assert.equal(canAlignNodes(SCENE, pair), false);
  assert.equal(arrangeEnablement(SCENE, pair).align, false);

  let free = withNodeField("auto_row_copy", "layout", {
    ...stack.layout!,
    layout_mode: "free",
  });
  free = withGeometry(free, {
    auto_row_copy: boxed(0, 0, 400, 300),
    group_proof: boxed(60, 140),
    text_headline: boxed(20, 40),
  });
  assert.equal(canAlignNodes(free, pair), true);
  assert.equal(arrangeEnablement(free, pair).align, true);
  assert.ok(alignNodesOperations(free, [...pair], "left").length > 0);
});

it("§1.5 enablement: a LOCKED member refuses align and distribute for the whole set", () => {
  // Pinned, so reachability is not what is doing the refusing here — the lock
  // is (the engine's `isNodeDirectGeometryEditable` refuses a locked node).
  const locked = withNodeField("line_divider", "locked", true, pinnedTrio());
  assert.equal(arrangeEnablement(locked, THREE).align, false);
  assert.equal(arrangeEnablement(locked, THREE).distribute, false);
});

it("§1.5 · L19 enablement: ONE unreachable member is enough to refuse the whole set", () => {
  // Two pinned siblings and one plain-frame child: the engine's gate says yes
  // to all three, but the batch would move only two of them — a partial align
  // is not the align the button promises.
  let mixed = withNodeField("rect_accent_bar", "position_mode", "absolute");
  mixed = withNodeField("rect_accent_bar", "absolute_box", boxed(10, 100), mixed);
  mixed = withNodeField("line_divider", "position_mode", "absolute", mixed);
  mixed = withNodeField("line_divider", "absolute_box", boxed(40, 200), mixed);
  assert.equal(canAlignNodes(mixed, THREE), true);
  assert.equal(arrangeEnablement(mixed, TWO).align, true);
  assert.equal(arrangeEnablement(mixed, THREE).align, false);
  assert.equal(arrangeEnablement(mixed, THREE).distribute, false);
});

it("§1.5 enablement: solver-managed Stack children align to nothing", () => {
  // `text_headline` and `group_proof` are children of a Stack auto-layout, so
  // the solver — not the human — owns their geometry.
  const pair = ["text_headline", "group_proof"];
  assert.equal(arrangeEnablement(SCENE, pair).align, false);
});

/* ── enablement: group / ungroup ─────────────────────────────────────────── */

it("§1.5 enablement: group needs 2+ unlocked SAME-PARENT siblings", () => {
  const siblings = ["rect_accent_bar", "line_divider"];
  assert.equal(arrangeEnablement(SCENE, siblings).group, true);
  assert.equal(
    arrangeEnablement(SCENE, siblings).group,
    canGroupNodes(SCENE, siblings),
  );
  assert.equal(arrangeEnablement(SCENE, ["rect_accent_bar"]).group, false);
  // Cross-parent: `ellipse_proof_dot` lives in `group_proof`, not in the root
  // frame — the engine's gate refuses the pair and so does the button.
  assert.equal(
    arrangeEnablement(SCENE, ["rect_accent_bar", "ellipse_proof_dot"]).group,
    false,
  );
  // A duplicated id is not two nodes.
  assert.equal(
    arrangeEnablement(SCENE, ["rect_accent_bar", "rect_accent_bar"]).group,
    false,
  );
});

it("§1.5 enablement: a LOCKED member refuses group", () => {
  const locked = withNodeField("line_divider", "locked", true);
  assert.equal(
    arrangeEnablement(locked, ["rect_accent_bar", "line_divider"]).group,
    false,
  );
});

it("§1.5 enablement: solver-managed Stack children refuse group", () => {
  assert.equal(
    arrangeEnablement(SCENE, ["text_headline", "group_proof"]).group,
    false,
  );
});

it("§1.5 enablement: ungroup is a SINGLE unlocked container", () => {
  assert.equal(arrangeEnablement(SCENE, ["group_proof"]).ungroup, true);
  assert.equal(
    arrangeEnablement(SCENE, ["group_proof"]).ungroup,
    canUngroupNode(SCENE, "group_proof"),
  );
  assert.equal(arrangeEnablement(SCENE, ["auto_row_copy"]).ungroup, true);
  // A leaf is not a container.
  assert.equal(arrangeEnablement(SCENE, ["rect_accent_bar"]).ungroup, false);
  assert.equal(arrangeEnablement(SCENE, ["text_headline"]).ungroup, false);
  // Two selected containers are not "a single container".
  assert.equal(
    arrangeEnablement(SCENE, ["group_proof", "auto_row_copy"]).ungroup,
    false,
  );
});

it("§1.5 enablement: the page's ROOT FRAME refuses ungroup (dissolving the artboard)", () => {
  // The engine's own gate says yes — the artboard IS a container — so this
  // refusal is ours, and it has to exist: ⇧⌘G on a selected artboard would
  // DISSOLVE it, scattering its children across the page and leaving a document
  // with no frame. The panel cannot reach it (the artboard renders the canvas
  // schema), but the keyboard reaches every schema.
  assert.equal(canUngroupNode(SCENE, AD_ROOT_FRAME_ID), true);
  assert.equal(arrangeEnablement(SCENE, [AD_ROOT_FRAME_ID]).ungroup, false);
  // …and the refusal is about THE ARTBOARD, not about page-parented containers
  // as a class: a second top-level container still ungroups. (Same control the
  // z-order root-frame case uses, so the two verbs cannot drift apart.)
  const twoPageChildren = clone(SCENE);
  twoPageChildren.pages[AD_PAGE_ID]!.children = [AD_ROOT_FRAME_ID, "group_proof"];
  twoPageChildren.nodes.auto_row_copy!.children = ["text_headline"];
  assert.equal(arrangeEnablement(twoPageChildren, ["group_proof"]).ungroup, true);
  assert.equal(
    arrangeEnablement(twoPageChildren, [AD_ROOT_FRAME_ID]).ungroup,
    false,
  );
});

it("§1.5 enablement: a LOCKED container refuses ungroup", () => {
  const locked = withNodeField("group_proof", "locked", true);
  assert.equal(arrangeEnablement(locked, ["group_proof"]).ungroup, false);
});

/* ── ⌘G / ⇧⌘G ────────────────────────────────────────────────────────────── */

it("§1.5 shortcut: ⌘G groups, ⇧⌘G ungroups, and Ctrl is the same key on a PC", () => {
  assert.equal(
    arrangeShortcut({ ctrlKey: false, key: "g", metaKey: true, shiftKey: false }, null),
    "group",
  );
  // Shift+G reports the UPPERCASE key, exactly as the ⌘Z handler's
  // `toLowerCase()` already assumes for ⇧⌘Z.
  assert.equal(
    arrangeShortcut({ ctrlKey: false, key: "G", metaKey: true, shiftKey: true }, null),
    "ungroup",
  );
  assert.equal(
    arrangeShortcut({ ctrlKey: true, key: "g", metaKey: false, shiftKey: false }, null),
    "group",
  );
});

it("§1.5 shortcut: a bare G, another modified key, and no modifier at all are not ours", () => {
  assert.equal(
    arrangeShortcut({ ctrlKey: false, key: "g", metaKey: false, shiftKey: false }, null),
    null,
  );
  assert.equal(
    arrangeShortcut({ ctrlKey: false, key: "z", metaKey: true, shiftKey: false }, null),
    null,
  );
});

it("§1.5 shortcut: a typing target keeps its own ⌘G — the SAME skip rules as ⌘Z", () => {
  // `use-scene-inspector-writes.ts:379-387`: contenteditable, INPUT, TEXTAREA.
  for (const target of [
    { isContentEditable: true, tagName: "DIV" },
    { isContentEditable: false, tagName: "INPUT" },
    { isContentEditable: false, tagName: "TEXTAREA" },
  ]) {
    assert.equal(
      arrangeShortcut(
        { ctrlKey: false, key: "g", metaKey: true, shiftKey: false },
        target,
      ),
      null,
      target.tagName,
    );
  }
  // A plain element is not a typing target.
  assert.equal(
    arrangeShortcut(
      { ctrlKey: false, key: "g", metaKey: true, shiftKey: false },
      { isContentEditable: false, tagName: "BUTTON" },
    ),
    "group",
  );
});

/* ── ⌘] / ⌘[ / ⌥⌘] / ⌥⌘[ (contract §1.5's z-order shortcuts) ─────────────── */

/** Build a bracket event the way a real macOS browser reports it.
 *
 * THIS HELPER IS THE POINT OF THE WHOLE SET. On a US layout ⌥ REWRITES `key`:
 * ⌥] is "‘" (U+2018) and ⌥[ is "“" (U+201C) — the character the layout
 * produces — while `code` stays the PHYSICAL key. A keymap written against
 * `key` (as the MVP editor's `keyboardArrangeAction`
 * (`subsystems/clue-design/apps/editor/src/engine/editorKeyboard.ts:55-60`,
 * READ-ONLY) is) therefore matches ⌘]/⌘[ and silently never matches
 * ⌥⌘]/⌥⌘[. Every case below states the `key` a real event would carry, so a
 * regression back to key-matching fails here rather than in a founder's hands.
 */
function bracketEvent(
  physical: "BracketLeft" | "BracketRight",
  modifiers: { alt?: boolean; ctrl?: boolean; meta?: boolean; shift?: boolean },
): {
  altKey: boolean;
  code: string;
  ctrlKey: boolean;
  key: string;
  metaKey: boolean;
  shiftKey: boolean;
} {
  const alt = modifiers.alt ?? false;
  const shift = modifiers.shift ?? false;
  const plain = physical === "BracketRight" ? "]" : "[";
  const shifted = physical === "BracketRight" ? "}" : "{";
  const optioned = physical === "BracketRight" ? "‘" : "“";
  const optionShifted = physical === "BracketRight" ? "’" : "”";
  return {
    altKey: alt,
    code: physical,
    ctrlKey: modifiers.ctrl ?? false,
    key: alt ? (shift ? optionShifted : optioned) : shift ? shifted : plain,
    metaKey: modifiers.meta ?? false,
    shiftKey: shift,
  };
}

it("§1.5 shortcut: ⌘] forward, ⌘[ backward, ⌥⌘] to front, ⌥⌘[ to back", () => {
  assert.equal(
    zOrderShortcut(bracketEvent("BracketRight", { meta: true }), null),
    "forward",
  );
  assert.equal(
    zOrderShortcut(bracketEvent("BracketLeft", { meta: true }), null),
    "backward",
  );
  // ⌥ held: `key` is now a curly quote, so ONLY a `code` match can still see
  // the bracket. This pair is the one the contract row would otherwise lose.
  assert.equal(
    zOrderShortcut(bracketEvent("BracketRight", { alt: true, meta: true }), null),
    "front",
  );
  assert.equal(
    zOrderShortcut(bracketEvent("BracketLeft", { alt: true, meta: true }), null),
    "back",
  );
  // Ctrl is the same key on a PC — the ⌘G pair's own rule.
  assert.equal(
    zOrderShortcut(bracketEvent("BracketRight", { ctrl: true }), null),
    "forward",
  );
  assert.equal(
    zOrderShortcut(bracketEvent("BracketLeft", { alt: true, ctrl: true }), null),
    "back",
  );
});

it("§1.5 shortcut: a bracket with no modifier, with ⇧, or another key is not ours", () => {
  // No ⌘/Ctrl: a bare bracket is typing, not arranging.
  assert.equal(zOrderShortcut(bracketEvent("BracketRight", {}), null), null);
  // ⇧⌘] / ⇧⌘[ are the BROWSER's next/previous tab on macOS and the contract
  // names only the four unshifted combos, so they stay the browser's.
  assert.equal(
    zOrderShortcut(bracketEvent("BracketRight", { meta: true, shift: true }), null),
    null,
  );
  assert.equal(
    zOrderShortcut(
      bracketEvent("BracketLeft", { alt: true, meta: true, shift: true }),
      null,
    ),
    null,
  );
  // ⌘G is the other function's; this one must not claim it.
  assert.equal(
    zOrderShortcut(
      { altKey: false, code: "KeyG", ctrlKey: false, key: "g", metaKey: true, shiftKey: false },
      null,
    ),
    null,
  );
});

it("§1.5 shortcut: an unmodified bracket still matches by `key` on a non-US layout", () => {
  // `code` is the physical key, so on a layout where the bracket does NOT sit
  // on BracketLeft/BracketRight the `key` half carries ⌘]/⌘[. (The ⌥ pair
  // cannot be rescued this way — ⌥ rewrites `key` — which is why `code` is the
  // primary match and this is only the fallback.)
  assert.equal(
    zOrderShortcut(
      { altKey: false, code: "Digit9", ctrlKey: false, key: "]", metaKey: true, shiftKey: false },
      null,
    ),
    "forward",
  );
  assert.equal(
    zOrderShortcut(
      { altKey: false, code: "Digit8", ctrlKey: false, key: "[", metaKey: true, shiftKey: false },
      null,
    ),
    "backward",
  );
});

it("§1.5 shortcut: a typing target keeps its own ⌘] — the SAME skip rules as ⌘G", () => {
  for (const target of [
    { isContentEditable: true, tagName: "DIV" },
    { isContentEditable: false, tagName: "INPUT" },
    { isContentEditable: false, tagName: "TEXTAREA" },
  ]) {
    assert.equal(
      zOrderShortcut(bracketEvent("BracketRight", { meta: true }), target),
      null,
      target.tagName,
    );
    assert.equal(
      zOrderShortcut(bracketEvent("BracketLeft", { alt: true, meta: true }), target),
      null,
      target.tagName,
    );
  }
  assert.equal(
    zOrderShortcut(bracketEvent("BracketRight", { meta: true }), {
      isContentEditable: false,
      tagName: "BUTTON",
    }),
    "forward",
  );
});

it("§1.5 shortcut: every mapped combo names a REAL z-order action", () => {
  // The four intents are the same vocabulary the buttons and `zOrderOperation`
  // use, so a keypress can only ask for a step the section already offers.
  const mapped: ZOrderAction[] = [
    zOrderShortcut(bracketEvent("BracketRight", { meta: true }), null)!,
    zOrderShortcut(bracketEvent("BracketLeft", { meta: true }), null)!,
    zOrderShortcut(bracketEvent("BracketRight", { alt: true, meta: true }), null)!,
    zOrderShortcut(bracketEvent("BracketLeft", { alt: true, meta: true }), null)!,
  ];
  const enablement = arrangeEnablement(SCENE, ["rect_accent_bar"]);
  for (const action of mapped) {
    assert.equal(
      typeof enablement.zOrder[action],
      "boolean",
      `${action} must be one of the section's four z-order flags`,
    );
    assert.equal(
      zOrderOperation(SCENE, "rect_accent_bar", action)?.kind,
      "move_node",
      `${action} must build the same operation the button builds`,
    );
  }
  assert.deepEqual(new Set(mapped).size, 4, "the four combos must not collide");
});
