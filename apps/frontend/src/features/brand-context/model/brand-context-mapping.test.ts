import assert from "node:assert/strict";
import test from "node:test";
import {
  HARVESTED_ASSET_RECORDS,
  HARVESTED_BRAND_KIT,
} from "../data/__fixtures__/harvest";
import { BrandContextWorkspaceSchema } from "./brand-context";
import {
  brandKitAssetIds,
  emptyBrandContextWorkspace,
  parseAssetRecords,
  toBrandContextWorkspace,
  toRegistryAssets,
} from "./brand-context-mapping";
import { BrandKitDetailSchema } from "./brand-kit";

/** A minimal, valid `BrandBrief@1` — the shape the ingestion agent writes. */
const BRIEF_FIXTURE = {
  background_rhythm: { bands: [], confidence: "high" },
  characterization: {
    confidence: "high",
    support: "Violet CTAs on a white canvas.",
    words: ["expansive", "polished"],
  },
  chromatic_moment: {
    confidence: "high",
    element: "the primary CTA",
    quiet: false,
    token: "surface.brand",
  },
  component_recipes: [],
  constraints: [],
  diagnostics: [],
  imagery_posture: { absences: [], confidence: "low", slots: [] },
  palette_application: [],
  schema_version: 1,
  signature_compositions: [],
  typographic_posture: { confidence: "low", signature_moves: [], tokens: [] },
};

const kit = BrandKitDetailSchema.parse(HARVESTED_BRAND_KIT);
const workspace = toBrandContextWorkspace(kit);
const workspaceWithAssets = toBrandContextWorkspace(kit, {
  assetRecords: parseAssetRecords(HARVESTED_ASSET_RECORDS),
});

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
    {
      family: "SourceCodePro", id: "brand", source: "custom",
      previewFamily: `clue-brand-${encodeURIComponent(kit.brand_kit.id)}-${kit.brand_kit.version}-brand`,
      faces: [{
        url: "https://stripe.com/mkt-ssr-statics/assets/_next/static/media/SourceCodePro-Medium.f5ba3e6a.woff2",
        weight: 500,
        style: "normal",
      }],
    },
  ]);
});

