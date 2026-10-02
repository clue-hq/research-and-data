import assert from "node:assert/strict";
import test from "node:test";
import { AD_DOCUMENT_ID, adImage, adTokenText } from "../adapter/__fixtures__/scene-nodes";
import { sceneImagePlacementOperations } from "../adapter/scene-apply";
import type { AssetRecord, Node, Operation } from "../engine/scene/contracts";
import { NOT_ACCEPTING_EDITS, NOT_AN_IMAGE_TARGET, SAME_IMAGE_IN_USE } from "./use-scene-replace-image";
import { createSceneAssetLibraryPick } from "./use-scene-asset-library";

const LOGO: AssetRecord = { id: "asset_logo", kind: "logo", label: "Cursor mark", status: "ready",
  source: { kind: "uploaded", filename: "mark.svg", uploaded_by: null } };

function picker(over: Partial<{ armed: boolean; node: Node | null; documentId: string | null }> = {}) {
  const applied: { intent?: string; operations: Operation[] }[] = [];
  const errors: string[] = [];
  const deps = () => ({
    applyOps: (operations: Operation[], intent?: string) => { applied.push({ intent, operations }); return true; },
    canApply: () => over.armed ?? true,
    documentId: over.documentId === undefined ? AD_DOCUMENT_ID : over.documentId,
    node: over.node === undefined ? (adImage() as Node) : over.node,
    onError: (m: string) => { errors.push(m); },
  });
  const pick = createSceneAssetLibraryPick(deps, (id) => (id === LOGO.id ? LOGO : null));
  return { applied, errors, pick };
}

test("a pick applies exactly the upload path's placement batch, once, as its own intent", () => {
  const { applied, errors, pick } = picker();
  assert.equal(pick(LOGO.id), true);
  assert.equal(applied.length, 1);
  assert.equal(applied[0].intent, "inspector: replace image from library");
  assert.deepEqual(applied[0].operations, sceneImagePlacementOperations(adImage() as Node, LOGO));
  assert.deepEqual(applied[0].operations.map((op) => op.kind), ["upsert_asset", "place_asset_in_node"]);
  assert.deepEqual(errors, []);
});

test("picking the asset already in use speaks and applies nothing", () => {
  const same = adImage() as Node;
  if (same.kind.kind === "image") same.kind.asset_id = LOGO.id;
  const { applied, errors, pick } = picker({ node: same });
  assert.equal(pick(LOGO.id), false);
  assert.deepEqual(applied, []);
  assert.deepEqual(errors, [SAME_IMAGE_IN_USE]);
});

test("guards speak with the replace path's own sentences", () => {
  const unarmed = picker({ armed: false });
  assert.equal(unarmed.pick(LOGO.id), false);
  assert.deepEqual(unarmed.errors, [NOT_ACCEPTING_EDITS]);
  const text = picker({ node: adTokenText() as Node });
  assert.equal(text.pick(LOGO.id), false);
  assert.deepEqual(text.errors, [NOT_AN_IMAGE_TARGET]);
  const noDoc = picker({ documentId: null });
  assert.equal(noDoc.pick(LOGO.id), false);
  assert.deepEqual(noDoc.errors, [NOT_ACCEPTING_EDITS]);
});

test("an unknown asset id is a refusal, not a throw", () => {
  const { applied, errors, pick } = picker();
  assert.equal(pick("asset_nope"), false);
  assert.deepEqual(applied, []);
  assert.deepEqual(errors, ["That image is no longer in the library."]);
});
