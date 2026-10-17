import assert from "node:assert/strict";
import { test } from "node:test";
import { boldAvailable, textPanelPatch, textPanelValues, weightOptions } from "./site-text-panel.logic";

const computed = { color: "#0E1110", fontFamily: "Stix Two Text", fontSize: 47.63, fontWeight: 400, italic: false, underline: false, textAlign: "left" as const };
const palette = [{ label: "text.heading", value: "#014036" }, { label: "text.primary", value: "#0E1110" }];
const fonts = [{ family: "Stix Two Text", weights: [400, 600] }, { family: "Inter", weights: [300, 400, 700, 900] }];

test("with no override the panel shows what the browser draws", () => {
  assert.deepEqual(textPanelValues(null, computed, palette), {
    color: "#0E1110", colorToken: null, opacity: "100%", fontFamily: "Stix Two Text", fontSize: "47.6",
    fontWeight: "400 Regular", bold: false, italic: false, underline: false, textAlign: "left",
  });
});

test("the override wins: a token shows its colour and name, a custom colour its hex and opacity", () => {
  const token = textPanelValues({ color: { token: "text.heading" }, fontSize: 48, fontWeight: 700, italic: true, textAlign: "center" }, computed, palette);
  assert.equal(token.color, "#014036");
  assert.equal(token.colorToken, "text.heading");
  assert.equal(token.fontSize, "48");
  assert.equal(token.fontWeight, "700 Bold");
  assert.equal(token.bold, true);
  assert.equal(token.italic, true);
  assert.equal(token.textAlign, "center");
  const custom = textPanelValues({ color: { hex: "#0F59B0", opacity: 80 } }, computed, palette);
  assert.deepEqual([custom.color, custom.colorToken, custom.opacity], ["#0F59B0", null, "80%"]);
});

test("colour changes: a token replaces any colour; a hex keeps the current opacity; opacity on a brand colour starts from what is drawn", () => {
  assert.deepEqual(textPanelPatch({ color: { hex: "#000000", opacity: 50 } }, { kind: "colorToken", token: "text.heading" }, computed, fonts), { color: { token: "text.heading" } });
  assert.deepEqual(textPanelPatch({ color: { hex: "#000000", opacity: 50 } }, { kind: "colorHex", hex: "#0f59b0" }, computed, fonts), { color: { hex: "#0F59B0", opacity: 50 } });
  assert.deepEqual(textPanelPatch(null, { kind: "colorHex", hex: "#0F59B0" }, computed, fonts), { color: { hex: "#0F59B0", opacity: 100 } });
  assert.deepEqual(textPanelPatch({ color: { token: "text.heading" } }, { kind: "opacity", value: "60%" }, computed, fonts), { color: { hex: "#0E1110", opacity: 60 } });
  assert.equal(textPanelPatch(null, { kind: "colorHex", hex: "red" }, computed, fonts), null);
  assert.equal(textPanelPatch(null, { kind: "opacity", value: "120%" }, computed, fonts), null);
});

test("size: a number from 8 to 200 (px allowed); anything else is refused, never clamped", () => {
  assert.deepEqual(textPanelPatch(null, { kind: "fontSize", value: "48" }, computed, fonts), { fontSize: 48 });
  assert.deepEqual(textPanelPatch(null, { kind: "fontSize", value: "18.5px" }, computed, fonts), { fontSize: 18.5 });
  for (const bad of ["7", "201", "abc", "", "-12"]) assert.equal(textPanelPatch(null, { kind: "fontSize", value: bad }, computed, fonts), null, bad);
});

test("font and weight: only the brand's families; a weight the new family lacks is dropped; a weight must be the family's", () => {
  assert.deepEqual(textPanelPatch({ fontWeight: 600 }, { kind: "fontFamily", value: "Inter" }, computed, fonts), { fontFamily: "Inter" });
  assert.deepEqual(textPanelPatch({ fontWeight: 700 }, { kind: "fontFamily", value: "Inter" }, computed, fonts), { fontFamily: "Inter", fontWeight: 700 });
  assert.equal(textPanelPatch(null, { kind: "fontFamily", value: "Comic Sans" }, computed, fonts), null);
  assert.deepEqual(textPanelPatch(null, { kind: "fontWeight", value: "600 Semi Bold" }, computed, fonts), { fontWeight: 600 });
  assert.equal(textPanelPatch(null, { kind: "fontWeight", value: "700 Bold" }, computed, fonts), null, "Stix Two Text has no 700");
});

test("bold on takes the family's bold (or its heaviest); off is an explicit regular weight, so bold-by-default text stops being bold", () => {
  assert.deepEqual(textPanelPatch(null, { kind: "bold", on: true }, computed, fonts), { fontWeight: 600 });
  assert.deepEqual(textPanelPatch({ fontFamily: "Inter" }, { kind: "bold", on: true }, computed, fonts), { fontFamily: "Inter", fontWeight: 700 });
  assert.deepEqual(textPanelPatch(null, { kind: "bold", on: false }, { ...computed, fontWeight: 700, fontFamily: "Inter" }, fonts), { fontWeight: 400 });
});

test("italic, underline and alignment set their value, off included", () => {
  assert.deepEqual(textPanelPatch({ italic: true }, { kind: "italic", on: false }, computed, fonts), { italic: false });
  assert.deepEqual(textPanelPatch(null, { kind: "underline", on: true }, computed, fonts), { underline: true });
  assert.deepEqual(textPanelPatch(null, { kind: "textAlign", value: "justify" }, computed, fonts), { textAlign: "justify" });
});

test("the weight list is the family's own, labelled like the ad editor's", () => {
  assert.deepEqual(weightOptions(fonts, "Inter"), ["300 Light", "400 Regular", "700 Bold", "900 Black"]);
  assert.equal(weightOptions(fonts, "Unknown").length, 9);
});

test("choosing the font, weight, size or alignment the text already shows changes nothing (no save, no undo step)", () => {
  // The override comes back as it was (not null, which means "refused" and shows a note).
  assert.deepEqual(textPanelPatch(null, { kind: "fontFamily", value: "Stix Two Text" }, computed, fonts), {});
  assert.deepEqual(textPanelPatch(null, { kind: "fontWeight", value: "400 Regular" }, computed, fonts), {});
  assert.deepEqual(textPanelPatch(null, { kind: "textAlign", value: "left" }, computed, fonts), {});
  assert.deepEqual(textPanelPatch({ fontSize: 48 }, { kind: "fontSize", value: "48" }, computed, fonts), { fontSize: 48 });
  assert.deepEqual(textPanelPatch(null, { kind: "fontSize", value: "47.6" }, computed, fonts), {}, "the size as shown, rounded");
  assert.deepEqual(textPanelPatch(null, { kind: "fontFamily", value: "Inter" }, computed, fonts), { fontFamily: "Inter" });
});

test("bold is the font's boldest weight when it has no 700: B shows pressed at it, and is unavailable for a font with nothing heavier than regular", () => {
  const capped = [{ family: "seasonFont", weights: [400, 500] }, { family: "Flat", weights: [400] }];
  const season = { ...computed, fontFamily: "seasonFont", fontWeight: 400 };
  const on = textPanelPatch(null, { kind: "bold", on: true }, season, capped);
  assert.deepEqual(on, { fontWeight: 500 });
  assert.equal(textPanelValues(on, season, palette, capped).bold, true, "at the font's boldest weight, B is pressed");
  assert.equal(boldAvailable(capped, "seasonFont"), true);
  assert.equal(boldAvailable(capped, "Flat"), false);
  assert.equal(boldAvailable(capped, "Unknown family"), true, "a family we do not know offers every weight");
});
