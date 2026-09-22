import { z } from "zod";
import { AssetContextSchema, AssetSourceSchema } from "./asset-context";

export const BrandContextSectionSchema = z.enum([
  "colors",
  "typography",
  "assets",
  "knowledge",
]);

export const BrandColorModeSchema = z.enum(["light", "dark"]);
export const BrandAssetViewSchema = z.enum(["grid", "list"]);
export const BrandAssetCategorySchema = z.enum([
  "logo",
  "background",
  "mockup",
  "upload",
  "ai-generated",
]);
export const BrandAssetSortKeySchema = z.enum(["name", "type", "size", "created"]);
export const BrandAssetSortDirectionSchema = z.enum(["ascending", "descending"]);

export const BrandColorSwatchSchema = z.object({
  id: z.string(),
  label: z.string(),
  lightValue: z.string(),
  darkValue: z.string(),
});

export const BrandColorGroupSchema = z.object({
  id: z.string(),
  label: z.string(),
  swatches: z.array(BrandColorSwatchSchema),
});

export const BrandTypefaceSchema = z.object({
  family: z.string(),
  id: z.string(),
  source: z.enum(["library", "custom"]),
  /** Namespaced per kit version so another brand's font cannot replace it. */
  previewFamily: z.string().optional(),
  faces: z.array(z.object({
    url: z.string(),
    weight: z.number().int().min(1).max(1000),
    style: z.enum(["normal", "italic"]),
  })).optional(),
});

export const BrandTextStyleSchema = z.object({
  fontFamily: z.string(),
  fontSize: z.number(),
  fontWeight: z.number(),
  id: z.string(),
  lineHeight: z.number(),
  name: z.string(),
  recommendedUse: z.string(),
});

export const BrandAssetVisualSchema = z.discriminatedUnion("kind", [
  z.object({
    imagePath: z.string(),
    kind: z.literal("image"),
  }),
  z.object({
    colors: z.array(z.string()).min(2),
    kind: z.literal("gradient"),
  }),
]);

export const BrandAssetSchema = z.object({
  context: AssetContextSchema.optional(),
  sources: z.array(AssetSourceSchema).optional(),
  category: BrandAssetCategorySchema,
  createdAt: z.string(),
  createdLabel: z.string(),
  description: z.string(),
  dimensions: z.string(),
  id: z.string(),
  name: z.string(),
  /** Where the row came from: the brand kit itself, or the workspace asset registry. */
  origin: z.enum(["kit", "registry"]),
  sizeBytes: z.number().nonnegative(),
  sizeLabel: z.string(),
  type: z.string(),
  visual: BrandAssetVisualSchema,
});

export const BrandKnowledgeDocumentSchema = z.object({
  body: z.string(),
  folderId: z.string(),
  id: z.string(),
  name: z.string(),
  path: z.string(),
  updatedLabel: z.string(),
  /** Only persisted Knowledge documents have a version; generated Design briefs do not. */
  version: z.number().int().positive().optional(),
  bodyLoaded: z.boolean().optional(),
});

export const BrandKnowledgeFolderSchema = z.object({
  documents: z.array(BrandKnowledgeDocumentSchema),
  id: z.string(),
  label: z.string(),
});

export const BrandContextWorkspaceSchema = z.object({
  assets: z.array(BrandAssetSchema),
  colorGroups: z.array(BrandColorGroupSchema),
  id: z.string(),
  knowledgeFolders: z.array(BrandKnowledgeFolderSchema),
  name: z.string(),
  textStyles: z.array(BrandTextStyleSchema),
  typefaces: z.array(BrandTypefaceSchema),
});

export type BrandAsset = z.infer<typeof BrandAssetSchema>;
export type BrandAssetCategory = z.infer<typeof BrandAssetCategorySchema>;
export type BrandAssetSortDirection = z.infer<typeof BrandAssetSortDirectionSchema>;
export type BrandAssetSortKey = z.infer<typeof BrandAssetSortKeySchema>;
export type BrandAssetView = z.infer<typeof BrandAssetViewSchema>;
export type BrandColorMode = z.infer<typeof BrandColorModeSchema>;
export type BrandContextSection = z.infer<typeof BrandContextSectionSchema>;
export type BrandContextWorkspace = z.infer<typeof BrandContextWorkspaceSchema>;
export type BrandKnowledgeDocument = z.infer<typeof BrandKnowledgeDocumentSchema>;
export type BrandKnowledgeFolder = z.infer<typeof BrandKnowledgeFolderSchema>;
export type BrandTextStyle = z.infer<typeof BrandTextStyleSchema>;
export type BrandTypeface = z.infer<typeof BrandTypefaceSchema>;

export interface BrandContextInitialState {
  assetId?: string;
  assetView: BrandAssetView;
  colorMode: BrandColorMode;
  filePath?: string;
  section: BrandContextSection;
}
