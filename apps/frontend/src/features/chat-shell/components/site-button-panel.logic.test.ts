import assert from "node:assert/strict";
import { test } from "node:test";
import { buttonPanelPatch, buttonPanelValues } from "./site-button-panel.logic";

const box = { fill: "#0F59B0", borderColor: "", borderWidth: 0, radius: [6, 6, 6, 6], paddingY: 12, paddingX: 22, width: 214 };
const palette = [{ label: "text.inverse", value: "#FFFFFF" }, { label: "surface.brand", value: "#014036" }];

test("with no override the panel shows the button as drawn", () => {
  assert.deepEqual(buttonPanelValues(null, box, palette), {
    fill: "#0F59B0", fillToken: null, fillOpacity: "100%", fillNone: false,
    stroke: "#000000", strokeToken: null, strokeOpacity: "100%", strokeNone: true, strokeWidth: "0",
    radiusMode: "number", radius: "6", corners: ["6", "6", "6", "6"],
    paddingY: "12", paddingX: "22", widthMode: "fit", width: "214",
  });
});

test("the override wins: tokens show their colour, pill and custom corners, fill width", () => {
  const values = buttonPanelValues(
    { fill: { token: "surface.brand" }, borderColor: { hex: "#000000", opacity: 50 }, borderWidth: 2, radius: "pill", padding: { y: 8, x: 16 }, width: "fill" },
    box,
    palette,
  );
  assert.deepEqual([values.fill, values.fillToken, values.stroke, values.strokeOpacity, values.strokeNone, values.strokeWidth], ["#014036", "surface.brand", "#000000", "50%", false, "2"]);
  assert.deepEqual([values.radiusMode, values.paddingY, values.paddingX, values.widthMode], ["pill", "8", "16", "fill"]);
  assert.deepEqual(buttonPanelValues({ radius: [0, 4, 8, 16] }, box, palette).corners, ["0", "4", "8", "16"]);
  assert.equal(buttonPanelValues({ radius: [0, 4, 8, 16] }, box, palette).radiusMode, "custom");
  assert.deepEqual([buttonPanelValues({ width: 320 }, box, palette).widthMode, buttonPanelValues({ width: 320 }, box, palette).width], ["fixed", "320"]);
});

test("colours: a token or a hex; opacity on a brand colour starts from what is drawn", () => {
  assert.deepEqual(buttonPanelPatch(null, { kind: "fillToken", token: "text.inverse" }, box), { fill: { token: "text.inverse" } });
  assert.deepEqual(buttonPanelPatch(null, { kind: "fillHex", hex: "#ff0000" }, box), { fill: { hex: "#FF0000", opacity: 100 } });
  assert.deepEqual(buttonPanelPatch(null, { kind: "fillOpacity", value: "40%" }, box), { fill: { hex: "#0F59B0", opacity: 40 } });
  assert.deepEqual(buttonPanelPatch(null, { kind: "strokeHex", hex: "#000000" }, box), { borderColor: { hex: "#000000", opacity: 100 }, borderWidth: 1 }, "a stroke colour on a button with none gives it a 1 px stroke");
  assert.equal(buttonPanelPatch(null, { kind: "fillHex", hex: "blue" }, box), null);
});

test("sizes: numbers within range; anything else refused, never clamped", () => {
  assert.deepEqual(buttonPanelPatch(null, { kind: "strokeWidth", value: "3" }, box), { borderWidth: 3 });
  assert.deepEqual(buttonPanelPatch(null, { kind: "radius", value: "12" }, box), { radius: 12 });
  assert.deepEqual(buttonPanelPatch(null, { kind: "radiusPill" }, box), { radius: "pill" });
  assert.deepEqual(buttonPanelPatch(null, { kind: "corner", index: 2, value: "20" }, box), { radius: [6, 6, 20, 6] }, "custom corners start from what is drawn");
  assert.deepEqual(buttonPanelPatch({ radius: "pill" }, { kind: "radiusCustom" }, box), { radius: [6, 6, 6, 6] });
  assert.deepEqual(buttonPanelPatch(null, { kind: "paddingY", value: "8" }, box), { padding: { y: 8, x: 22 } });
  assert.deepEqual(buttonPanelPatch({ padding: 10 }, { kind: "paddingX", value: "30" }, box), { padding: { y: 10, x: 30 } });
  assert.deepEqual(buttonPanelPatch(null, { kind: "widthMode", value: "fill" }, box), { width: "fill" });
  assert.deepEqual(buttonPanelPatch(null, { kind: "widthMode", value: "fixed" }, box), { width: 214 }, "fixed starts at the width drawn");
  assert.deepEqual(buttonPanelPatch(null, { kind: "width", value: "320px" }, box), { width: 320 });
  for (const bad of [{ kind: "strokeWidth", value: "300" }, { kind: "radius", value: "-1" }, { kind: "paddingY", value: "abc" }, { kind: "width", value: "0" }, { kind: "corner", index: 1, value: "999" }] as const) {
    assert.equal(buttonPanelPatch(null, bad, box), null, JSON.stringify(bad));
  }
});

test("removing the stroke clears its colour and width; choosing what is shown changes nothing", () => {
  assert.deepEqual(buttonPanelPatch({ borderColor: { hex: "#000000", opacity: 100 }, borderWidth: 2, width: "fill" }, { kind: "strokeNone" }, box), { borderWidth: 0, width: "fill" });
  assert.deepEqual(buttonPanelPatch(null, { kind: "paddingY", value: "12" }, box), {}, "the padding shown");
  assert.deepEqual(buttonPanelPatch({ radius: "pill" }, { kind: "radiusPill" }, box), { radius: "pill" });
});

test("switching mode starts from what is drawn, within what can be written", () => {
  const pill = { ...box, radius: [9999, 9999, 9999, 9999], width: 2400, paddingX: 260 };
  assert.deepEqual(buttonPanelPatch({ radius: "pill" }, { kind: "radiusNumber" }, pill), { radius: 200 }, "a pill's drawn 9999px starts at the largest radius");
  assert.deepEqual(buttonPanelPatch(null, { kind: "radiusCustom" }, pill), { radius: [200, 200, 200, 200] });
  assert.deepEqual(buttonPanelPatch(null, { kind: "corner", index: 0, value: "4" }, pill), { radius: [4, 200, 200, 200] });
  assert.deepEqual(buttonPanelPatch(null, { kind: "widthMode", value: "fixed" }, pill), { width: 2000 });
  assert.deepEqual(buttonPanelPatch(null, { kind: "widthMode", value: "fixed" }, { ...box, width: 0 }), { width: 1 });
  assert.deepEqual(buttonPanelPatch(null, { kind: "paddingY", value: "10" }, pill), { padding: { y: 10, x: 200 } });
  assert.deepEqual(buttonPanelPatch({ radius: 8 }, { kind: "radiusNumber" }, box), { radius: 8 }, "already a number: nothing changes");
});
