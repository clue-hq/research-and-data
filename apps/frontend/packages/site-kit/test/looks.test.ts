// Looks are the brief's recipes joined to the kit's measured recipes (Wave 2 A9). Measured first,
// the recipe's tokens second, the standard button's part third.
import assert from "node:assert/strict";
import { test } from "node:test";
import { colorOf } from "../src/brand-values";
import { buttonLookOptions, buttonLooks, drawnButton, drawnLink, lookNamed, motionEntries, motionNotes } from "../src/looks";
import { surfaceChoices } from "../src/surfaces";
import { kitBrand } from "./fixtures/kits";

test("a brand's looks are its button recipes, named for the dock by kind", () => {
  assert.deepEqual(buttonLookOptions(kitBrand("garner")).map((o) => [o.label, o.value]), [
    ["Standard", ""], ["Outline", "outline.1"], ["Text only", "ghost.1"],
    ["Filled 1", "solid.1"], ["Filled 2", "solid.2"], ["Filled 3", "solid.3"], ["Filled 4", "solid.4"],
  ]);
  assert.deepEqual(buttonLookOptions(kitBrand("altcarbon")).map((o) => o.label), ["Standard", "Filled"]);
});

test("a measured kit's looks are named by their colour; the labels follow use, the names never do", () => {
  // probe.minted: every button style the real probe measured, all used once — so by name.
  assert.deepEqual(buttonLookOptions(kitBrand("probe.minted")).map((o) => [o.label, o.value]), [
    ["Standard", ""], ["Outline", "outline.0d2b25"],
    ["Filled 1", "solid.047464"], ["Filled 2", "solid.0a4a8a"], ["Filled 3", "solid.28241e"], ["Filled 4", "solid.7c4cff"],
  ]);
  // conduit.minted: the measured demo button (used 4 times) leads its kind; the recipes measured
  // before keep their old names and their old order after it.
  const filled = buttonLookOptions(kitBrand("conduit.minted")).filter((o) => o.label.startsWith("Filled"));
  assert.deepEqual(filled.map((o) => o.value), ["solid.28241e", "solid.1", "solid.3", "solid.4", "solid.5"]);
  assert.equal(filled[0].label, "Filled 1");
});

test("an old kit draws a look from its recipe's tokens, and the standard button where the recipe has none", () => {
  const conduit = kitBrand("conduit");
  const look = lookNamed(conduit, "button", "solid.2")!;
  assert.equal(look.measured, null);
  const drawn = drawnButton(conduit, look);
  assert.equal(drawn.parts.fill, "#7CE4FC", "no fill in the kit: the standard button's surface.brand");
  assert.equal(drawn.source.fill, "standard");
  assert.equal(drawn.parts.label, "#FFFFFF");
  assert.equal(drawn.tokens.label, "text.inverse");
  assert.equal(drawn.parts.radius, "8px 8px 8px 8px");
});

test("a measured kit draws Conduit's demo button warm dark, never surface.brand", () => {
  const conduit = kitBrand("conduit.minted");
  const look = lookNamed(conduit, "button", "solid.28241e")!;
  const drawn = drawnButton(conduit, look);
  assert.equal(drawn.parts.fill, "#28241E");
  assert.equal(drawn.tokens.fill, "surface.band.28241e");
  assert.equal(drawn.source.fill, "measured");
  assert.equal(drawn.parts.padding, "0px 10px 0px 10px");
  assert.equal(drawn.parts.height, "32px");
});

test("outline and text-only looks never take the standard button's fill or label", () => {
  const garner = kitBrand("garner");
  const outline = drawnButton(garner, lookNamed(garner, "button", "outline.1"));
  assert.equal(outline.parts.fill, "transparent");
  assert.equal(outline.parts.label, colorOf(garner, "text.primary"));
  assert.equal(outline.parts.borderWidth, "1px 1px 1px 1px");
  const ghost = drawnButton(garner, lookNamed(garner, "button", "ghost.1"));
  assert.equal(ghost.parts.fill, "transparent");
  assert.equal(ghost.parts.label, colorOf(garner, "text.primary"));
});

test("a text link is the site's most measured link style, else underlined in its text's colour", () => {
  const probe = drawnLink(kitBrand("probe.minted"), "link");
  assert.equal(probe.parts.decoration, "none");
  assert.equal(probe.source.decoration, "measured");
  const old = drawnLink(kitBrand("garner"), "link");
  assert.deepEqual([old.parts.decoration, old.source.decoration], ["underline", "fallback"]);
});

test("the brand's surfaces: our six, then every other surface of the kit with a readable name", () => {
  const choices = surfaceChoices(kitBrand("garner.minted"));
  assert.deepEqual(choices.slice(0, 6).map((c) => c.value), ["page", "card", "muted", "brandSubtle", "brand", "inverse"]);
  const labels = Object.fromEntries(choices.slice(6).map((c) => [c.value, c.label]));
  assert.equal(labels["band-014036"], "Dark band");
  assert.equal(labels["band-ffffff"], "Light band");
  assert.equal(labels.canvas, "Canvas");
  assert.equal(labels.elevated, "Elevated");
  assert.equal(labels.accent, "Accent");
  assert.ok(!("band-014036" in Object.fromEntries(surfaceChoices(kitBrand("garner")).map((c) => [c.value, c.label]))));
});

test("motion entries come from the kit's measured animations and reveals", () => {
  const entries = motionEntries(kitBrand("probe.minted"));
  const pulse = entries.find((e) => e.className === "brand-motion-pulse")!;
  assert.equal(pulse.describe, "opacity 1 → .4, transform scale(1) → scale(1.2); repeats forever, alternating");
  assert.equal(pulse.timing, "1.6s ease-in-out");
  const reveal = entries.find((e) => e.kind === "reveal")!;
  assert.match(reveal.className, /^brand-motion-reveal-[0-9a-f]{8}$/);
  assert.equal(reveal.describe, "fades in from opacity 0 and moves into place from 24px below as it scrolls into view");
  assert.deepEqual(motionNotes(kitBrand("probe.minted")), [{ kind: "scripted", where: "div#spin.spin" }]);
  assert.deepEqual(motionEntries(kitBrand("garner")), []);
});
