import assert from "node:assert/strict";
import test from "node:test";
import { HARVESTED_BRAND_KIT, MEASURED_BRAND_KIT } from "../data/__fixtures__/harvest";
import { toBrandContextWorkspace } from "./brand-context-mapping";
import { BrandKitDetailSchema } from "./brand-kit";
import { isMeasuredColor, toMeasuredBrand } from "./measured-brand";
import { measuredSections, typefaceFor, type MeasuredBrandView, type MeasuredSample } from "./measured-view";

// MEASURED_BRAND_KIT: Garner's kit with everything the real probe measured on
// apps/api/tests/fixtures/capture/style_states.html, minted by the real code (Task X5's script).
const kit = BrandKitDetailSchema.parse(MEASURED_BRAND_KIT);
const view = toMeasuredBrand(kit) as MeasuredBrandView;

const group = (id: string) => view.groups.find((g) => g.id === id)!;
const style = (groupId: string, variant: string) => group(groupId).styles.find((s) => s.variant === variant)!;
const sample = (groupId: string, variant: string, state: MeasuredSample["state"]) =>
  style(groupId, variant).samples.find((s) => s.state === state)!;

test("the kit read keeps what the extraction measured: measured_components and every token group", () => {
  assert.equal(kit.brand_kit_json.measured_components?.schema_version, 1);
  assert.ok(Object.keys(kit.brand_kit_json.tokens?.styles ?? {}).length > 0, "style tokens survive the read");
  assert.ok(Object.keys(kit.brand_kit_json.tokens?.spacing ?? {}).length > 0);
  assert.ok((kit.brand_kit_json.constraints?.contrast_pairs ?? []).length > 0);
  const broken = structuredClone(MEASURED_BRAND_KIT) as { brand_kit_json: Record<string, unknown> };
  broken.brand_kit_json.measured_components = { schema_version: 1, source: "x", styles: "not a list" };
  const parsed = BrandKitDetailSchema.parse(broken);
  assert.equal(parsed.brand_kit_json.measured_components, null, "an unreadable section is no section");
  assert.ok(parsed.brand_kit_json.tokens?.colors, "and the rest of the kit still reads");
});

test("a kit made before measurement has no measured view, so the page is unchanged", () => {
  assert.equal(toMeasuredBrand(BrandKitDetailSchema.parse(HARVESTED_BRAND_KIT)), null);
  assert.deepEqual(measuredSections(null), []);
  assert.deepEqual(measuredSections(view), ["components", "spacing", "motion"]);
});

test("buttons are named as the dock names them, by kind, and by their look-keyed variant", () => {
  assert.deepEqual(group("buttons").styles.map((s) => [s.name, s.variant]), [
    ["Outline", "outline.0d2b25"],
    ["Filled 1", "solid.047464"],
    ["Filled 2", "solid.0a4a8a"],
    ["Filled 3", "solid.28241e"],
    ["Filled 4", "solid.7c4cff"],
  ]);
  assert.deepEqual(view.groups.map((g) => g.title), ["Buttons", "Cards", "Links"]);
  assert.deepEqual(group("links").styles.map((s) => s.name), ["Link", "Navigation link"]);
  assert.deepEqual(group("cards").styles.map((s) => s.name), ["Card"]);
});

test("each measured state is drawn from its own measured values", () => {
  const filled = style("buttons", "solid.047464");
  assert.deepEqual(filled.samples.map((s) => s.name), ["Rest", "Hover", "Pressed", "Focus", "Disabled"]);
  const rest = sample("buttons", "solid.047464", "rest");
  assert.equal(rest.style.backgroundColor, "#047464");
  assert.equal(rest.style.color, "#FFFFFF");
  assert.equal(rest.style.textTransform, "uppercase");
  assert.equal(rest.style.letterSpacing, "0.02em");
  assert.equal(rest.backdrop, "#F9FAF8", "Garner's page colour behind a teal button");
  assert.ok(rest.values.some((v) => v.label === "Font" && v.value === "Arial · 14px · 500 · 0.02em letter spacing"));
  const hover = sample("buttons", "solid.047464", "hover");
  assert.equal(hover.style.backgroundColor, "#035A4E");
  assert.equal(hover.style.boxShadow, "0px 4px 12px 0px #00000033");
  assert.equal(hover.icon?.style.transform, "matrix(1, 0, 0, 1, 4, 0)", "the arrow slides on hover");
  assert.ok(hover.values.every((v) => v.label !== "Text"), "a state lists only what it changes");
  assert.equal(sample("buttons", "solid.047464", "pressed").style.transform, "matrix(0.98, 0, 0, 0.98, 0, 0)");
  const focus = sample("buttons", "solid.047464", "focus").style;
  assert.deepEqual([focus.outlineColor, focus.outlineWidth, focus.outlineStyle, focus.outlineOffset], ["#F5A623", "3px", "solid", "2px"]);
  assert.equal(sample("buttons", "solid.047464", "disabled").style.opacity, "0.45");
  assert.deepEqual(filled.transitions.map((t) => [t.label, t.value]), [
    ["Transition", "background-color 200ms ease-out"],
    ["Transition", "transform 150ms ease"],
    ["Transition", "box-shadow 300ms ease after 50ms"],
    ["Icon transition", "transform 200ms ease"],
  ]);
});

