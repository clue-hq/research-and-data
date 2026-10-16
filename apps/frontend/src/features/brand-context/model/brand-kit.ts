import { z } from "zod";
import { BrandBriefSchema } from "./brand-brief";

/**
 * Slice 1: the design API's brand-kit wire shapes — the REAL store behind the
 * Brand-context page.
 *
 * The canonical model is the Rust `BrandKit`
 * (`subsystems/clue-design/crates/lumen-core/src/brand.rs:193`); these schemas
 * cover only the slice of it the page reads (colors, typography, fonts, logos,
 * images) and deliberately stop there — `z.object` strips what it does not
 * name, so a kit growing new fields never breaks this seam.
 *
 * Token maps are parsed ENTRY-TOLERANTLY (`.nullable().catch(null)`): one
 * token in an unrecognized shape drops that swatch, it never blanks the whole
 * page. Everything else is strict, because a malformed envelope means we are
 * not talking to the design API at all.
 */

/** One value plus its per-mode overrides, keyed `"<axis>.<value>"` (`theme.dark`). */
const BrandModeValueSchema = <T extends z.ZodTypeAny>(value: T) =>
  z.object({
    default: value,
    modes: z.record(z.string(), value).optional(),
  });

export const BrandColorTokenValueSchema = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("hex"), value: z.string().min(1) }),
  z.object({
    kind: z.literal("oklch"),
    l: z.number(),
    c: z.number(),
    h: z.number(),
    alpha: z.number().nullish(),
  }),
  z.object({ kind: z.literal("alias"), token: z.string().min(1) }),
]);

/**
 * Where a token's value came from (`TokenProvenance`): `website:<page> :: <what was measured>`,
 * `derived:…` or `default:…`. The Brand page says "Measured" from it (Task X6). A provenance in a
 * shape this build cannot read is no provenance, never a dropped token.
 */
const BrandTokenProvenanceSchema = z
  .object({ source: z.string(), confidence: z.number().nullish() })
  .nullish()
  .catch(null);

export const BrandColorTokenSchema = z.object({
  value: BrandModeValueSchema(BrandColorTokenValueSchema),
  role: z.string().nullish(),
  description: z.string().nullish(),
  provenance: BrandTokenProvenanceSchema,
});

export const BrandTypographyTokenValueSchema = z.discriminatedUnion("kind", [
  z.object({
    kind: z.literal("style"),
    font_family: z.string().min(1),
    font_size: z.number(),
    font_weight: z.number(),
    /** A unitless multiplier — the engine's `font_size * line_height` (text_measure.rs:563). */
    line_height: z.number().nullish(),
    letter_spacing: z.number().nullish(),
    color: z.string().nullish(),
    /** The kit font this style uses (`assets.fonts` key): how a sample finds its fallback stack. */
    font_asset: z.string().nullish(),
  }),
  z.object({ kind: z.literal("alias"), token: z.string().min(1) }),
]);

export const BrandTypographyTokenSchema = z.object({
  value: BrandModeValueSchema(BrandTypographyTokenValueSchema),
  role: z.string().nullish(),
  description: z.string().nullish(),
  provenance: BrandTokenProvenanceSchema,
});

/** `NumberToken` (brand.rs): spacing, radii, stroke widths, opacity and other numbers. */
export const BrandNumberTokenValueSchema = z.discriminatedUnion("kind", [
  z.object({
    kind: z.literal("number"),
    value: z.number(),
    unit: z.enum(["unitless", "px", "mm", "percent", "ratio"]),
  }),
  z.object({ kind: z.literal("alias"), token: z.string().min(1) }),
]);

export const BrandNumberTokenSchema = z.object({
  value: BrandModeValueSchema(BrandNumberTokenValueSchema),
  role: z.string().nullish(),
  description: z.string().nullish(),
  provenance: BrandTokenProvenanceSchema,
});