test("font previews prefer authenticated stored bytes, preserve faces and discard unusable URLs", () => {
  const detail = BrandKitDetailSchema.parse({
    brand_kit: { id: "kit", version: 2, name: "Fonts" },
    brand_kit_json: {
      id: "kit", name: "Fonts", version: 2,
      assets: { fonts: { body: {
        family: "Brand font", source: { kind: "uploaded" },
        faces: [
          { asset_id: "font/id", source_url: "https://example.com/old.woff2", weight: 500, style: "normal" },
          { source_url: "https://example.com/italic.woff2", weight: 700, style: "italic" },
          { source_url: "javascript:alert(1)", weight: 400, style: "normal" },
          { source_url: "data:text/html,invalid", weight: 400, style: "normal" },
          { source_url: "https://example.com/broken.woff2", weight: "invalid" },
        ],
      } } },
    },
  });
  const [font] = toBrandContextWorkspace(detail).typefaces;
  assert.equal(font.previewFamily, "clue-brand-kit-2-body");
  assert.deepEqual(font.faces, [
    { url: "/api/clue/design/assets/font%2Fid/bytes", weight: 500, style: "normal" },
    { url: "https://example.com/italic.woff2", weight: 700, style: "italic" },
  ]);
  assert.notEqual(toBrandContextWorkspace({ ...detail, brand_kit: { ...detail.brand_kit, version: 3 } }).typefaces[0].previewFamily, font.previewFamily);
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

test("assets are the kit's logos then its images, deduped and ordered", () => {
  assert.deepEqual(
    workspaceWithAssets.assets.map((asset) => [asset.id, asset.category]),
    [
      ["asset_ing_cb86ad335799c963", "logo"],
      ["asset_ing_61a219a05909b652", "logo"],
      ["asset_ing_53f9b6455350e5b5", "background"],
      ["asset_ing_7262ca0dc07c8d9c", "background"],
      ["asset_ing_5ea77b5ffa4992f3", "background"],
      ["asset_ing_421820f838bdedce", "background"],
      ["asset_ing_e33a3733dcbaa605", "background"],
      ["asset_ing_2240f4c56a7ba765", "background"],
      ["asset_ing_2b0928ca4f3a3c70", "background"],
      ["asset_ing_1511de1ec38185ac", "background"],
      ["asset_ing_0888ff6595f4662d", "background"],
      ["asset_ing_ecf26311cdeb734d", "background"],
      ["asset_ing_9ea5ee9c9f82fa56", "background"],
      ["asset_ing_fa2ed16107766130", "background"],
      ["asset_ing_f436261cad2c2aa9", "background"],
    ],
  );
});

test("an asset's bytes are addressed through the BFF, never the design API", () => {
  for (const asset of workspaceWithAssets.assets) {
    assert.equal(asset.visual.kind, "image");
    assert.match(
      asset.visual.kind === "image" ? asset.visual.imagePath : "",
      /^\/api\/clue\/design\/assets\/asset_ing_[0-9a-f]+\/bytes$/,
    );
  }
});

test("the asset registry supplies the name, type, size and geometry", () => {
  const logo = workspaceWithAssets.assets.find(
    (asset) => asset.id === "asset_ing_61a219a05909b652",
  );
  assert.deepEqual(
    {
      name: logo?.name,
      type: logo?.type,
      sizeBytes: logo?.sizeBytes,
      sizeLabel: logo?.sizeLabel,
      dimensions: logo?.dimensions,
      createdLabel: logo?.createdLabel,
      description: logo?.description,
    },
    {
      name: "logo.svg",
      type: "SVG",
      sizeBytes: 1922,
      sizeLabel: "1.9 KB",
      dimensions: "60×25px",
      createdLabel: "Aug 18, 2026",
      // The harvest carries no description — the kit's describe pass was off.
      description: "",
    },
  );
});

test("an asset with no registry record still renders, with honest unknowns", () => {
  const mapped = toBrandContextWorkspace(kit, {});
  const logo = mapped.assets.find(
    (asset) => asset.id === "asset_ing_61a219a05909b652",
  );
  assert.deepEqual(
    {
      name: logo?.name,
      type: logo?.type,
      sizeBytes: logo?.sizeBytes,
      sizeLabel: logo?.sizeLabel,
      dimensions: logo?.dimensions,
    },
    {
      // Without the registry the kit's own key is all we honestly have.
      name: "primary",
      type: "—",
      sizeBytes: 0,
      sizeLabel: "—",
      dimensions: "—",
    },
  );
});

test("a captured screenshot is the screen's mockup category", () => {
  const mapped = toBrandContextWorkspace(
    BrandKitDetailSchema.parse({
      brand_kit: { id: "kit", version: 1, name: "Shots" },
      brand_kit_json: {
        id: "kit",
        name: "Shots",
        version: 1,
        assets: {
          images: {
            "img.1": { asset_id: "asset_shot", role: "screenshot" },
            "img.2": { asset_id: "asset_photo", role: "photo" },
          },
        },
      },
    }),
    {},
  );

  assert.deepEqual(
    mapped.assets.map((asset) => [asset.id, asset.category]),
    [
      ["asset_shot", "mockup"],
      ["asset_photo", "background"],
    ],
  );
});

test("no kit models a gradient, so no asset claims to be one", () => {
  assert.ok(
    workspaceWithAssets.assets.every((asset) => asset.visual.kind === "image"),
  );
});

test("a briefless kit shows an honestly empty knowledge tree", () => {
  // The harvested Stripe kit predates the brief — no folder, and no placeholder
  // Design.md claiming this brand has no design rules.
  assert.deepEqual(workspaceWithAssets.knowledgeFolders, []);
});

test("a kit carrying a brief serves it as design/Design.md", () => {
  const withBrief = toBrandContextWorkspace(
    BrandKitDetailSchema.parse({
      ...HARVESTED_BRAND_KIT,
      brand_kit: {
        ...(HARVESTED_BRAND_KIT as { brand_kit: Record<string, unknown> }).brand_kit,
        approval_status: "approved",
      },
      brand_kit_json: {
        ...(HARVESTED_BRAND_KIT as { brand_kit_json: Record<string, unknown> })
          .brand_kit_json,
        brief: BRIEF_FIXTURE,
      },
    }),
  );

  assert.deepEqual(
    withBrief.knowledgeFolders.map((folder) => [folder.id, folder.label]),
    [["design", "Design"]],
  );
  const document = withBrief.knowledgeFolders[0].documents[0];
  assert.equal(document.path, "design/Design.md");
  assert.equal(document.name, "Design.md");
  // The content header carries the kit's identity, version and approval state.
  assert.match(document.body, /version 1/);
  assert.match(document.body, /Approved/);
  assert.match(document.body, /## Characterization/);
  assert.match(document.body, /surface\.brand/);
  BrandContextWorkspaceSchema.parse(withBrief);
});

test("a brief in a shape this build cannot read is no brief, not a broken page", () => {
  const mapped = toBrandContextWorkspace(
    BrandKitDetailSchema.parse({
      ...HARVESTED_BRAND_KIT,
      brand_kit_json: {
        ...(HARVESTED_BRAND_KIT as { brand_kit_json: Record<string, unknown> })
          .brand_kit_json,
        brief: { schema_version: 99, characterization: "who knows" },
      },
    }),
  );
  assert.deepEqual(mapped.knowledgeFolders, []);
  assert.ok(mapped.colorGroups.length > 0);
});

test("every asset the kit references is collected for the registry read", () => {
  assert.equal(brandKitAssetIds(kit).length, 15);
  assert.ok(brandKitAssetIds(kit).includes("asset_ing_61a219a05909b652"));
});

test("an alias naming a prototype key resolves to nothing, not to Object.prototype", () => {
  const mapped = toBrandContextWorkspace(
    BrandKitDetailSchema.parse({
      brand_kit: { id: "kit", version: 1, name: "Hostile" },
      brand_kit_json: {
        id: "kit",
        name: "Hostile",
        version: 1,
        tokens: {
          colors: {
            "surface.page": {
              value: { default: { kind: "hex", value: "#FFF" } },
            },
            "surface.card": {
              value: { default: { kind: "alias", token: "constructor" } },
            },
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

test("a registry asset with a stored thumbnail shows the thumbnail in the grid; one without falls back to its bytes", () => {
  const [withThumb, without] = toRegistryAssets(
    [
      { id: "a_thumb", kind: "raster_image", status: "ready", source: { kind: "uploaded" },
        media: { mime_type: "image/png", thumbnail: { mime_type: "image/png" } } },
      { id: "a_plain", kind: "raster_image", status: "ready", source: { kind: "uploaded" },
        media: { mime_type: "image/png" } },
    ],
    new Set(),
  );
  assert.equal(withThumb.visual.kind, "image");
  assert.equal(without.visual.kind, "image");
  if (withThumb.visual.kind !== "image" || without.visual.kind !== "image") return;
  assert.equal(withThumb.visual.thumbnailPath, "/api/clue/design/assets/a_thumb/thumbnail");
  assert.equal(withThumb.visual.imagePath, "/api/clue/design/assets/a_thumb/bytes");
  assert.equal(without.visual.thumbnailPath, undefined);
});

test("a kit asset whose registry record has a thumbnail shows it in the grid", () => {
  const kit = BrandKitDetailSchema.parse(HARVESTED_BRAND_KIT);
  const [first] = brandKitAssetIds(kit);
  const raw = HARVESTED_ASSET_RECORDS[first] as { asset: { media?: Record<string, unknown> } };
  const withThumb = {
    ...raw,
    asset: { ...raw.asset, media: { ...(raw.asset.media ?? {}), thumbnail: { mime_type: "image/png" } } },
  };
  const workspace = toBrandContextWorkspace(kit, {
    assetRecords: parseAssetRecords({ ...HARVESTED_ASSET_RECORDS, [first]: withThumb }),
    registryRecords: [],
  });
  const asset = workspace.assets.find(candidate => candidate.id === first);
  assert.ok(asset && asset.visual.kind === "image");
  if (asset?.visual.kind !== "image") return;
  assert.equal(asset.visual.thumbnailPath, `/api/clue/design/assets/${encodeURIComponent(first)}/thumbnail`);
});

test("a kit asset that was deleted (archived) is not on the page", () => {
  const kit = BrandKitDetailSchema.parse(HARVESTED_BRAND_KIT);
  const [first] = brandKitAssetIds(kit);
  const raw = HARVESTED_ASSET_RECORDS[first] as { asset: Record<string, unknown> };
  const archived = { ...raw, asset: { ...raw.asset, status: "archived" } };
  const workspace = toBrandContextWorkspace(kit, {
    assetRecords: parseAssetRecords({ ...HARVESTED_ASSET_RECORDS, [first]: archived }),
    registryRecords: [],
  });
  assert.equal(workspace.assets.some(candidate => candidate.id === first), false);
  assert.ok(workspace.assets.length > 0);
});
