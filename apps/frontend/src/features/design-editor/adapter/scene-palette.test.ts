import assert from "node:assert/strict";
import { it } from "node:test";
import type { BrandKitDetailPayload } from "../engine/scene/tokenColors";
import {
  HARVESTED_AD_BRAND_KIT,
  adBrandKit,
} from "./__fixtures__/brand-kit-colors";
import { adTokenText } from "./__fixtures__/scene-nodes";
import {
  buildScenePalette,
  normalizeHex,
  paletteHex,
  scenePaletteColor,
  scenePaletteToken,
} from "./scene-palette";

/**
 * AD4.0 step 3: this file IS §1.6's offer-and-resolve table — which of the
 * kit's colour tokens the picker offers, in what order, and what a swatch
 * value means as a colour.
 *
 * Every case runs against the REAL brand kit the seeded ad is bound to
 * (`__fixtures__/brand-kit-colors`, `GET /brand-kits/{id}` bytes), never a
 * hand-written token map. Where the harvest cannot express a case — this kit
 * states every colour as a `hex`, so `oklch` and `alias` value kinds are
 * unexercised — the fixture is DEEP-COPIED and exactly one entry is edited,
 * and the case says so.
 */

/** A deep copy of the harvested kit — the fixture is a live reference into a
 * module singleton every test file shares (`adBrandKit`'s own warning), so a
 * derived variant that mutated it would rewrite the kit for every later test. */
function kitCopy(): BrandKitDetailPayload {
  return JSON.parse(JSON.stringify(HARVESTED_AD_BRAND_KIT)) as BrandKitDetailPayload;
}

// ══ the offered set ═════════════════════════════════════════════════════════

it("§1.6: the picker offers the kit's SEMANTIC colour tokens and hides the palette.* ramps", () => {
  const palette = buildScenePalette(adBrandKit());
  assert.ok(palette, "the harvested kit defines colour tokens");
  const labels = palette.options.map((option) => option.label);
  // The kit defines 42 colour tokens; 22 are `palette.*` ramp steps.
  assert.equal(labels.length, 20);
  assert.equal(
    labels.some((label) => label.startsWith("palette.")),
    false,
  );
  // The 20 offered names are EXACTLY the colour buckets the same response
  // publishes under `brand_summary.tokens` (text/surface/border/focus) — the
  // catalog upstream's `ColorSwatchControl` offers from.
  assert.deepEqual([...labels].sort(), [
    "border.brand",
    "border.default",
    "border.strong",
    "border.subtle",
    "focus.ring",
    "surface.accent",
    "surface.brand",
    "surface.brand.subtle",
    "surface.canvas",
    "surface.card",
    "surface.elevated",
    "surface.inverse",
    "surface.muted",
    "surface.page",
    "text.accent",
    "text.brand",
    "text.inverse",
    "text.muted",
    "text.primary",
    "text.secondary",
  ]);
});

