import type { BrandKitDetailPayload } from "./tokenColors";
import type { Diagnostic } from "./contracts";
import {
  INTER_FAMILY,
  fontFaceDescriptors,
  registerKitFontFaces,
} from "./canvaskit/loadCanvasKit";
import { effectiveFaceMeta } from "./canvaskit/fontFaces";
import { defaultDesignFetch } from "../config";

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

export interface KitFontFamilyRef {
  family: string;
  assetIds: string[];
}

/** Every family the kit declares, including typography-token families that
 * have no `assets.fonts` group at all. Keeping the empty declarations is
 * deliberate: they are the data defect that used to look like a successful
 * font load while both renderers silently substituted a face. */
export function collectKitFontFamilyRefs(
  kit: BrandKitDetailPayload | null | undefined
): KitFontFamilyRef[] {
  const families = new Map<string, Set<string>>();
  const addFamily = (value: unknown) => {
    if (typeof value !== "string" || value.trim().length === 0) {
      return null;
    }
    const family = value.trim();
    const assets = families.get(family) ?? new Set<string>();
    families.set(family, assets);
    return assets;
  };

  const fonts = (kit as { assets?: { fonts?: unknown } } | null | undefined)
    ?.assets?.fonts;
  if (fonts && typeof fonts === "object") {
    for (const group of Object.values(fonts as Record<string, unknown>)) {
      if (!group || typeof group !== "object") {
        continue;
      }
      const assets = addFamily((group as { family?: unknown }).family);
      if (!assets) {
        continue;
      }
      const faces = (group as { faces?: unknown }).faces;
      if (!Array.isArray(faces)) {
        continue;
      }
      for (const face of faces) {
        const assetId = (face as { asset_id?: unknown } | null)?.asset_id;
        if (typeof assetId === "string" && assetId.length > 0) {
          assets.add(assetId);
        }
      }
    }
  }

  const typography = (
    kit as {
      tokens?: {
        typography?: Record<
          string,
          { value?: { default?: { font_family?: unknown } } }
        >;
      };
    } | null | undefined
  )?.tokens?.typography;
  for (const token of Object.values(typography ?? {})) {
    addFamily(token?.value?.default?.font_family);
  }

  return [...families.entries()].map(([family, assetIds]) => ({
    family,
    assetIds: [...assetIds],
  }));
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
  /** Fence async font registration to the load/context that requested it. */
  isCurrent?: () => boolean;
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
    message: `Brand Kit font “${ref.family}” face ${ref.assetId} could not be loaded (${reason}); canvas and server export use the deterministic ${INTER_FAMILY} fallback for it.`,
    subject: { kind: "asset", id: ref.assetId },
    hint: "Re-attach the Brand Kit or confirm the licensed TTF/OTF asset is present in durable storage."
  };
}

function kitFontFamilyDiagnostic(family: string): Diagnostic {
  return {
    severity: "warning",
    phase: "brand",
    code: "EDITOR_KIT_FONT_FAMILY_UNAVAILABLE",
    message: `Brand Kit declares “${family}” but supplies no TTF/OTF face assets; canvas and server export use the deterministic ${INTER_FAMILY} fallback.`,
    subject: { kind: "document" },
    hint: `Ingest licensed TTF/OTF files for “${family}” to render that family; the editor will not download or fabricate font files implicitly.`,
  };
}

function kitDomFontFaceDiagnostic(
  face: { key: string; family: string },
  reason: string
): Diagnostic {
  return {
    severity: "warning",
    phase: "brand",
    code: "EDITOR_KIT_DOM_FONT_FACE_UNAVAILABLE",
    message: `Brand Kit font “${face.family}” could not register in document.fonts (${reason}); DOM previews use the deterministic ${INTER_FAMILY} fallback.`,
    subject: { kind: "asset", id: face.key.slice(face.key.lastIndexOf("@") + 1) },
    hint: "Confirm the asset is a browser-loadable licensed TTF/OTF face and re-open the editor.",
  };
}

/** Fetch + register the kit's faces. Resolves true when at least one new
 * face landed in a live provider (the caller should then invalidate text
 * measurement/render memos). */
export async function loadKitFontFaces(
  { apiBaseUrl, fetchImpl, onFaceDiagnostic, isCurrent = () => true }: LoadKitFontFacesOptions,
  kit: BrandKitDetailPayload | null | undefined
): Promise<boolean> {
  if (!isCurrent()) return false;
  const refs = collectKitFontFaceRefs(kit);
  for (const family of collectKitFontFamilyRefs(kit)) {
    if (family.assetIds.length === 0) {
      onFaceDiagnostic?.(kitFontFamilyDiagnostic(family.family));
    }
  }
  if (refs.length === 0) {
    return false;
  }
  // Workspace auth is the BFF's job — defaults to the receiver-safe wrapper; callers inject designBffConfig()'s transport.
  const doFetch: typeof fetch | undefined =
    fetchImpl ?? (typeof fetch !== "undefined" ? defaultDesignFetch : undefined);
  if (!doFetch) {
    for (const ref of refs) {
      onFaceDiagnostic?.(kitFontFaceDiagnostic(ref, "fetch is unavailable"));
    }
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
  if (!isCurrent()) return false;
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
  await registerKitFontFacesInDom(loaded, onFaceDiagnostic, isCurrent);
  if (!isCurrent()) return false;
  try {
    return registerKitFontFaces(loaded);
  } catch (error) {
    const reason =
      error instanceof Error ? error.message : "CanvasKit registration failed";
    for (const face of loaded) {
      onFaceDiagnostic?.(
        kitFontFaceDiagnostic(
          {
            assetId: face.key.slice(face.key.lastIndexOf("@") + 1),
            family: face.family,
          },
          `CanvasKit registration failed: ${reason}`
        )
      );
    }
    return false;
  }
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
  faces: { key: string; family: string; bytes: ArrayBuffer; weight?: number; style?: string }[],
  onFaceDiagnostic?: (diagnostic: Diagnostic) => void,
  isCurrent: () => boolean = () => true,
): Promise<void> {
  if (typeof FontFace === "undefined" || typeof document === "undefined" || !document.fonts) {
    return;
  }
  await Promise.all(
    faces.map(async (face) => {
      if (registeredDomFaceKeys.has(face.key)) {
        return;
      }
      if (!isCurrent()) return;
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
        if (!isCurrent() || registeredDomFaceKeys.has(face.key)) return;
        document.fonts.add(fontFace);
        registeredDomFaceKeys.add(face.key);
      } catch (error) {
        // A DOM font registration failure must not affect the canvas leg.
        if (!isCurrent()) return;
        onFaceDiagnostic?.(
          kitDomFontFaceDiagnostic(
            face,
            error instanceof Error ? error.message : "registration failed"
          )
        );
      }
    })
  );
}
