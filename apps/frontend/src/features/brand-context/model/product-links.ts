import type { BrandKnowledgeDocument } from "./brand-context";
import type { BrandProduct } from "./brand-knowledge";

/** A product page is about exactly one product; any other document may name several. */
export const PRODUCT_PAGE_KIND = "product-research";

/** The product a document is the main page of, when it is one (spec 2026-10-15 §4.1). */
export function productOfPage(
  document: BrandKnowledgeDocument, products: readonly BrandProduct[],
): BrandProduct | undefined {
  if (document.kind !== PRODUCT_PAGE_KIND) return undefined;
  return products.find((product) => product.pageDocumentId === document.id);
}

/** The names of the products a document is about, in list order, for the editor header. */
export function linkedProductNames(
  document: BrandKnowledgeDocument, products: readonly BrandProduct[],
): string[] {
  const ids = document.productIds ?? [];
  return products.filter((product) => ids.includes(product.productId)).map((product) => product.name);
}

/** Only documents in the Product folder name products — never the company overview, an
 * audience file or the generated catalog (founder ruling 2026-10-15). */
export const PRODUCT_FOLDER = "product";

export function canLinkProducts(document: BrandKnowledgeDocument): boolean {
  return document.folderId === PRODUCT_FOLDER && !document.generated && Boolean(document.version);
}
