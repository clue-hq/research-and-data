import type { BrandKitDetailPayload } from "./tokenColors";
import type { Diagnostic } from "./contracts";
import { fontFaceDescriptors, registerKitFontFaces } from "./canvaskit/loadCanvasKit";
import { effectiveFaceMeta } from "./canvaskit/fontFaces";
import { lumenFetch } from "./editorConfig";

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
  /** A7b (D5): kit-declared weight/style. Fallback metadata for BOTH legs —
   * the face's byte-parsed OS/2 meta wins when it parses (server truth): the
   * CanvasKit leg keys its style-qualified alias on it, and the DOM leg's
   * `FontFace` descriptors register the face distinctly instead of colliding
   * at the (family, normal, 400) default. */
  weight?: number;
  style?: string;
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
        const weight = (face as { weight?: unknown } | null)?.weight;
        const style = (face as { style?: unknown } | null)?.style;
        refs.push({
          assetId,
          family,
          weight: typeof weight === "number" ? weight : undefined,
          style: typeof style === "string" ? style : undefined
        });
      }
    }
  }
  return refs;
}

export interface LoadKitFontFacesOptions {
  apiBaseUrl: string;
  fetchImpl?: typeof fetch;
  /**
   * Called once per kit face that could NOT be fetched/registered. Previously
   * these failures were swallowed (the face was skipped and the canvas kept a
   * fallback), so the client stayed silent while the server logs LUMS0101 for
   * the same miss. The editor passes a sink that surfaces these as client
   * diagnostics so the client/server asymmetry is closed.
   */
  onFaceDiagnostic?: (diagnostic: Diagnostic) => void;
}

/** Client mirror of the server's LUMS0101 per-face warning: a declared kit
 * face whose bytes could not be loaded, so canvas/DOM text keeps a fallback. */
function kitFontFaceDiagnostic(ref: KitFontFaceRef, reason: string): Diagnostic {
  return {
    severity: "warning",
    phase: "brand",
    code: "EDITOR_KIT_FONT_FACE_UNAVAILABLE",
    message: `Brand Kit font “${ref.family}” face ${ref.assetId} could not be loaded (${reason}); canvas and preview keep a fallback face for it.`,
    subject: { kind: "asset", id: ref.assetId },
    hint: "Re-attach the Brand Kit or confirm the font asset is present in the asset store; export uses the same faces."
  };
}

/** Fetch + register the kit's faces. Resolves true when at least one new
 * face landed in a live provider (the caller should then invalidate text
 * measurement/render memos). */
export async function loadKitFontFaces(
  { apiBaseUrl, fetchImpl, onFaceDiagnostic }: LoadKitFontFacesOptions,
  kit: BrandKitDetailPayload | null | undefined
): Promise<boolean> {
  const refs = collectKitFontFaceRefs(kit);
  if (refs.length === 0) {
    return false;
  }
  const doFetch: typeof fetch | undefined =
    fetchImpl ?? (typeof fetch !== "undefined" ? lumenFetch : undefined);
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
          // No longer silent: report the miss the same way the server does.
          onFaceDiagnostic?.(kitFontFaceDiagnostic(ref, `HTTP ${response.status}`));
          return null;
        }
        const bytes = await response.arrayBuffer();
        return { key: `${ref.family}@${ref.assetId}`, family: ref.family, bytes, weight: ref.weight, style: ref.style };
      } catch (error) {
        onFaceDiagnostic?.(
          kitFontFaceDiagnostic(ref, error instanceof Error ? error.message : "fetch failed")
        );
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
  faces: { key: string; family: string; bytes: ArrayBuffer; weight?: number; style?: string }[]
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
        // A7b (D5): weight/style descriptors so a kit's italic face registers
        // distinctly from its upright instead of colliding at the default.
        // Byte-parsed meta wins over the kit's declared fields (same rule as
        // the canvas leg), so DOM faces carry the weight the server matches.
        const meta = effectiveFaceMeta(face);
        const fontFace = new FontFace(
          face.family,
          face.bytes,
          fontFaceDescriptors({ weight: meta.weight, style: meta.italic ? "italic" : "normal" })
        );
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
