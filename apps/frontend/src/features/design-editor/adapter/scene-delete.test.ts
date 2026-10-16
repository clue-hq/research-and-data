import assert from "node:assert/strict";
import { it } from "node:test";
import type { Scene } from "../engine/scene/contracts";
import {
  loadWasmModuleFromDisk,
  wasmArtifactPresent,
} from "../engine/scene/__tests__/wasm-module-loader";
import { WasmEngine } from "../engine/scene/wasmEngine";
import { AD_PAGE_ID, HARVESTED_AD_PAGE } from "./__fixtures__/scene-nodes";
import { deleteShortcut, planSceneDelete } from "./scene-delete";

/*
 * The harvested ad's tree:
 *   frame_ad_root "Ad artboard"
 *     auto_row_copy "Copy row"
 *       text_headline "Headline"
 *       group_proof "Proof point"
 *         ellipse_proof_dot "Accent dot"
 *         text_proof_stat "Proof stat"
 *     rect_accent_bar "Accent bar"
 *     line_divider "Divider"
 *     image_hero "Hero image"
 */

const clone = (): Scene => structuredClone(HARVESTED_AD_PAGE);

function locking(id: string): Scene {
  const scene = clone();
  scene.nodes[id] = { ...scene.nodes[id]!, locked: true };
  return scene;
}

const plan = (scene: Scene, ids: string[]) =>
  planSceneDelete(scene, AD_PAGE_ID, ids, "⌘Z");

const KEY = {
  altKey: false,
  ctrlKey: false,
  key: "Backspace",
  metaKey: false,
  repeat: false,
  shiftKey: false,
};
const BODY = { isContentEditable: false, tagName: "BODY" };

it("delete key: Backspace (Mac's delete) and Delete both count, from the page body", () => {
  assert.equal(deleteShortcut(KEY, BODY), true);
  assert.equal(deleteShortcut({ ...KEY, key: "Delete" }, BODY), true);
  assert.equal(deleteShortcut(KEY, null), true);
  assert.equal(deleteShortcut({ ...KEY, key: "d" }, BODY), false);
});

it("delete key: any modifier, a held key, or a focused field is not ours", () => {
  for (const modifier of ["altKey", "ctrlKey", "metaKey", "shiftKey"] as const) {
    assert.equal(deleteShortcut({ ...KEY, [modifier]: true }, BODY), false, modifier);
  }
  assert.equal(deleteShortcut({ ...KEY, repeat: true }, BODY), false);
  for (const tagName of ["INPUT", "TEXTAREA", "SELECT"]) {
    assert.equal(deleteShortcut(KEY, { isContentEditable: false, tagName }), false, tagName);
  }
  assert.equal(deleteShortcut(KEY, { isContentEditable: true, tagName: "DIV" }), false);
});

it("plan: a single leaf element is removed with no note", () => {
  assert.deepEqual(plan(clone(), ["image_hero"]), {
    kind: "delete",
    operations: [{ kind: "remove_node", node_id: "image_hero" }],
    note: null,
  });
});

it("plan: a container goes with everything inside it, and the note says how much", () => {
  assert.deepEqual(plan(clone(), ["auto_row_copy"]), {
    kind: "delete",
    operations: [{ kind: "remove_node", node_id: "auto_row_copy" }],
    note: 'Deleted "Copy row" and 4 elements inside it. ⌘Z to undo.',
  });
  const group = plan(clone(), ["group_proof"]);
  assert.equal(group.kind === "delete" && group.note, 'Deleted "Proof point" and 2 elements inside it. ⌘Z to undo.');
});

it("plan: the note prints the undo chord it is given", () => {
  const result = planSceneDelete(clone(), AD_PAGE_ID, ["group_proof"], "Ctrl+Z");
  assert.equal(result.kind === "delete" && result.note, 'Deleted "Proof point" and 2 elements inside it. Ctrl+Z to undo.');
});

it("plan: several selected elements go in one batch", () => {
  assert.deepEqual(plan(clone(), ["image_hero", "rect_accent_bar"]), {
    kind: "delete",
    operations: [
      { kind: "remove_node", node_id: "image_hero" },
      { kind: "remove_node", node_id: "rect_accent_bar" },
    ],
    note: null,
  });
  const mixed = plan(clone(), ["image_hero", "group_proof"]);
  assert.equal(mixed.kind === "delete" && mixed.note, "Deleted 2 elements and 2 elements inside them. ⌘Z to undo.");
});

it("plan: a selected node inside another selected node is not removed twice", () => {
  const result = plan(clone(), ["text_proof_stat", "auto_row_copy", "group_proof"]);
  assert.equal(result.kind, "delete");
  assert.deepEqual(result.kind === "delete" && result.operations, [
    { kind: "remove_node", node_id: "auto_row_copy" },
  ]);
});

it("plan: the artboard is never deleted, alone or alongside other elements", () => {
  assert.deepEqual(plan(clone(), ["frame_ad_root"]), { kind: "none" });
  assert.deepEqual(plan(clone(), ["frame_ad_root", "image_hero"]), {
    kind: "delete",
    operations: [{ kind: "remove_node", node_id: "image_hero" }],
    note: null,
  });
});

it("plan: no scene, no selection, or a node the scene no longer carries is a non-event", () => {
  assert.deepEqual(planSceneDelete(null, AD_PAGE_ID, ["image_hero"], "⌘Z"), { kind: "none" });
  assert.deepEqual(plan(clone(), []), { kind: "none" });
  assert.deepEqual(plan(clone(), ["node_gone"]), { kind: "none" });
});

it("plan: a locked element, or a container with a locked element inside, is refused whole", () => {
  assert.deepEqual(plan(locking("image_hero"), ["image_hero"]), {
    kind: "refuse",
    note: '"Hero image" is locked, so it can\'t be deleted.',
  });
  assert.deepEqual(plan(locking("text_proof_stat"), ["auto_row_copy"]), {
    kind: "refuse",
    note: '"Copy row" has a locked element inside it ("Proof stat"), so it can\'t be deleted.',
  });
  assert.equal(plan(locking("image_hero"), ["rect_accent_bar", "image_hero"]).kind, "refuse");
});

if (!wasmArtifactPresent) {
  console.log(
    "[scene-delete] the real-engine case SKIPPED — no wasm artifact at " +
      "public/vendor/wasm; run `node scripts/copy-design-vendor.mjs`.",
  );
}

it(
  "plan: the real engine takes the batch and the whole subtree is gone",
  { skip: !wasmArtifactPresent },
  async () => {
    const wasm = await loadWasmModuleFromDisk();
    const scene = clone();
    const result = plan(scene, ["auto_row_copy", "image_hero"]);
    assert.equal(result.kind, "delete");
    if (result.kind !== "delete") return;
    const outcome = new WasmEngine(wasm, scene).applyOperations(result.operations);
    assert.equal(outcome.accepted, true);
    for (const id of ["auto_row_copy", "text_headline", "group_proof", "ellipse_proof_dot", "text_proof_stat", "image_hero"]) {
      assert.equal(outcome.scene.nodes[id], undefined, `${id} survived`);
    }
    assert.deepEqual(outcome.scene.nodes.frame_ad_root?.children, ["rect_accent_bar", "line_divider"]);
  },
);
