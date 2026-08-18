import assert from "node:assert/strict";
import test from "node:test";
import { HARVESTED_BRAND_KIT } from "../data/__fixtures__/harvest";
import { BrandContextWorkspaceSchema } from "./brand-context";
import {
  emptyBrandContextWorkspace,
  toBrandContextWorkspace,
} from "./brand-context-mapping";
import { BrandKitDetailSchema } from "./brand-kit";

const kit = BrandKitDetailSchema.parse(HARVESTED_BRAND_KIT);
const workspace = toBrandContextWorkspace(kit);

test("the harvested kit maps to a workspace the page's schema accepts", () => {
  BrandContextWorkspaceSchema.parse(workspace);
  assert.equal(workspace.id, "brand_kit_ing_813df4f30f2d429a853dbccae2277a5a");
  assert.equal(workspace.name, "Stripe");
});

test("semantic roles are one group, each palette ramp is its own", () => {
  assert.deepEqual(
    workspace.colorGroups.map((group) => [group.id, group.label]),
    [
      ["semantic", "Semantic roles"],
      ["palette-neutral", "Neutral palette"],
      ["palette-primary", "Primary palette"],
    ],
  );

  const semantic = workspace.colorGroups[0];
  assert.equal(semantic.swatches.length, 20);
  // Semantic swatches carry their whole token path, sorted.
  assert.equal(semantic.swatches[0].id, "border.brand");
  assert.equal(semantic.swatches[0].label, "border.brand");
});

test("swatches carry the kit's light value and its theme.dark override", () => {
  const surfaceCard = workspace.colorGroups[0].swatches.find(
    (swatch) => swatch.id === "surface.card",
  );
  assert.deepEqual(
    { light: surfaceCard?.lightValue, dark: surfaceCard?.darkValue },
    { light: "#FFFFFF", dark: "#16192D" },
  );
});

test("a token with no dark mode reports its light value — never a fabricated dark", () => {
  const primary = workspace.colorGroups.find(
    (group) => group.id === "palette-primary",
  );
  const stop500 = primary?.swatches.find(
    (swatch) => swatch.id === "palette.primary.500",
  );
  assert.deepEqual(
    { light: stop500?.lightValue, dark: stop500?.darkValue },
    { light: "#6D70FF", dark: "#6D70FF" },
  );
});

test("ramp swatches are labelled by stop and ordered numerically", () => {
  const neutral = workspace.colorGroups.find(
    (group) => group.id === "palette-neutral",
  );
  assert.deepEqual(
    neutral?.swatches.map((swatch) => swatch.label),
    ["50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950"],
  );
});

test("alias tokens resolve through to a real value, per mode", () => {
  const aliased = toBrandContextWorkspace(
    BrandKitDetailSchema.parse({
      brand_kit: { id: "kit", version: 1, name: "Alias" },
      brand_kit_json: {
        id: "kit",
        name: "Alias",
        version: 1,
        tokens: {
          colors: {
            "surface.brand": {
              value: {
                default: { kind: "hex", value: "#111111" },
                modes: { "theme.dark": { kind: "hex", value: "#EEEEEE" } },
              },
            },
            "surface.card": {
              value: { default: { kind: "alias", token: "surface.brand" } },
            },
          },
        },
      },
    }),
  );

  const card = aliased.colorGroups[0].swatches.find(
    (swatch) => swatch.id === "surface.card",
  );
  assert.deepEqual(
    { light: card?.lightValue, dark: card?.darkValue },
    { light: "#111111", dark: "#EEEEEE" },
  );
});

test("an oklch token becomes a CSS oklch colour rather than being dropped", () => {
  const mapped = toBrandContextWorkspace(
    BrandKitDetailSchema.parse({
      brand_kit: { id: "kit", version: 1, name: "Oklch" },
      brand_kit_json: {
        id: "kit",
        name: "Oklch",
        version: 1,
        tokens: {
          colors: {
            "surface.page": {
              value: {
                default: { kind: "oklch", l: 0.5, c: 0.1, h: 240, alpha: 1 },
              },
            },
          },
        },
      },
    }),
  );

  assert.equal(
    mapped.colorGroups[0].swatches[0].lightValue,
    "oklch(0.5 0.1 240)",
  );
});

