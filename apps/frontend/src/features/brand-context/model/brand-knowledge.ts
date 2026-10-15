import { z } from "zod";

import type { BrandKnowledgeDocument, BrandKnowledgeFolder } from "./brand-context";
import { dateLabel } from "./brand-context-mapping";

/** The four platform-served folders, in the dummy's order. Design is the brand kit's. */
export const KnowledgeFolderKeySchema = z.enum(["company", "product", "audience", "proof"]);

export const KnowledgeDocumentSchema = z
  .object({
    icpKey: z.string().nullable(),
    id: z.string(),
    kind: z.string(),
    path: z.string(),
    productId: z.string().nullable(),
    /** Every product the document names (spec 2026-10-15 §4.1). */
    productIds: z.array(z.string()).default([]),
    /** The catalog generated from the product list: read-only here. */
    generated: z.boolean().default(false),
    status: z.string(),
    title: z.string(),
    updatedAt: z.string(),
    version: z.number().int(),
  })
  .passthrough();

export const KnowledgeTreeSchema = z.object({
  brandId: z.string().nullable(),
  folders: z.array(
    z.object({
      documents: z.array(KnowledgeDocumentSchema),
      key: KnowledgeFolderKeySchema,
      label: z.string(),
    }),
  ),
});

export const KnowledgeSourceSchema = z.object({
  confidence: z.string().nullable(),
  section: z.string(),
  title: z.string().nullable(),
  url: z.string(),
});

export const KnowledgeDocumentDetailSchema = KnowledgeDocumentSchema.extend({
  frontMatter: z.record(z.string(), z.unknown()),
  markdown: z.string(),
  sources: z.array(KnowledgeSourceSchema),
});

export const OnboardingStepSchema = z.object({
  costUsd: z.string(),
  failureCode: z.string().nullable(),
  finishedAt: z.string().nullable(),
  kind: z.string(),
  phase: z.string(),
  startedAt: z.string().nullable(),
  status: z.string(),
  subjectRef: z.string().nullable(),
});

export const OnboardingStatusSchema = z.object({
  costUsd: z.string(),
  runId: z.string().nullable(),
  status: z.string(),
  steps: z.array(OnboardingStepSchema),
});

/** One product on the brand's list, with its page (spec 2026-10-15 §10). */
export const BrandProductSchema = z.object({
  aliases: z.array(z.string()),
  name: z.string(),
  pageDocumentId: z.string().nullable(),
  pagePath: z.string().nullable(),
  pagePending: z.boolean(),
  productId: z.string(),
});

export const ProductChangeLineSchema = z.object({
  changeId: z.string(),
  createdAt: z.string(),
  kind: z.string(),
  text: z.string(),
  undoable: z.boolean(),
});

export const BrandProductsSchema = z.object({
  brandId: z.string().nullable(),
  products: z.array(BrandProductSchema),
  recentChanges: z.array(ProductChangeLineSchema),
});

/** What one add / rename / merge / remove / undo did. */
export const ProductChangeSchema = z.object({
  changeId: z.string(),
  kind: z.string(),
  pageDocumentId: z.string().nullable(),
  /** Where the product's page lives now; the editor follows it after a rename. */
  pagePath: z.string().nullable().default(null),
  pagePending: z.boolean(),
  productId: z.string(),
  productName: z.string(),
  projectsNeedingChoice: z.number().int(),
  projectsUpdated: z.number().int(),
  text: z.string(),
});

export type BrandProduct = z.infer<typeof BrandProductSchema>;
export type BrandProducts = z.infer<typeof BrandProductsSchema>;
export type ProductChange = z.infer<typeof ProductChangeSchema>;
export type ProductChangeLine = z.infer<typeof ProductChangeLineSchema>;

export type KnowledgeTree = z.infer<typeof KnowledgeTreeSchema>;
export type KnowledgeDocumentDetail = z.infer<typeof KnowledgeDocumentDetailSchema>;
export type OnboardingStatus = z.infer<typeof OnboardingStatusSchema>;

/** A run that can still publish documents. */
export function onboardingRunIsLive(status: OnboardingStatus | null): boolean {
  return status?.status === "queued" || status?.status === "running";
}

/**
 * Map the platform tree onto the dummy's Knowledge shape. `bodies` holds the markdown per
 * document id; a document whose body was not read lists with an empty body (the page then
 * shows an empty preview, never an error surface it does not have).
 */
export function toKnowledgeFolders(tree: KnowledgeTree, bodies: Map<string, string>): BrandKnowledgeFolder[] {
  return tree.folders.map((folder) => ({
    documents: folder.documents.map((document) => toKnowledgeDocument(document, folder.key, bodies.get(document.id))),
    id: folder.key,
    label: folder.label,
  }));
}

export function toKnowledgeDocument(
  document: z.infer<typeof KnowledgeDocumentSchema>, folderId: string, body?: string,
): BrandKnowledgeDocument {
  return {
    body: body ?? "", bodyLoaded: body !== undefined, folderId, id: document.id,
    name: document.title, path: document.path, version: document.version,
    updatedLabel: `Updated ${dateLabel(document.updatedAt)}`,
    kind: document.kind, productIds: document.productIds, generated: document.generated,
  };
}
