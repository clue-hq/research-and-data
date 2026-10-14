import type { BrandKnowledgeDocument } from "../model/brand-context";
import {
  BrandProductsSchema,
  KnowledgeDocumentDetailSchema,
  ProductChangeSchema,
  toKnowledgeDocument,
  type BrandProducts,
  type ProductChange,
} from "../model/brand-knowledge";

/** Server-side reads go straight to the platform; browser writes go through the BFF. */
const READ_PREFIX = "/frontend/v1/brand-context";
const WRITE_PREFIX = "/api/clue/frontend/v1/brand-context";

/**
 * The brand's product list with each product's page and the last 30 days of changes, or `null`
 * when the read is refused — the Product folder then shows no product actions, never an error.
 */
export async function readBrandProducts(clueFetch: typeof fetch): Promise<BrandProducts | null> {
  try {
    const response = await clueFetch(`${READ_PREFIX}/products`, { cache: "no-store" });
    if (!response.ok) return null;
    return BrandProductsSchema.parse(await response.json());
  } catch {
    return null;
  }
}

async function refusal(response: Response): Promise<Error> {
  if (response.status === 401 || response.status === 403) {
    return new Error("You do not have permission to change products.");
  }
  try {
    const body = (await response.json()) as { error?: { message?: unknown } };
    if (typeof body.error?.message === "string" && body.error.message) {
      return new Error(body.error.message);
    }
  } catch {
    // Fall through to the generic sentence.
  }
  return new Error("Could not change the products. Please try again.");
}

async function send(
  path: string, method: "POST" | "PUT", body: unknown, clueFetch: typeof fetch,
): Promise<Response> {
  let response: Response;
  try {
    response = await clueFetch(`${WRITE_PREFIX}${path}`, {
      method, cache: "no-store",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error("Could not reach the platform. Nothing was changed; please try again.");
  }
  if (!response.ok) throw await refusal(response);
  return response;
}

async function change(path: string, body: unknown, clueFetch: typeof fetch): Promise<ProductChange> {
  const response = await send(path, "POST", body, clueFetch);
  return ProductChangeSchema.parse(await response.json());
}

const id = encodeURIComponent;

export function addProduct(
  input: { name: string; description?: string }, clueFetch: typeof fetch = fetch,
): Promise<ProductChange> {
  return change("/products", input, clueFetch);
}

export function renameProduct(productId: string, name: string, clueFetch: typeof fetch = fetch): Promise<ProductChange> {
  return change(`/products/${id(productId)}/rename`, { name }, clueFetch);
}

export function mergeProducts(
  input: { productIds: string[]; intoProductId?: string; newName?: string }, clueFetch: typeof fetch = fetch,
): Promise<ProductChange> {
  return change("/products/merge", input, clueFetch);
}

export function removeProduct(productId: string, clueFetch: typeof fetch = fetch): Promise<ProductChange> {
  return change(`/products/${id(productId)}/remove`, undefined, clueFetch);
}

export function undoProductChange(changeId: string, clueFetch: typeof fetch = fetch): Promise<ProductChange> {
  return change(`/product-changes/${id(changeId)}/undo`, undefined, clueFetch);
}

/**
 * Point a document at the products it is about (the editor's Products picker). The current body
 * is saved again unchanged with the chosen ids, so the link is a new version like any edit.
 */
export async function linkDocumentProducts(
  document: BrandKnowledgeDocument, productIds: string[], clueFetch: typeof fetch = fetch,
): Promise<BrandKnowledgeDocument> {
  if (!document.version || document.bodyLoaded === false) {
    throw new Error("This document is not available for editing.");
  }
  const response = await send(
    `/knowledge/documents/${id(document.id)}`, "PUT",
    { body: document.body, expectedRevision: document.version, productIds }, clueFetch,
  );
  const saved = KnowledgeDocumentDetailSchema.parse(await response.json());
  return toKnowledgeDocument(saved, document.folderId, saved.markdown);
}