test("an unresolvable token drops its swatch instead of blanking the page", () => {
  const mapped = toBrandContextWorkspace(
    BrandKitDetailSchema.parse({
      brand_kit: { id: "kit", version: 1, name: "Broken" },
      brand_kit_json: {
        id: "kit",
        name: "Broken",
        version: 1,
        tokens: {
          colors: {
            "surface.page": {
              value: { default: { kind: "hex", value: "#FFF" } },
            },
            "surface.card": {
              value: { default: { kind: "alias", token: "surface.missing" } },
            },
            "surface.broken": { not: "a token" },
          },
        },
      },
    }),
  );

  assert.deepEqual(
    mapped.colorGroups[0].swatches.map((swatch) => swatch.id),
    ["surface.page"],
  );
});

test("a kit with nothing in it becomes the designed empty workspace", () => {
  const mapped = toBrandContextWorkspace(
    BrandKitDetailSchema.parse({
      brand_kit: { id: "kit_empty", version: 1, name: "Empty" },
      brand_kit_json: { id: "kit_empty", name: "Empty", version: 1 },
    }),
  );

  BrandContextWorkspaceSchema.parse(mapped);
  assert.deepEqual(mapped, {
    ...emptyBrandContextWorkspace(),
    id: "kit_empty",
    name: "Empty",
  });
});

test("the honest-empty workspace is schema-valid and carries no fixture content", () => {
  const empty = emptyBrandContextWorkspace();
  BrandContextWorkspaceSchema.parse(empty);
  assert.deepEqual(
    {
      colorGroups: empty.colorGroups,
      typefaces: empty.typefaces,
      textStyles: empty.textStyles,
      assets: empty.assets,
      knowledgeFolders: empty.knowledgeFolders,
    },
    {
      colorGroups: [],
      typefaces: [],
      textStyles: [],
      assets: [],
      knowledgeFolders: [],
    },
  );
});

test("typefaces come from the kit's font assets, sourced honestly", () => {
  assert.deepEqual(workspace.typefaces, [
    { family: "SourceCodePro", id: "brand", source: "custom" },
  ]);
});

test("a system font family is a library typeface, a brand's own webfont is custom", () => {
  const mapped = toBrandContextWorkspace(
    BrandKitDetailSchema.parse({
      brand_kit: { id: "kit", version: 1, name: "Fonts" },
      brand_kit_json: {
        id: "kit",
        name: "Fonts",
        version: 1,
        assets: {
          fonts: {
            body: { family: "Georgia", source: { kind: "system" } },
            brand: { family: "Inter", source: { kind: "uploaded" } },
            mono: { family: "IBM Plex Mono" },
          },
        },
      },
    }),
  );

  assert.deepEqual(mapped.typefaces, [
    { family: "Georgia", id: "body", source: "library" },
    { family: "Inter", id: "brand", source: "custom" },
    { family: "IBM Plex Mono", id: "mono", source: "library" },
  ]);
});

test("text styles read the type scale largest-first, in px", () => {
  assert.deepEqual(
    workspace.textStyles.map((style) => [style.id, style.fontSize]),
    [
      ["type.display", 51],
      ["type.stat", 40],
      ["type.headline", 32],
      ["type.title", 23],
      ["type.subtitle", 20],
      ["type.body", 16],
      ["type.body.small", 14],
      ["type.label", 13],
      ["type.caption", 12],
      ["type.eyebrow", 12],
      ["type.cta", 11],
      ["type.legal", 11],
    ],
  );
});

test("the kit's unitless line-height becomes the px the column claims", () => {
  const display = workspace.textStyles[0];
  assert.deepEqual(display, {
    fontFamily: "SourceCodePro",
    fontSize: 51,
    fontWeight: 700,
    id: "type.display",
    // 51 × 1.05, the engine's own `font_size * line_height`.
    lineHeight: 54,
    name: "Display",
    // The kit carries no usage guidance for its type tokens — honest empty.
    recommendedUse: "",
  });
});

test("a kit with no typography and no fonts renders both empty states", () => {
  const mapped = toBrandContextWorkspace(
    BrandKitDetailSchema.parse({
      brand_kit: { id: "kit", version: 1, name: "Bare" },
      brand_kit_json: { id: "kit", name: "Bare", version: 1 },
    }),
  );

  assert.deepEqual(mapped.typefaces, []);
  assert.deepEqual(mapped.textStyles, []);
});
