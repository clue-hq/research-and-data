import { z } from "zod";

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
  "ai-generated",
]);
export const BrandAssetSortKeySchema = z.enum(["name", "type", "size", "created"]);
export const BrandAssetSortDirectionSchema = z.enum(["ascending", "descending"]);
export const BrandDocumentModeSchema = z.enum(["preview", "edit"]);

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
  category: BrandAssetCategorySchema,
  createdAt: z.string(),
  createdLabel: z.string(),
  description: z.string(),
  dimensions: z.string(),
  id: z.string(),
  name: z.string(),
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
export type BrandDocumentMode = z.infer<typeof BrandDocumentModeSchema>;
export type BrandKnowledgeDocument = z.infer<typeof BrandKnowledgeDocumentSchema>;
export type BrandTextStyle = z.infer<typeof BrandTextStyleSchema>;
export type BrandTypeface = z.infer<typeof BrandTypefaceSchema>;

export interface BrandContextInitialState {
  assetId?: string;
  assetView: BrandAssetView;
  colorMode: BrandColorMode;
  documentMode: BrandDocumentMode;
  filePath?: string;
  section: BrandContextSection;
}

export interface MarkdownBlock {
  depth?: number;
  items?: string[];
  text?: string;
  type: "heading" | "paragraph" | "list";
}

export function parseKnowledgeMarkdown(source: string): MarkdownBlock[] {
  const lines = source.split("\n");
  const blocks: MarkdownBlock[] = [];
  let paragraph: string[] = [];
  let listItems: string[] = [];

  function flushParagraph() {
    if (!paragraph.length) return;
    blocks.push({ text: paragraph.join(" "), type: "paragraph" });
    paragraph = [];
  }

  function flushList() {
    if (!listItems.length) return;
    blocks.push({ items: listItems, type: "list" });
    listItems = [];
  }

  for (const line of lines) {
    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    const listItem = /^[-*]\s+(.+)$/.exec(line);

    if (heading) {
      flushParagraph();
      flushList();
      blocks.push({
        depth: heading[1].length,
        text: heading[2],
        type: "heading",
      });
      continue;
    }

    if (listItem) {
      flushParagraph();
      listItems.push(listItem[1]);
      continue;
    }

    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }

    flushList();
    paragraph.push(line.trim());
  }

  flushParagraph();
  flushList();
  return blocks;
}