/** `ShadowToken` (brand.rs): one shadow layer; a measured multi-layer shadow is several tokens. */
export const BrandShadowTokenSchema = z.object({
  value: BrandModeValueSchema(
    z.object({ x: z.number(), y: z.number(), blur: z.number(), spread: z.number(), color: z.string().min(1) }),
  ),
  description: z.string().nullish(),
  provenance: BrandTokenProvenanceSchema,
});

/**
 * `StyleToken` (brand.rs, Wave 2 A9 Task X1): the measured values the other groups cannot hold —
 * keywords, durations, easings, transforms, keyframes, animations, reveals and icons.
 */
export const BrandStyleTokenValueSchema = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("keyword"), property: z.string(), value: z.string() }),
  z.object({ kind: z.literal("duration"), ms: z.number() }),
  z.object({ kind: z.literal("easing"), function: z.string() }),
  z.object({ kind: z.literal("transform"), value: z.string() }),
  z.object({
    kind: z.literal("keyframes"),
    frames: z.array(z.object({ offset: z.number(), declarations: z.record(z.string(), z.string()) })),
  }),
  z.object({
    kind: z.literal("animation"),
    keyframes: z.string(),
    duration: z.string(),
    easing: z.string(),
    delay: z.string().nullish(),
    iterations: z.string(),
    direction: z.string(),
    fill_mode: z.string(),
  }),
  z.object({
    kind: z.literal("reveal"),
    from_opacity: z.string().nullish(),
    from_transform: z.string().nullish(),
    duration: z.string(),
    easing: z.string(),
  }),
  z.object({ kind: z.literal("glyph"), text: z.string() }),
  z.object({ kind: z.literal("svg"), markup: z.string(), width: z.number(), height: z.number() }),
  z.object({ kind: z.literal("alias"), token: z.string().min(1) }),
]);

export const BrandStyleTokenSchema = z.object({
  value: BrandModeValueSchema(BrandStyleTokenValueSchema),
  description: z.string().nullish(),
  provenance: BrandTokenProvenanceSchema,
});

const TokenNameSchema = z.string().min(1).max(160);
const SlotsSchema = z.record(z.string(), TokenNameSchema);

/** One measured style of `MeasuredComponents@1` (Task X5): its slots name kit tokens. */
export const BrandMeasuredStyleSchema = z.object({
  component: z.string().min(1),
  variant: z.string().min(1),
  count: z.number().int().min(1),
  probed: z.string(),
  source: z.string(),
  rest: SlotsSchema.default({}),
  states: z
    .object({
      hover: SlotsSchema.optional(),
      pressed: SlotsSchema.optional(),
      focus: SlotsSchema.optional(),
      disabled: SlotsSchema.optional(),
    })
    .default({}),
  motion: z
    .array(
      z.object({
        target: z.enum(["self", "label", "icon"]),
        property: z.string(),
        duration: TokenNameSchema,
        easing: TokenNameSchema,
        delay: TokenNameSchema.nullish(),
      }),
    )
    .default([]),
  icon: z.object({ token: TokenNameSchema, position: z.enum(["start", "end"]) }).nullish(),
  browser_focus_ring: z.boolean().default(false),
});

/**
 * `MeasuredComponents@1` (Wave 2 A9, Task X5): what the extraction measured, by style, as kit token
 * names. Entry-tolerant like the token maps: one unreadable style drops itself, not the section.
 */
export const BrandMeasuredComponentsSchema = z.object({
  schema_version: z.literal(1),
  source: z.string(),
  styles: z
    .array(BrandMeasuredStyleSchema.nullable().catch(null))
    .transform((styles) => styles.filter((style) => style !== null)),
  motion: z
    .object({
      animations: z.array(TokenNameSchema).default([]),
      reveals: z.array(TokenNameSchema).default([]),
      scripted: z.array(z.object({ kind: z.enum(["scripted", "canvas", "video"]), where: z.string() })).default([]),
    })
    .default({ animations: [], reveals: [], scripted: [] }),
});

/** `constraints.contrast_pairs`: which text colour each surface carries (a band's measured ink). */
const BrandContrastPairSchema = z.object({
  foreground: z.string().min(1),
  background: z.string().min(1),
  min_ratio: z.number().nullish(),
});

