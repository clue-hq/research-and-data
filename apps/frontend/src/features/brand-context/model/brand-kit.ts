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

export const BrandColorTokenSchema = z.object({
  value: BrandModeValueSchema(BrandColorTokenValueSchema),
  role: z.string().nullish(),
  description: z.string().nullish(),
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
  }),
  z.object({ kind: z.literal("alias"), token: z.string().min(1) }),
]);

export const BrandTypographyTokenSchema = z.object({
  value: BrandModeValueSchema(BrandTypographyTokenValueSchema),
  role: z.string().nullish(),
  description: z.string().nullish(),
});

export const BrandFontAssetSchema = z.object({
  family: z.string().min(1),
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
    })
    .nullish(),
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
export type BrandFontAsset = z.infer<typeof BrandFontAssetSchema>;
export type BrandImageAsset = z.infer<typeof BrandImageAssetSchema>;
export type BrandLogoAsset = z.infer<typeof BrandLogoAssetSchema>;
export type BrandTypographyToken = z.infer<typeof BrandTypographyTokenSchema>;
export type BrandKitDetail = z.infer<typeof BrandKitDetailSchema>;
export type BrandKitJson = z.infer<typeof BrandKitJsonSchema>;
export type BrandKitSummary = z.infer<typeof BrandKitSummarySchema>;
export type DesignAssetListRecord = z.infer<typeof DesignAssetListRecordSchema>;
export type DesignAssetRecord = z.infer<typeof DesignAssetRecordSchema>;
