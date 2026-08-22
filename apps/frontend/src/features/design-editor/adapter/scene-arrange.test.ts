import assert from "node:assert/strict";
import { it } from "node:test";
import type { Node, Scene } from "../engine/scene/contracts";
import { moveNodeToParent } from "../engine/scene/operations";
import {
  canAlignNodes,
  canDistributeNodes,
  canGroupNodes,
  canUngroupNode,
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
 * `withNodeField`), so a locked/relocated case is still harvested bytes. */
function withNodeField<Field extends keyof Node>(
  nodeId: string,
  field: Field,
  value: Node[Field],
): Scene {
  const scene = clone(SCENE);
  const node = scene.nodes[nodeId];
  assert.ok(node, `fixture node ${nodeId} missing`);
  node[field] = value;
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

it("§1.5 enablement: align needs 2+, distribute needs 3+, and both defer to the ENGINE's own gate", () => {
  const two = ["rect_accent_bar", "line_divider"];
  const three = [...two, "image_hero"];
  assert.equal(arrangeEnablement(SCENE, ["rect_accent_bar"]).align, false);
  assert.equal(arrangeEnablement(SCENE, two).align, true);
  assert.equal(arrangeEnablement(SCENE, two).distribute, false);
  assert.equal(arrangeEnablement(SCENE, three).distribute, true);
  // The gate is never re-implemented — these ARE `canAlignNodes` /
  // `canDistributeNodes`, so a rule change upstream moves the buttons.
  assert.equal(arrangeEnablement(SCENE, three).align, canAlignNodes(SCENE, three));
  assert.equal(
    arrangeEnablement(SCENE, three).distribute,
    canDistributeNodes(SCENE, three),
  );
});

it("§1.5 enablement: a LOCKED member refuses align and distribute for the whole set", () => {
  const locked = withNodeField("line_divider", "locked", true);
  const three = ["rect_accent_bar", "line_divider", "image_hero"];
  assert.equal(arrangeEnablement(locked, three).align, false);
  assert.equal(arrangeEnablement(locked, three).distribute, false);
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
