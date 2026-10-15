import { BrandContextSectionSchema, type BrandContextSection, type BrandKnowledgeDocument } from "./brand-context";

/** Where Brand context opens when a link names no section: the company overview, which is the
 * lightest page to load and the first thing a person reads (founder request 2026-10-15). */
export const LANDING_DOCUMENT_PATH = "company/overview.md";
export const CATALOG_PATH = "product/catalog.md";

export function brandContextLanding(query: { section?: string; file?: string }): {
  section: BrandContextSection;
  filePath: string | undefined;
} {
  const section = BrandContextSectionSchema.safeParse(query.section);
  if (!section.success) return { section: "knowledge", filePath: query.file ?? LANDING_DOCUMENT_PATH };
  return { section: section.data, filePath: query.file };
}

/**
 * The document to show for a chosen path. A path that no longer exists — a renamed, merged or
 * removed product's page — falls back to the product catalog (where the change shows) rather than
 * silently to the first document; no choice at all shows the first document.
 */
export function pickSelectedDocument<D extends BrandKnowledgeDocument>(
  documents: readonly D[], path: string,
): D | undefined {
  const chosen = documents.find((document) => document.path === path);
  if (chosen) return chosen;
  if (path) {
    const catalog = documents.find((document) => document.path === CATALOG_PATH);
    if (catalog) return catalog;
  }
  return documents[0];
}
