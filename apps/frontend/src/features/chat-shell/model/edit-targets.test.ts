import assert from "node:assert/strict";
import test from "node:test";
import type { Scene } from "@/features/design-editor/engine/scene/contracts";
import { HARVESTED_AD_PAGE } from "@/features/design-editor/adapter/__fixtures__/scene-nodes";
import {
  annotationChips,
  annotationContextRefs,
  editTargetChips,
  editTargetContextRefs,
} from "./edit-targets";

test("edit-target chips mirror ordered selection and use document node names", () => {
  const scene = HARVESTED_AD_PAGE as Scene;
  const ids = ["text_headline", "missing_after_reload"];

  // A node the live scene no longer carries drops off the bar entirely — the
  // same filter the submission snapshot applies, so a chip is always a
  // submittable target, never a stale id the server would refuse.
  assert.deepEqual(editTargetChips(scene, ids), [
    { label: scene.nodes.text_headline.name, nodeId: "text_headline" },
  ]);
});

test("edit-target chips need a scene to name targets against", () => {
  assert.deepEqual(editTargetChips(null, ["text_headline"]), []);
});

test("the target context snapshot keeps one version across document and ordered nodes", () => {
  const refs = editTargetContextRefs({
    documentId: "doc_ad",
    documentVersion: 12,
    targetNodeIds: ["headline", "logo"],
  });

  assert.deepEqual(refs, [
    { objectId: "doc_ad", objectType: "design_document", version: 12 },
    { objectId: "headline", objectType: "design_node", version: 12 },
    { objectId: "logo", objectType: "design_node", version: 12 },
  ]);
});

test("annotations become one document ref plus ordered noted node refs; chips are numbered", () => {
  const items = [
    {
      n: 2,
      note: "Make the headline shorter and punchier please",
      address: { nodeId: "frg_a", path: ":nth-child(1)", tag: "h2" },
      name: "h2",
      pageId: "home",
      textLike: true,
    },
    {
      n: 3,
      note: "Remove",
      address: { nodeId: "sec_b", tag: "section" },
      name: "Proof",
      pageId: "home",
      textLike: false,
    },
  ];

  assert.deepEqual(
    annotationContextRefs({ documentId: "doc_1", documentVersion: 9, items }),
    [
      { objectId: "doc_1", objectType: "design_document", version: 9 },
      {
        objectId: "frg_a#:nth-child(1)",
        objectType: "design_node",
        version: 9,
        note: "2. Make the headline shorter and punchier please",
      },
      { objectId: "sec_b", objectType: "design_node", version: 9, note: "3. Remove" },
    ],
  );
  assert.deepEqual(annotationChips(items), [
    { n: 2, label: "Make the headline shorter an\u2026" },
    { n: 3, label: "Remove" },
  ]);
});