export const BrandFontAssetSchema = z.object({
  family: z.string().min(1),
  /** The kit's own fallback families for this font: a sample draws with them (site-kit `fontStack`). */
  fallback_stack: z.array(z.string()).nullish().catch(null),
  /** `AssetSource` (assets.rs:129) — `system` is a platform family, anything else is the brand's own. */
  source: z.object({ kind: z.string() }).nullish(),
  faces: z.array(z.object({
    weight: z.number().int().min(1).max(1000),
    style: z.enum(["normal", "italic"]),
    asset_id: z.string().min(1).nullish(),
    source_url: z.string().nullish(),
  }).nullable().catch(null)).nullish(),
});

export const BrandLogoVariantSchema = z.object({
  name: z.string().nullish(),
  asset_id: z.string().min(1),
  color_mode: z.string().nullish(),
  width: z.number().nullish(),
  height: z.number().nullish(),
});

export const BrandLogoAssetSchema = z.object({
  variants: z.array(BrandLogoVariantSchema).nullish(),
  usage: z.string().nullish(),
  title: z.string().nullish(),
  description: z.string().nullish(),
  usage_note: z.string().nullish(),
});

export const BrandImageAssetSchema = z.object({
  asset_id: z.string().min(1),
  /** `photo | illustration | screenshot | icon | og_image` (evidence.py:130). */
  role: z.string().nullish(),
  mime_type: z.string().nullish(),
  title: z.string().nullish(),
  description: z.string().nullish(),
  usage_note: z.string().nullish(),
});

const tolerant = <T extends z.ZodTypeAny>(entry: T) =>
  z.record(z.string(), entry.nullable().catch(null)).optional();

/**
 * One recorded provenance of the kit (`BrandSource`). Slice 4 reads the website a kit was
 * ingested from so Re-extract can re-run the SAME site; entry-tolerant like the token maps.
 */
export const BrandSourceSchema = z.object({
  url: z.string().nullish(),
  kind: z.string().nullish(),
});

export const BrandKitJsonSchema = z.object({
  id: z.string().min(1),
  name: z.string(),
  version: z.number(),
  approval_status: z.string().nullish(),
  sources: z.array(BrandSourceSchema.nullable().catch(null)).nullish(),
  tokens: z
    .object({
      colors: tolerant(BrandColorTokenSchema),
      typography: tolerant(BrandTypographyTokenSchema),
      // Wave 2 A9 (Task X6): the Brand page draws each measured style from its own tokens, so the
      // read keeps every group that names one. They were stripped here before.
      numbers: tolerant(BrandNumberTokenSchema),
      spacing: tolerant(BrandNumberTokenSchema),
      radii: tolerant(BrandNumberTokenSchema),
      stroke_widths: tolerant(BrandNumberTokenSchema),
      opacity: tolerant(BrandNumberTokenSchema),
      shadows: tolerant(BrandShadowTokenSchema),
      styles: tolerant(BrandStyleTokenSchema),
    })
    .nullish(),
  constraints: z
    .object({
      contrast_pairs: z
        .array(BrandContrastPairSchema.nullable().catch(null))
        .transform((pairs) => pairs.filter((pair) => pair !== null))
        .nullish()
        .catch(null),
    })
    .nullish()
    .catch(null),
  assets: z
    .object({
      fonts: tolerant(BrandFontAssetSchema),
      logos: tolerant(BrandLogoAssetSchema),
      images: tolerant(BrandImageAssetSchema),
    })
    .nullish(),
  /**
   * The per-brand Creative Brief (`BrandBrief@1`), written by the ingestion
   * brief agent and riding this kit version. Absent on every kit ingested before
   * the brief existed, and on any kit whose brief was refused — which is a valid,
   * honest state, so it is `nullish`, never required. `.catch(null)`: a brief in
   * a shape this build cannot read is no brief, never a broken page.
   */
  brief: BrandBriefSchema.nullish().catch(null),
  /**
   * What the extraction measured on the seller's site, by style (Wave 2 A9, Tasks X5/X6). Absent on
   * every kit made before measurement — an honest state, so `nullish`; `.catch(null)`: a section in
   * a shape this build cannot read is no section, never a broken page.
   */
  measured_components: BrandMeasuredComponentsSchema.nullish().catch(null),
});