it("§1.6: every offered row carries the token's REAL colour, and its label IS its token", () => {
  const palette = buildScenePalette(adBrandKit());
  assert.ok(palette, "the harvested kit defines colour tokens");
  for (const option of palette.options) {
    // The brief's open question, settled by the data rather than assumed:
    // `onTokenChange` reports a LABEL, and on this lane that label is the
    // token name verbatim. `option.token` carries it explicitly all the same,
    // so a later relabel cannot silently break the write path.
    assert.equal(option.label, option.token, option.label);
    assert.match(option.value, /^#[0-9A-Fa-f]{6}$/, option.label);
  }
  // Spot-checked against the harvested bytes.
  const inverse = palette.options.find((option) => option.label === "text.inverse");
  assert.equal(inverse?.value, "#FFFFFF");
  const brand = palette.options.find((option) => option.label === "surface.brand");
  assert.equal(brand?.value, "#533AFD");
});

it("§1.6: the offer order is the KIT's own token order — nothing is re-sorted here", () => {
  const kit = adBrandKit();
  const palette = buildScenePalette(kit);
  assert.ok(palette, "the harvested kit defines colour tokens");
  const kitOrder = Object.keys(kit.tokens?.colors ?? {}).filter(
    (name) => !name.startsWith("palette."),
  );
  assert.deepEqual(
    palette.options.map((option) => option.label),
    kitOrder,
  );
});

it("§1.6: an ALIAS resolves but is not OFFERED — the kit catalogs it as a legacy name", () => {
  const palette = buildScenePalette(adBrandKit());
  assert.ok(palette, "the harvested kit defines colour tokens");
  // `tokens.aliases` carries `accent.primary` -> `surface.accent`.
  assert.equal(
    palette.options.some((option) => option.label === "accent.primary"),
    false,
  );
  // Hiding it from the PICKER must not make a document already bound to it
  // unresolvable: resolution reads the whole map, offers read the catalog.
  assert.equal(scenePaletteColor(palette, "accent.primary"), "#EA2261");
  assert.equal(scenePaletteColor(palette, "surface.accent"), "#EA2261");
});

it("§1.6: a ramp is resolvable even though it is not offered", () => {
  const palette = buildScenePalette(adBrandKit());
  assert.ok(palette, "the harvested kit defines colour tokens");
  assert.equal(scenePaletteColor(palette, "palette.primary.600"), "#533AFD");
});

it("§1.6: a kit with no colour tokens at all is NO palette — the control keeps its own list", () => {
  assert.equal(buildScenePalette(null), null);
  assert.equal(buildScenePalette(undefined), null);
  assert.equal(buildScenePalette({}), null);
  assert.equal(buildScenePalette({ tokens: {} }), null);
  assert.equal(buildScenePalette({ tokens: { colors: {} } }), null);
});

it("§1.6: a ramp-ONLY kit still resolves, but offers nothing to pick", () => {
  // Derived from the harvest by DROPPING every semantic token — the ramp
  // entries below are the real harvested ones.
  const kit = kitCopy();
  const colors = kit.tokens?.colors ?? {};
  for (const name of Object.keys(colors)) {
    if (!name.startsWith("palette.")) delete colors[name];
  }
  delete kit.tokens?.aliases;
  const palette = buildScenePalette(kit);
  assert.ok(palette, "the ramps are still a colour vocabulary");
  assert.deepEqual(palette.options, []);
  assert.equal(scenePaletteColor(palette, "palette.neutral.950"), "#000000");
});

// ══ resolution (R3b) ════════════════════════════════════════════════════════

it("R3b: the seeded ad's own token fill resolves to a real colour, `$` prefix and all", () => {
  const palette = buildScenePalette(adBrandKit());
  const [fill] = adTokenText().fills;
  assert.equal(fill.paint.kind, "token");
  // The harvested headline's stored token is `$text.inverse` — the author-
  // facing `$` sugar rides in the stored bytes, and the kit's key does not
  // carry it. `resolveTokenColor` strips it, so both spellings hit one entry.
  const stored = fill.paint.kind === "token" ? fill.paint.token : "";
  assert.equal(stored, "$text.inverse");
  assert.equal(scenePaletteColor(palette, stored), "#FFFFFF");
  assert.equal(scenePaletteColor(palette, "text.inverse"), "#FFFFFF");
});

it("R3b: a value that is not a token of this kit resolves to nothing — never a guess", () => {
  const palette = buildScenePalette(adBrandKit());
  for (const value of ["#0E0B2E", "none", "", "text.nope", "$text.nope", "Primary"]) {
    assert.equal(scenePaletteColor(palette, value), null, value);
  }
  assert.equal(scenePaletteColor(null, "text.inverse"), null);
});

it("R3b: an OKLCH token resolves through the engine's own converter", () => {
  // UNCOVERED by the harvest: this kit states every colour as a hex. One
  // entry of a DEEP COPY is replaced with the oklch form `tokenColors.ts`
  // documents, so the conversion path runs against otherwise-real bytes.
  const kit = kitCopy();
  const colors = kit.tokens?.colors ?? {};
  colors["text.primary"] = {
    value: { default: { c: 0, h: 0, kind: "oklch", l: 0 } },
  };
  const palette = buildScenePalette(kit);
  assert.equal(scenePaletteColor(palette, "text.primary"), "#000000");
});

it("R3b: an UNRESOLVABLE alias chain drops that token rather than looping", () => {
  // UNCOVERED by the harvest: no harvested entry is an in-catalog alias. Two
  // entries of a DEEP COPY are pointed at each other.
  const kit = kitCopy();
  const colors = kit.tokens?.colors ?? {};
  colors["text.primary"] = { value: { default: { kind: "alias", token: "text.muted" } } };
  colors["text.muted"] = { value: { default: { kind: "alias", token: "text.primary" } } };
  const palette = buildScenePalette(kit);
  assert.ok(palette, "the rest of the kit still resolves");
  assert.equal(scenePaletteColor(palette, "text.primary"), null);
  // A token that resolves to nothing is not offered either — an unpaintable
  // swatch is worse than no swatch (`buildThemeColorOptions`'s own rule).
  assert.equal(
    palette.options.some((option) => option.label === "text.primary"),
    false,
  );
});

// ══ label → token (the write path's half) ═══════════════════════════════════

it("R3: an OFFERED label names its token; anything else names none", () => {
  const palette = buildScenePalette(adBrandKit());
  assert.equal(scenePaletteToken(palette, "text.inverse"), "text.inverse");
  assert.equal(scenePaletteToken(palette, "surface.brand"), "surface.brand");
  // The ramps and the alias are resolvable but NOT offered, so no pick can
  // have produced them — and a label the picker never rendered is not a write.
  assert.equal(scenePaletteToken(palette, "palette.primary.600"), null);
  assert.equal(scenePaletteToken(palette, "accent.primary"), null);
  // Labels the retired fixture palette used to offer (`resolveInspectorThemeColors`
  // now returns nothing without a kit). They are not this kit's tokens and
  // must never reach the document.
  for (const label of ["Primary", "Secondary", "Tertiary", "Dark", "Light", "Subtle"]) {
    assert.equal(scenePaletteToken(palette, label), null, label);
  }
  assert.equal(scenePaletteToken(palette, ""), null);
  assert.equal(scenePaletteToken(null, "text.inverse"), null);
});

// ══ the custom-hex half of §1.6 ═════════════════════════════════════════════

it("§1.6: `normalizeHex` is the ported upstream normalization, minus its silent black", () => {
  assert.equal(normalizeHex("#FF00AA"), "#ff00aa");
  assert.equal(normalizeHex("  #ff00aa  "), "#ff00aa");
  assert.equal(normalizeHex("#FF00AA80"), "#ff00aa");
  for (const value of ["", "#FFF", "rebeccapurple", "123456", "none"]) {
    assert.equal(normalizeHex(value), null, value);
  }
});

it("R3b: `paletteHex` is a hex verbatim, a token resolved, and nothing else at all", () => {
  const palette = buildScenePalette(adBrandKit());
  // A hex rides through with its CASING untouched — it is already what the
  // control committed, and re-casing it would churn a value nobody changed.
  assert.equal(paletteHex(palette, "#0E0B2E"), "#0E0B2E");
  assert.equal(paletteHex(palette, "$text.inverse"), "#FFFFFF");
  assert.equal(paletteHex(palette, "text.inverse"), "#FFFFFF");
  // The honest none-state and an unresolvable token both yield NO hex, so a
  // caller that structurally needs one refuses instead of fabricating.
  assert.equal(paletteHex(palette, "none"), null);
  assert.equal(paletteHex(palette, "text.nope"), null);
  assert.equal(paletteHex(null, "$text.inverse"), null);
  assert.equal(paletteHex(null, "#0E0B2E"), "#0E0B2E");
});
