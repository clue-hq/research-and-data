import { fontFaceDescriptors, registerKitFontFaces } from "./canvaskit/loadCanvasKit";
import { effectiveFaceMeta } from "./canvaskit/fontFaces";

/**
 * Curated FONT LIBRARY (canvas + DOM legs): fetch the shared library manifest
 * once, then lazily register only the faces whose family the CURRENT scene
 * references — the library is ~27 families / 104 faces / ~31MB, so eager
 * loading is off the table. Mirrors the K3 kit-font machinery in `kitFonts.ts`
 * (same fetch + two-leg registration + `family@assetId` dedup); the only
 * difference is the source (a scene-filtered manifest, not the attached kit).
 *
 * Fetch failures skip the face (the canvas keeps its current fallback);
 * registration dedupes by asset id, so a re-run never re-downloads or
 * double-registers a face.
 */

interface FontLibraryFace {
  weight?: number;
  style?: string;
  asset_id: string;
  digest?: string;
  byte_length?: number;
}

interface FontLibraryFamily {
  slug: string;
  family: string;
  category?: string;
  tone?: string;
  pairing?: unknown;
  notes?: string;
  license?: string;
  metrics?: unknown;
  glyph_coverage?: unknown;
  faces: FontLibraryFace[];
}

export interface FontLibrary {
  version: number;
  provenance?: unknown;
  families: FontLibraryFamily[];
}

interface LibraryFontFaceRef {
  assetId: string;
  family: string;
  /** A7b (D5): the manifest weight/style. Fallback metadata for BOTH legs —
   * the face's byte-parsed OS/2 meta wins when it parses (server truth): the
   * CanvasKit leg keys its style-qualified alias on it, and the DOM leg's
   * `FontFace` descriptors register (family, style, weight) distinctly
   * instead of colliding at the nondeterministic (family, normal, 400)
   * default. */
  weight?: number;
  style?: string;
}

export interface FontLibraryOptions {
  apiBaseUrl: string;
  fetchImpl?: typeof fetch;
}

const EMPTY_LIBRARY: FontLibrary = { version: 1, families: [] };

// Module-level manifest cache. The resolved promise is cached (never a
// rejected one — all failure paths resolve to EMPTY_LIBRARY), so an API-down
// session caches negatively and never spams the endpoint. One base url per
// page, so the first caller's options win.
let libraryPromise: Promise<FontLibrary> | null = null;

/** Fetch + parse the font-library manifest once. A non-ok response or any
 * fetch/parse error resolves to an empty library and is cached for the
 * session (negative cache — API-down must not re-request per scene edit). */
export function fetchFontLibrary({ apiBaseUrl, fetchImpl }: FontLibraryOptions): Promise<FontLibrary> {
  libraryPromise ??= (async () => {
    const doFetch: typeof fetch | undefined =
      fetchImpl ?? (typeof fetch !== "undefined" ? (input, init) => fetch(input, init) : undefined);
    if (!doFetch) {
      return EMPTY_LIBRARY;
    }
    try {
      const response = await doFetch(new URL("/font-library", apiBaseUrl));
      if (!response.ok) {
        return EMPTY_LIBRARY;
      }
      const json = (await response.json()) as Partial<FontLibrary> | null;
      const families = Array.isArray(json?.families) ? (json.families as FontLibraryFamily[]) : [];
      return { version: typeof json?.version === "number" ? json.version : 1, provenance: json?.provenance, families };
    } catch {
      return EMPTY_LIBRARY;
    }
  })();
  return libraryPromise;
}

/** The library's registrable faces for the current scene: every `faces[]`
 * entry of a family whose `family` string appears in the serialized scene
 * JSON, tagged with the declared family. Containment matches the server-side
 * filter (`includes` — false positives are harmless, they just pre-load a
 * face). Families with an empty/non-string family or no faces are skipped. */
