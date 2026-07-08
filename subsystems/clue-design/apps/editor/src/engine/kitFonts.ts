import type { BrandKitDetailPayload } from "./tokenColors";
import { registerKitFontFaces } from "./canvaskit/loadCanvasKit";

/**
 * K3 (canvas leg): fetch the attached kit's font-face bytes from the asset
 * store and register them into the CanvasKit font provider, so on-canvas
 * text shapes and measures in the kit's real faces — the same bytes the
 * server helper loads for preflight measurement and export.
 *
 * Fetch failures skip the face (the canvas keeps its current fallback);
 * registration dedupes by asset id, so a kit refetch never re-downloads or
 * double-registers a face.
 */

interface KitFontFaceRef {
  assetId: string;
  family: string;
}

/** The kit's registrable faces: every `assets.fonts[*].faces[]` entry that
 * names a stored asset, tagged with its group's declared family. */
export function collectKitFontFaceRefs(
  kit: BrandKitDetailPayload | null | undefined
): KitFontFaceRef[] {
  const fonts = (kit as { assets?: { fonts?: unknown } } | null | undefined)?.assets?.fonts;
  if (!fonts || typeof fonts !== "object") {
    return [];
  }
  const refs: KitFontFaceRef[] = [];
  for (const group of Object.values(fonts as Record<string, unknown>)) {
    if (!group || typeof group !== "object") {
      continue;
    }
    const family = (group as { family?: unknown }).family;
    const faces = (group as { faces?: unknown }).faces;
    if (typeof family !== "string" || family.length === 0 || !Array.isArray(faces)) {
      continue;
    }
    for (const face of faces) {
      const assetId = (face as { asset_id?: unknown } | null)?.asset_id;
      if (typeof assetId === "string" && assetId.length > 0) {
        refs.push({ assetId, family });
      }
    }
  }
  return refs;
}

export interface LoadKitFontFacesOptions {
  apiBaseUrl: string;
  fetchImpl?: typeof fetch;
}

/** Fetch + register the kit's faces. Resolves true when at least one new
 * face landed in a live provider (the caller should then invalidate text
 * measurement/render memos). */
export async function loadKitFontFaces(
  { apiBaseUrl, fetchImpl }: LoadKitFontFacesOptions,
  kit: BrandKitDetailPayload | null | undefined
): Promise<boolean> {
  const refs = collectKitFontFaceRefs(kit);
  if (refs.length === 0) {
    return false;
  }
  const doFetch: typeof fetch | undefined =
    fetchImpl ?? (typeof fetch !== "undefined" ? (input, init) => fetch(input, init) : undefined);
  if (!doFetch) {
    return false;
  }
  const faces = await Promise.all(
    refs.map(async (ref) => {
      try {
        const response = await doFetch(
          new URL(`/assets/${encodeURIComponent(ref.assetId)}/bytes`, apiBaseUrl)
        );
        if (!response.ok) {
          return null;
        }
        const bytes = await response.arrayBuffer();
        return { key: `${ref.family}@${ref.assetId}`, family: ref.family, bytes };
      } catch {
        return null;
      }
    })
  );
  const loaded = faces.filter((face): face is NonNullable<typeof face> => face !== null);
  if (loaded.length === 0) {
    return false;
  }
  // DOM leg: register the same bytes into document.fonts under the declared
  // family so DOM-rendered surfaces (e.g. the Export Preview SVG, which
  // references the family by NAME — the trial faces are non-embeddable so
  // their bytes are never inlined) render kit type instead of a default
  // serif. Purely local display of already-fetched bytes; it does not touch
  // export/embedding. Failures are swallowed so the canvas leg is unaffected.
  await registerKitFontFacesInDom(loaded);
  return registerKitFontFaces(loaded);
}

const registeredDomFaceKeys = new Set<string>();

/** Test-only: forget which faces were registered into document.fonts so each
 * case starts from a clean DOM registry. */
export function resetKitDomFontsForTests(): void {
  registeredDomFaceKeys.clear();
}

/** Feed already-fetched kit face bytes to the browser's DOM font registry
 * (`document.fonts`). Keyed by the same `family@assetId` as the CanvasKit
 * leg, so a kit refetch never double-adds a face. No-op (and never throws)
 * where FontFace/document.fonts are unavailable (jsdom/tests). */
async function registerKitFontFacesInDom(
  faces: { key: string; family: string; bytes: ArrayBuffer }[]
): Promise<void> {
  if (typeof FontFace === "undefined" || typeof document === "undefined" || !document.fonts) {
    return;
  }
  await Promise.all(
    faces.map(async (face) => {
      if (registeredDomFaceKeys.has(face.key)) {
        return;
      }
      registeredDomFaceKeys.add(face.key);
      try {
        const fontFace = new FontFace(face.family, face.bytes);
        await fontFace.load();
        document.fonts.add(fontFace);
      } catch (error) {
        // A DOM font registration failure must not affect the canvas leg.
        registeredDomFaceKeys.delete(face.key);
        console.warn(`Failed to register kit font face "${face.family}" into document.fonts`, error);
      }
    })
  );
}