test("the seller's icon is drawn as an image in the measured colour, never as markup", () => {
  const icon = sample("buttons", "solid.047464", "rest").icon!;
  assert.equal(icon.position, "end");
  assert.ok(icon.src?.startsWith("data:image/svg+xml;charset=utf-8,"));
  const markup = decodeURIComponent(icon.src!.slice("data:image/svg+xml;charset=utf-8,".length));
  assert.ok(markup.startsWith('<svg xmlns="http://www.w3.org/2000/svg"'), markup);
  assert.ok(markup.includes("#FFFFFF") && !markup.includes("currentColor"), markup);
  assert.equal(sample("buttons", "outline.0d2b25", "rest").icon?.glyph, "→");
});

test("a focus ring the site leaves to the browser is said, not drawn", () => {
  assert.equal(sample("buttons", "solid.7c4cff", "focus").note, "The browser's own focus ring");
  assert.equal(sample("buttons", "solid.047464", "focus").note, null);
});

test("a style that would not show on the page colour is drawn on the kit's inverse surface", () => {
  const raw = structuredClone(MEASURED_BRAND_KIT) as { brand_kit_json: { tokens: { colors: Record<string, { value: { default: unknown } }> } } };
  raw.brand_kit_json.tokens.colors["surface.page"].value.default = { kind: "hex", value: "#047464" };
  const onTeal = toMeasuredBrand(BrandKitDetailSchema.parse(raw))!;
  const rest = onTeal.groups[0].styles.find((s) => s.variant === "solid.047464")!.samples[0];
  assert.equal(rest.backdrop, "#111210", "Garner's surface.inverse");
});

test("links and cards show their hover looks", () => {
  const link = sample("links", "ghost.0d2b25", "hover").style;
  assert.deepEqual([link.textDecorationLine, link.textDecorationThickness, link.color], ["underline", "2px", "#047464"]);
  assert.equal(sample("links", "ghost.0d2b25", "rest").style.display, undefined, "a text link is not boxed");
  assert.ok(sample("cards", "solid.f1f0de", "hover").style.boxShadow?.startsWith("0px 8px 24px 0px"));
});

test("minted colours are grouped by style and section background, never in Semantic roles", () => {
  assert.deepEqual(view.colorGroups.map((g) => g.label), [
    "Section backgrounds", "Outline button", "Filled 1 button", "Filled 2 button", "Filled 3 button",
    "Filled 4 button", "Card", "Link", "Navigation link",
  ]);
  const filled = view.colorGroups.find((g) => g.label === "Filled 1 button")!;
  assert.deepEqual(filled.swatches.map((s) => [s.label, s.lightValue]), [
    ["Fill", "#047464"], ["Text", "#FFFFFF"], ["Border", "#047464"],
    ["Hover fill", "#035A4E"], ["Pressed fill", "#023F37"], ["Focus ring", "#F5A623"],
  ]);
  const band = view.colorGroups[0].swatches.find((s) => s.lightValue === "#014036")!;
  assert.equal(band.label, "Dark band · text #FFFFFF");
  assert.ok(view.movedColors.includes("surface.band.014036"));
  assert.ok(view.movedColors.every(isMeasuredColor));
  assert.ok(!view.movedColors.includes("surface.brand") && !view.movedColors.includes("text.inverse"), "reused kit colours stay where they are");
  const semantic = toBrandContextWorkspace(kit, { movedColors: new Set(view.movedColors) }).colorGroups[0];
  const ids = semantic.swatches.map((s) => s.id);
  assert.ok(!ids.includes("surface.band.014036") && ids.includes("surface.brand"));
  assert.ok(toBrandContextWorkspace(kit).colorGroups[0].swatches.some((s) => s.id === "surface.band.014036"), "without the measured view nothing moves");
});

test("spacing lists the kit's steps, smallest first, saying which were measured", () => {
  assert.equal(view.spacing[0].value, "0px");
  const section = view.spacing.find((s) => s.token === "space.section")!;
  assert.deepEqual([section.name, section.value, section.measured], ["Section", "100px", true]);
  const tight = view.spacing.find((s) => s.token === "space.stack.tight")!;
  assert.deepEqual([tight.name, tight.measured], ["Stack tight", false]);
  assert.equal(view.spacing.find((s) => s.token === "space.sm")?.name, "Small");
  assert.equal(view.spacing.find((s) => s.token === "space.4")?.name, "Step 4");
  assert.ok(view.spacing.every((s) => s.token.startsWith("space.")), "component tokens are shown with their styles");
});

test("motion is the measured animations, reveals and the motion pages do not copy, in words", () => {
  assert.deepEqual(view.animations.map((c) => [c.name, c.headline, c.lines]), [[
    "Pulse", "1.6s ease-in-out",
    ["Opacity 1 → .4, transform scale(1) → scale(1.2); repeats forever, alternating", "1 element: div#pulse.pulse"],
  ]]);
  assert.equal(view.reveals.length, 1);
  assert.equal(view.reveals[0].name, "Scroll reveal");
  assert.equal(view.reveals[0].headline, "600ms ease-out");
  assert.equal(view.reveals[0].lines[0], "Fades in from opacity 0 and moves into place from 24px below as it scrolls into view");
  assert.deepEqual(view.scripted, [{
    id: "scripted-0", name: "Scripted animation", headline: "div#spin.spin",
    lines: ["Needs a script, so pages made here don't copy it."],
  }]);
});

test("a sample loads the kit's own typeface when the kit carries the measured family", () => {
  const typefaces = [{ family: "Open Sans", id: "body", source: "custom" as const }];
  assert.equal(typefaceFor(typefaces, "open sans")?.id, "body");
  assert.equal(typefaceFor(typefaces, "Arial"), null);
  assert.equal(typefaceFor(typefaces, null), null);
});