export function collectReferencedLibraryFaceRefs(
  library: FontLibrary,
  sceneJson: string
): LibraryFontFaceRef[] {
  const refs: LibraryFontFaceRef[] = [];
  for (const family of library.families) {
    const familyName = (family as { family?: unknown } | null)?.family;
    const faces = (family as { faces?: unknown } | null)?.faces;
    if (typeof familyName !== "string" || familyName.length === 0 || !Array.isArray(faces) || faces.length === 0) {
      continue;
    }
    if (!sceneJson.includes(familyName)) {
      continue;
    }
    for (const face of faces) {
      const assetId = (face as { asset_id?: unknown } | null)?.asset_id;
      if (typeof assetId === "string" && assetId.length > 0) {
        const weight = (face as { weight?: unknown } | null)?.weight;
        const style = (face as { style?: unknown } | null)?.style;
        refs.push({
          assetId,
          family: familyName,
          weight: typeof weight === "number" ? weight : undefined,
          style: typeof style === "string" ? style : undefined
        });
      }
    }
  }
  return refs;
}

// Faces already fetched + registered this session, keyed `family@assetId`.
// Both register legs dedupe internally, but this set spares us re-FETCHING
// bytes for a face a prior scene already loaded — a re-run that references
// only known families makes zero network calls.
const loadedLibraryFaceKeys = new Set<string>();

/** Fetch + register the library faces referenced by `scene`. Resolves true
 * when at least one new face landed in a live provider (the caller should
 * then invalidate text measurement/render memos — same contract as
 * `loadKitFontFaces`). */
export async function loadLibraryFontFaces(
  scene: unknown,
  { apiBaseUrl, fetchImpl }: FontLibraryOptions
): Promise<boolean> {
  const library = await fetchFontLibrary({ apiBaseUrl, fetchImpl });
  if (library.families.length === 0) {
    return false;
  }
  const sceneJson = JSON.stringify(scene);
  const refs = collectReferencedLibraryFaceRefs(library, sceneJson).filter(
    (ref) => !loadedLibraryFaceKeys.has(`${ref.family}@${ref.assetId}`)
  );
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
        return { key: `${ref.family}@${ref.assetId}`, family: ref.family, bytes, weight: ref.weight, style: ref.style };
      } catch {
        return null;
      }
    })
  );
  const loaded = faces.filter((face): face is NonNullable<typeof face> => face !== null);
  if (loaded.length === 0) {
    return false;
  }
  // Mark only successfully-fetched faces as loaded, so a face that failed its
  // fetch is retried on the next scene that references it.
  for (const face of loaded) {
    loadedLibraryFaceKeys.add(face.key);
  }
  // DOM leg: register the same bytes into document.fonts under the declared
  // family so DOM-rendered surfaces (e.g. the Export Preview SVG, which
  // references the family by NAME) render library type instead of a default
  // serif. Purely local display of already-fetched bytes; failures are
  // swallowed so the canvas leg is unaffected.
  await registerLibraryFontFacesInDom(loaded);
  return registerKitFontFaces(loaded);
}

const registeredDomFaceKeys = new Set<string>();

/** Test-only: forget the module-level caches (manifest, fetched faces, DOM
 * registry) so each case starts from a clean slate. */
export function resetFontLibraryForTests(): void {
  libraryPromise = null;
  loadedLibraryFaceKeys.clear();
  registeredDomFaceKeys.clear();
}

/** Feed already-fetched library face bytes to the browser's DOM font registry
 * (`document.fonts`). Keyed by the same `family@assetId` as the CanvasKit leg,
 * so a re-run never double-adds a face. No-op (and never throws) where
 * FontFace/document.fonts are unavailable (jsdom/tests). */
async function registerLibraryFontFacesInDom(
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
        // A7b (D5): pass the weight/style descriptors so italic and upright
        // faces of one family register as distinct DOM faces instead of
        // colliding nondeterministically at the (family, normal, 400) default.
        // Byte-parsed meta wins over the manifest (same rule as the canvas
        // leg), so the DOM face carries the weight the server will match.
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
        console.warn(`Failed to register library font face "${face.family}" into document.fonts`, error);
      }
    })
  );
}
