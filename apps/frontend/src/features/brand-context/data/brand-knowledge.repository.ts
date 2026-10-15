import type { BrandKnowledgeFolder } from "../model/brand-context";
import {
  KnowledgeDocumentDetailSchema,
  KnowledgeTreeSchema,
  KnowledgeTreeWithBodiesSchema,
  OnboardingStatusSchema,
  toKnowledgeFolders,
  type OnboardingStatus,
} from "../model/brand-knowledge";

const READ_PREFIX = "/frontend/v1/brand-context";

async function readJson(clueFetch: typeof fetch, path: string): Promise<unknown> {
  const response = await clueFetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error(`platform API ${path} responded ${response.status}`);
  return response.json();
}

/**
 * The Knowledge folders the platform serves (Company, Product, Audience, Proof). The tree is
 * one read; each document's body is one more, issued in parallel like the asset-registry reads.
 * A refused body lists the document with an empty body; a refused tree yields no folders.
 * Never rejects — the page is a review surface, and a 500 would be a lie about the brand.
 */
export async function readBrandKnowledgeFolders(clueFetch: typeof fetch): Promise<BrandKnowledgeFolder[]> {
  // One read carries the tree and every body (2026-10-15: 37 separate body reads took 1.45 s
  // through one API process). An API without that route gets the per-document reads below.
  try {
    const full = KnowledgeTreeWithBodiesSchema.parse(await readJson(clueFetch, `${READ_PREFIX}/knowledge/full`));
    const bodies = new Map<string, string>();
    for (const document of full.folders.flatMap((folder) => folder.documents)) {
      if (document.markdown !== null) bodies.set(document.id, document.markdown);
    }
    return toKnowledgeFolders(full, bodies);
  } catch {
    // Older API, or the read failed: fall through to the tree plus one read per document.
  }
  let tree;
  try {
    tree = KnowledgeTreeSchema.parse(await readJson(clueFetch, `${READ_PREFIX}/knowledge`));
  } catch (error) {
    console.warn("[brand-context] knowledge folders unavailable; serving none:", error);
    return [];
  }
  const bodies = new Map<string, string>();
  await Promise.all(
    tree.folders.flatMap((folder) => folder.documents).map(async (document) => {
      try {
        const detail = KnowledgeDocumentDetailSchema.parse(
          await readJson(clueFetch, `${READ_PREFIX}/knowledge/documents/${encodeURIComponent(document.id)}`),
        );
        bodies.set(document.id, detail.markdown);
      } catch {
        // Listed by name, body empty — honest, and the tree is unaffected.
      }
    }),
  );
  return toKnowledgeFolders(tree, bodies);
}

/** The onboarding run's status, or `null` when the read is refused or there is no surface. */
export async function readOnboardingStatus(clueFetch: typeof fetch): Promise<OnboardingStatus | null> {
  try {
    return OnboardingStatusSchema.parse(await readJson(clueFetch, `${READ_PREFIX}/onboarding/current`));
  } catch {
    return null;
  }
}
