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
