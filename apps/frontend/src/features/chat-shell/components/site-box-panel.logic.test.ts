// The site element inspector's box panel (plan 4): Fill, Stroke and Layout as plan 3's button box, plus
// gap and content alignment, and which keys a section's own box writes (ruling R2).
import assert from "node:assert/strict";
import { test } from "node:test";
import type { ComputedContainer } from "@clue/site-kit/editor-protocol";
import { ALIGN_ROOM_NOTE, BOX_GAP_NOTE, SECTION_WIDTH_NOTE, boxPanelPatch, boxPanelValues, boxTargets } from "./site-box-panel.logic";

const card: ComputedContainer = {
  fill: "#FFFFFF", fillOpacity: 100, borderColor: "", borderWidth: 0, radius: [12, 12, 12, 12], paddingY: 24, paddingX: 32, width: 480, height: 200,
  gap: 16, layout: "grid", contentAlign: "start", name: "Card",
};

test("values come from the override over the drawn box", () => {
  const drawn = boxPanelValues(null, card, []);
  assert.deepEqual([drawn.fill, drawn.paddingY, drawn.paddingX, drawn.radius, drawn.gap, drawn.contentAlign, drawn.layout], ["#FFFFFF", "24", "32", "12", "16", "start", "grid"]);
  const set = boxPanelValues({ gap: 8, contentAlign: { along: "grid", to: "end" }, padding: 10 }, card, []);
  assert.deepEqual([set.gap, set.contentAlign, set.paddingY, set.paddingX], ["8", "end", "10", "10"]);
});

test("gap is live only for rows, stacks and grids", () => {
  for (const layout of ["row", "stack", "grid"] as const) assert.equal(boxPanelValues(null, { ...card, layout }, []).gapLive, true);
  assert.equal(boxPanelValues(null, { ...card, layout: "text" }, []).gapLive, false);
  assert.equal(boxPanelPatch(null, { kind: "gap", value: "12" }, { ...card, layout: "text" }), null, "no gap where the browser ignores it");
  assert.equal(BOX_GAP_NOTE, "This box stacks its contents with the brand's spacing; gap applies to rows and grids.");
});

test("content alignment writes the drawn layout with it", () => {
  assert.deepEqual(boxPanelPatch(null, { kind: "contentAlign", to: "center" }, card), { contentAlign: { along: "grid", to: "center" } });
  assert.deepEqual(boxPanelPatch({ gap: 4 }, { kind: "contentAlign", to: "end" }, { ...card, layout: "stack" }), { gap: 4, contentAlign: { along: "stack", to: "end" } });
  const same = { contentAlign: { along: "grid" as const, to: "center" as const } };
  assert.equal(boxPanelPatch(same, { kind: "contentAlign", to: "center" }, card), same, "no change: the same override");
});

test("padding, gap and radius refuse 201 with no value; gap and box changes are written", () => {
  assert.equal(boxPanelPatch(null, { kind: "gap", value: "201" }, card), null);
  assert.equal(boxPanelPatch(null, { kind: "paddingY", value: "201" }, card), null);
  assert.equal(boxPanelPatch(null, { kind: "radius", value: "201" }, card), null);
  assert.deepEqual(boxPanelPatch(null, { kind: "gap", value: "24px" }, card), { gap: 24 });
  assert.deepEqual(boxPanelPatch(null, { kind: "fillHex", hex: "#112233" }, card), { fill: { hex: "#112233", opacity: 100 } });
});

test("no change returns the same override", () => {
  const override = { gap: 16 };
  assert.equal(boxPanelPatch(override, { kind: "gap", value: "16" }, card), override);
});

test("which keys each part writes: a box both on itself; a section's fill and stroke on its outer box, its layout on its inner box", () => {
  const element = { key: "card", kind: "container" as const, label: "Card", computed: {} as never, container: card };
  const forBox = boxTargets({ element, elementOverride: { gap: 4 }, sectionBox: null, sectionBoxOverrides: { inner: null, outer: null } });
  assert.deepEqual([forBox?.paint.key, forBox?.layout.key, forBox?.layout.override, forBox?.layout.widthNote], ["card", "card", { gap: 4 }, null]);
  const sectionBox = { outer: { key: "root", box: card }, inner: { key: "root.inner", container: { ...card, name: "Box" } } };
  const forSection = boxTargets({ element: null, elementOverride: null, sectionBox, sectionBoxOverrides: { outer: { fill: { token: "x" } }, inner: { padding: 40 } } });
  assert.deepEqual([forSection?.paint.key, forSection?.paint.override, forSection?.layout.key, forSection?.layout.override, forSection?.layout.widthNote], ["root", { fill: { token: "x" } }, "root.inner", { padding: 40 }, SECTION_WIDTH_NOTE]);
  assert.equal(SECTION_WIDTH_NOTE, "A section always spans the page.");
  assert.equal(boxTargets({ element: { ...element, kind: "image", container: null }, elementOverride: null, sectionBox: null, sectionBoxOverrides: { inner: null, outer: null } }), null);
});

test("review I5: a box as wide as its contents offers no content alignment, and says why", () => {
  const hugging = { ...card, layout: "row" as const, alignRoom: false };
  assert.equal(boxPanelValues(null, hugging, []).alignLive, false);
  assert.equal(boxPanelValues(null, { ...card, alignRoom: true }, []).alignLive, true);
  assert.equal(boxPanelValues(null, card, []).alignLive, true, "unknown room counts as room");
  assert.equal(boxPanelPatch(null, { kind: "contentAlign", to: "center" }, hugging), null);
  assert.equal(ALIGN_ROOM_NOTE, "This box is only as wide as its contents, so they have no room to line up. Set its width to Fill first.");
});
