import assert from "node:assert/strict";
import test from "node:test";
import type { WebTheme } from "../engine/webDocuments";
import {
  buildThemeColorOptions,
  themeColorForToken,
  tokenLabel,
} from "./theme-options";

// W4.0: the document's REAL theme tokens become the color picker's Theme-tab
// options. The label is the write path (apply.ts lowercases it back into the
// `text-<token>` facet), so the round-trip is the contract under test.

function theme(tokens: Record<string, string>): WebTheme {
  return { bodyFamily: null, displayFamily: null, tokens };
}

test("every option's label lowercases back to its token name", () => {
  const tokens = { primary: "#0A5", accent: "#D85A00", inverse: "#FFFFFF" };
  const options = buildThemeColorOptions(theme(tokens));
  assert.deepEqual(
    options.map((option) => option.label),
    ["Primary", "Accent", "Inverse"],
  );
  for (const option of options) {
    // apply.ts writes `text-${label.trim().toLowerCase()}`, so the label MUST
    // land back on the token it came from.
    assert.equal(tokens[option.label.trim().toLowerCase() as keyof typeof tokens], option.value);
  }
});

test("a mixed-case server token still round-trips (names lowercase on ingest)", () => {
  const options = buildThemeColorOptions(theme({ CardMuted: "#EEF1F5" }));
  assert.deepEqual(options, [{ label: "Cardmuted", value: "#EEF1F5" }]);
  assert.equal(options[0].label.toLowerCase(), "cardmuted");
});

test("the server's token order is preserved", () => {
  const names = ["primary", "accent", "dark", "light", "card", "muted", "border", "inverse"];
  const tokens: Record<string, string> = {};
  for (const name of names) tokens[name] = `#${name.slice(0, 3)}`;
  assert.deepEqual(
    buildThemeColorOptions(theme(tokens)).map((option) => option.label.toLowerCase()),
    names,
  );
});

test("values pass through verbatim — any CSS color, never normalized", () => {
  const options = buildThemeColorOptions(
    theme({ primary: "oklch(0.62 0.19 30)", muted: "rgb(238 241 245)" }),
  );
  assert.deepEqual(
    options.map((option) => option.value),
    ["oklch(0.62 0.19 30)", "rgb(238 241 245)"],
  );
});

test("entries without a non-empty string value are skipped", () => {
  const options = buildThemeColorOptions({
    bodyFamily: null,
    displayFamily: null,
    tokens: {
      primary: "#0A5",
      blank: "",
      missing: null,
      numeric: 7,
    } as unknown as Record<string, string>,
  });
  assert.deepEqual(options, [{ label: "Primary", value: "#0A5" }]);
});

test("an empty theme — or none at all — yields no options", () => {
  assert.deepEqual(buildThemeColorOptions(theme({})), []);
  assert.deepEqual(buildThemeColorOptions(null), []);
});

// Ruling F3 (founder, 2026-08-18): the technical `palette-*` ramps are hidden
// from the picker; only the semantic/role tokens are offered.

test("palette-* ramp tokens are excluded from the picker", () => {
  const options = buildThemeColorOptions(
    theme({
      primary: "#0A5",
      "palette-neutral-50": "#FAFAFA",
      "palette-neutral-950": "#0B0B0C",
      "palette-primary-500": "#0A5",
      accent: "#D85A00",
    }),
  );
  assert.deepEqual(options, [
    { label: "Primary", value: "#0A5" },
    { label: "Accent", value: "#D85A00" },
  ]);
});

test("a mixed-case PALETTE- token is excluded too (names lowercase on ingest)", () => {
  assert.deepEqual(buildThemeColorOptions(theme({ "PALETTE-Neutral-50": "#FAFAFA" })), []);
});

test("compound non-palette tokens are retained", () => {
  const names = [
    "surface-brand-subtle",
    "text-secondary",
    "border-strong",
    "focus-ring",
    "accent-primary",
  ];
  const tokens: Record<string, string> = {};
  for (const name of names) tokens[name] = `#${name.length.toString(16)}`;
  assert.deepEqual(
    buildThemeColorOptions(theme(tokens)).map((option) => option.label.toLowerCase()),
    names,
  );
});

test("the retained tokens keep the server's order across a filtered theme", () => {
  const options = buildThemeColorOptions(
    theme({
      "palette-neutral-50": "#FAFAFA",
      primary: "#0A5",
      "palette-primary-500": "#0A5",
      "text-secondary": "#5A6270",
      dark: "#1C2028",
      "palette-neutral-950": "#0B0B0C",
      "focus-ring": "#2D7FF9",
    }),
  );
  assert.deepEqual(
    options.map((option) => option.label.toLowerCase()),
    ["primary", "text-secondary", "dark", "focus-ring"],
  );
});

test("the rule is the `palette-` PREFIX — a token named exactly `palette` survives", () => {
  const options = buildThemeColorOptions(
    theme({ palette: "#123456", palettes: "#654321", "palette-neutral-50": "#FAFAFA" }),
  );
  assert.deepEqual(options, [
    { label: "Palette", value: "#123456" },
    { label: "Palettes", value: "#654321" },
  ]);
});

test("a filtered palette-* token no longer resolves a swatch (ruling F3)", () => {
  const options = buildThemeColorOptions(
    theme({ primary: "#0A5", "palette-primary-500": "#0A5" }),
  );
  // An agent-authored `text-palette-primary-500` node falls back to the dummy
  // default rather than resolving a trigger swatch — accepted by ruling F3.
  assert.equal(themeColorForToken(options, "palette-primary-500"), undefined);
});

test("tokenLabel is the one shared capitalize-first rule", () => {
  assert.equal(tokenLabel("dark"), "Dark");
  assert.equal(tokenLabel("d"), "D");
  assert.equal(tokenLabel(""), "");
});

test("a hydrated token resolves to its option's color, case-insensitively", () => {
  const options = buildThemeColorOptions(theme({ primary: "#0A5", dark: "#1C2028" }));
  assert.equal(themeColorForToken(options, "Dark"), "#1C2028");
  assert.equal(themeColorForToken(options, "dark"), "#1C2028");
  assert.equal(themeColorForToken(options, " DARK "), "#1C2028");
});

test("an unmatched token, no token, or no theme resolves to nothing", () => {
  const options = buildThemeColorOptions(theme({ primary: "#0A5" }));
  // "Content" is the dummy's own default label — it must NOT resolve.
  assert.equal(themeColorForToken(options, "Content"), undefined);
  assert.equal(themeColorForToken(options, ""), undefined);
  assert.equal(themeColorForToken(options, undefined), undefined);
  assert.equal(themeColorForToken([], "Primary"), undefined);
  assert.equal(themeColorForToken(undefined, "Primary"), undefined);
});
