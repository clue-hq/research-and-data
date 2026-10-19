// The site element inspector's image panel (plan 5): Fit (ruling R3) and the panel's own sections.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { ComputedImage } from "@clue/site-kit/editor-protocol";
import { boxTargets } from "./site-box-panel.logic";
import { FIT_SAME_NOTE, imageFitPatch, imagePanelValues } from "./site-image-panel.logic";

const box = { fill: "", borderColor: "", borderWidth: 0, radius: [0, 0, 0, 0], paddingY: 0, paddingX: 0, width: 400 };
const hero: ComputedImage = { media: "img", box, fit: "fill", fitMatters: true, alt: "", src: "/brands/x.png" };

test("fit values and patches; fit off when the shape does not change it", () => {
  assert.deepEqual(imagePanelValues(null, hero), { fit: "fill", fitLive: true });
  assert.deepEqual(imagePanelValues({ imageFit: "fit" }, hero), { fit: "fit", fitLive: true });
  assert.deepEqual(imagePanelValues(null, { ...hero, fitMatters: false }), { fit: "fill", fitLive: false });
  assert.deepEqual(imageFitPatch(null, "fit", hero), { imageFit: "fit" });
  const same = { imageFit: "fit" as const };
  assert.equal(imageFitPatch(same, "fit", hero), same, "no change: the same override");
  assert.equal(imageFitPatch(null, "fit", { ...hero, fitMatters: false }), null);
  assert.equal(FIT_SAME_NOTE, "This image is shown at its own shape, so Fill and Fit look the same here.");
});

test("an image's Stroke writes the image's own key, from its drawn box", () => {
  const element = { key: "image", kind: "image" as const, label: "Image", computed: {} as never, image: hero };
  const targets = boxTargets({ element, elementOverride: { radius: 8 }, sectionBox: null, sectionBoxOverrides: { inner: null, outer: null } });
  assert.deepEqual([targets?.paint.key, targets?.paint.override, targets?.paint.box], ["image", { radius: 8 }, box]);
});