/** `brand_kit_summary` (dto.py:71) — the list row and the detail envelope's header. */
export const BrandKitSummarySchema = z.object({
  id: z.string().min(1),
  version: z.number(),
  name: z.string(),
  approval_status: z.string().nullish(),
  created_at: z.string().nullish(),
  updated_at: z.string().nullish(),
});

export const BrandKitSummaryListSchema = z.array(BrandKitSummarySchema);

/** `brand_kit_detail_dto` (dto.py:103) — `GET /brand-kits/{id}`. */
export const BrandKitDetailSchema = z.object({
  brand_kit: BrandKitSummarySchema,
  brand_kit_json: BrandKitJsonSchema,
});

/**
 * `GET /assets/{asset_id}` — the asset REGISTRY record. The kit carries only
 * an `asset_id`; the filename, media type, byte length and vector geometry the
 * assets panel displays live here (main.py:6113).
 */
export const DesignAssetRecordSchema = z.object({
  asset: z.object({
    id: z.string().min(1),
    label: z.string().nullish(),
    media: z
      .object({
        mime_type: z.string().nullish(),
        byte_length: z.number().nullish(),
        filename: z.string().nullish(),
        // Present when the store holds a thumbnail; the grid shows it instead of the bytes.
        thumbnail: z.object({ mime_type: z.string().nullish() }).passthrough().nullish(),
      })
      .nullish(),
    raster: z
      .object({ width: z.number().nullish(), height: z.number().nullish() })
      .nullish(),
    vector: z
      .object({ width: z.number().nullish(), height: z.number().nullish() })
      .nullish(),
  }),
  created_at: z.string().nullish(),
});

/**
 * One bare record from `GET /assets` (main.py:6993). The LIST route serves
 * `public_asset_record` rows directly — not the `{asset, created_at}` envelope
 * `GET /assets/{id}` returns — so it gets its own schema. Deliberately loose on
 * `kind`/`status`/`source.kind`: the registry's vocabularies grow, and an
 * unrecognized value must degrade one row, never the page.
 */
export const DesignAssetListRecordSchema = z.object({
  id: z.string().min(1),
  kind: z.string(),
  label: z.string().nullish(),
  status: z.string(),
  source: z.object({ kind: z.string() }).passthrough(),
  media: z
    .object({
      mime_type: z.string().nullish(),
      byte_length: z.number().nullish(),
      filename: z.string().nullish(),
      thumbnail: z.object({ mime_type: z.string().nullish() }).passthrough().nullish(),
    })
    .nullish(),
  raster: z
    .object({ pixel_width: z.number().nullish(), pixel_height: z.number().nullish() })
    .nullish(),
  vector: z
    .object({ width: z.number().nullish(), height: z.number().nullish() })
    .nullish(),
  provenance: z.object({ created_at: z.string().nullish() }).nullish(),
});

export type BrandColorToken = z.infer<typeof BrandColorTokenSchema>;
export type BrandMeasuredComponents = z.infer<typeof BrandMeasuredComponentsSchema>;
export type BrandFontAsset = z.infer<typeof BrandFontAssetSchema>;
export type BrandImageAsset = z.infer<typeof BrandImageAssetSchema>;
export type BrandLogoAsset = z.infer<typeof BrandLogoAssetSchema>;
export type BrandTypographyToken = z.infer<typeof BrandTypographyTokenSchema>;
export type BrandKitDetail = z.infer<typeof BrandKitDetailSchema>;
export type BrandKitJson = z.infer<typeof BrandKitJsonSchema>;
export type BrandKitSummary = z.infer<typeof BrandKitSummarySchema>;
export type DesignAssetListRecord = z.infer<typeof DesignAssetListRecordSchema>;
export type DesignAssetRecord = z.infer<typeof DesignAssetRecordSchema>;
