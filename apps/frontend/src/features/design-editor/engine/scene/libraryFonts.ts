import type { Diagnostic } from "./contracts";
import {
  INTER_FAMILY,
  fontFaceDescriptors,
  registerKitFontFaces,
} from "./canvaskit/loadCanvasKit";
import { effectiveFaceMeta } from "./canvaskit/fontFaces";
import { defaultDesignFetch } from "../config";

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
  /** Fence async font registration to the load/context that requested it. */
  isCurrent?: () => boolean;
  /** Renderer-diagnostic sink for a referenced face that cannot load. */
  onFaceDiagnostic?: (diagnostic: Diagnostic) => void;
}

function libraryFontFaceDiagnostic(
  ref: LibraryFontFaceRef,
  reason: string
): Diagnostic {
  return {
    severity: "warning",
    phase: "brand",
    code: "EDITOR_LIBRARY_FONT_FACE_UNAVAILABLE",
    message: `Font Library family “${ref.family}” face ${ref.assetId} could not be loaded (${reason}); canvas and server export use the deterministic ${INTER_FAMILY} fallback.`,
    subject: { kind: "asset", id: ref.assetId },
    hint: "Confirm the licensed TTF/OTF asset is present in durable storage.",
  };
}

function libraryDomFontFaceDiagnostic(
  face: { key: string; family: string },
  reason: string
): Diagnostic {
  return {
    severity: "warning",
    phase: "brand",
    code: "EDITOR_LIBRARY_DOM_FONT_FACE_UNAVAILABLE",
    message: `Font Library family “${face.family}” could not register in document.fonts (${reason}); DOM previews use the deterministic ${INTER_FAMILY} fallback.`,
    subject: { kind: "asset", id: face.key.slice(face.key.lastIndexOf("@") + 1) },
    hint: "Confirm the asset is a browser-loadable licensed TTF/OTF face and re-open the editor.",
  };
}

function fontLibraryDiagnostic(reason: string): Diagnostic {
  return {
    severity: "warning",
    phase: "brand",
    code: "EDITOR_FONT_LIBRARY_UNAVAILABLE",
    message: `Font Library manifest could not be loaded (${reason}); referenced library families use the deterministic ${INTER_FAMILY} fallback.`,
    subject: { kind: "document" },
    hint: "Restore the workspace Font Library endpoint; the editor will not download substitute font files implicitly.",
  };
}

const EMPTY_LIBRARY: FontLibrary = { version: 1, families: [] };

// Module-level manifest cache. The resolved promise is cached (never a
// rejected one — all failure paths resolve to EMPTY_LIBRARY), so an API-down
// session caches negatively and never spams the endpoint. One base url per
// page, so the first caller's options win.
let libraryPromise: Promise<FontLibrary> | null = null;
let cachedLibraryDiagnostic: Diagnostic | null = null;

/** Fetch + parse the font-library manifest once. A non-ok response or any
 * fetch/parse error resolves to an empty library and is cached for the
 * session (negative cache — API-down must not re-request per scene edit). */
export async function fetchFontLibrary({
  apiBaseUrl,
  fetchImpl,
  onFaceDiagnostic,
}: FontLibraryOptions): Promise<FontLibrary> {
  libraryPromise ??= (async () => {
    // Workspace auth is the BFF's job — defaults to the receiver-safe wrapper; callers inject designBffConfig()'s transport.
    const doFetch: typeof fetch | undefined =
      fetchImpl ?? (typeof fetch !== "undefined" ? defaultDesignFetch : undefined);
    if (!doFetch) {
      cachedLibraryDiagnostic = fontLibraryDiagnostic("fetch is unavailable");
      return EMPTY_LIBRARY;
    }
    try {
      const response = await doFetch(new URL("/font-library", apiBaseUrl));
      if (!response.ok) {
        cachedLibraryDiagnostic = fontLibraryDiagnostic(`HTTP ${response.status}`);
        return EMPTY_LIBRARY;
      }
      const json = (await response.json()) as Partial<FontLibrary> | null;
      const families = Array.isArray(json?.families) ? (json.families as FontLibraryFamily[]) : [];
      cachedLibraryDiagnostic = null;
      return { version: typeof json?.version === "number" ? json.version : 1, provenance: json?.provenance, families };
    } catch (error) {
      cachedLibraryDiagnostic = fontLibraryDiagnostic(
        error instanceof Error ? error.message : "fetch failed"
      );
      return EMPTY_LIBRARY;
    }
  })();
  const library = await libraryPromise;
  if (cachedLibraryDiagnostic) {
    onFaceDiagnostic?.(cachedLibraryDiagnostic);
  }
  return library;
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

// Registration failures for faces whose FETCH succeeded (a DOM `document.fonts`
// refusal, a CanvasKit provider throw). Such a face sits in
// `loadedLibraryFaceKeys`, so no later run re-attempts it — the degradation is
// permanent for the session, and its diagnostic must be too. The caller's
// effect re-runs on every scene change and REPLACES its diagnostic state, so
// without this cache the banner would vanish on the first edit after the
// failure while the fallback rendering persisted. (Fetch failures need no
// cache: they are retried — and re-reported — on every referencing run.)
const persistentFaceDiagnostics = new Map<string, Diagnostic>();

/** Fetch + register the library faces referenced by `scene`. Resolves true
 * when at least one new face landed in a live provider (the caller should
 * then invalidate text measurement/render memos — same contract as
 * `loadKitFontFaces`). */
export async function loadLibraryFontFaces(
  scene: unknown,
  { apiBaseUrl, fetchImpl, onFaceDiagnostic, isCurrent = () => true }: FontLibraryOptions
): Promise<boolean> {
  if (!isCurrent()) return false;
  const library = await fetchFontLibrary({
    apiBaseUrl,
    fetchImpl,
    onFaceDiagnostic,
  });
  if (!isCurrent()) return false;
  // Session-permanent registration failures are re-reported on EVERY run —
  // including the early returns below — the same way the manifest diagnostic
  // is, so the caller's replace-not-merge diagnostic state cannot silently
  // clear a banner whose degradation is still in force.
  for (const diagnostic of persistentFaceDiagnostics.values()) {
    onFaceDiagnostic?.(diagnostic);
  }
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
  // Workspace auth is the BFF's job — defaults to the receiver-safe wrapper; callers inject designBffConfig()'s transport.
  const doFetch: typeof fetch | undefined =
    fetchImpl ?? (typeof fetch !== "undefined" ? defaultDesignFetch : undefined);
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
          onFaceDiagnostic?.(
            libraryFontFaceDiagnostic(ref, `HTTP ${response.status}`)
          );
          return null;
        }
        const bytes = await response.arrayBuffer();
        return { key: `${ref.family}@${ref.assetId}`, family: ref.family, bytes, weight: ref.weight, style: ref.style };
      } catch (error) {
        onFaceDiagnostic?.(
          libraryFontFaceDiagnostic(
            ref,
            error instanceof Error ? error.message : "fetch failed"
          )
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
  // references the family by NAME) render library type instead of a default
  // serif. Purely local display of already-fetched bytes; failures are
  // swallowed so the canvas leg is unaffected.
  await registerLibraryFontFacesInDom(loaded, onFaceDiagnostic, isCurrent);
  if (!isCurrent()) return false;
  for (const face of loaded) loadedLibraryFaceKeys.add(face.key);
  try {
    return registerKitFontFaces(loaded);
  } catch (error) {
    const reason =
      error instanceof Error ? error.message : "CanvasKit registration failed";
    for (const face of loaded) {
      const diagnostic = libraryFontFaceDiagnostic(
        {
          assetId: face.key.slice(face.key.lastIndexOf("@") + 1),
          family: face.family,
        },
        `CanvasKit registration failed: ${reason}`
      );
      // The face is already marked loaded, so it is never re-attempted this
      // session — persist its diagnostic alongside the degradation.
      persistentFaceDiagnostics.set(face.key, diagnostic);
      onFaceDiagnostic?.(diagnostic);
    }
    return false;
  }
}

const registeredDomFaceKeys = new Set<string>();

/** Test-only: forget the module-level caches (manifest, fetched faces, DOM
 * registry) so each case starts from a clean slate. */
export function resetFontLibraryForTests(): void {
  libraryPromise = null;
  cachedLibraryDiagnostic = null;
  loadedLibraryFaceKeys.clear();
  registeredDomFaceKeys.clear();
  persistentFaceDiagnostics.clear();
}

/** Feed already-fetched library face bytes to the browser's DOM font registry
 * (`document.fonts`). Keyed by the same `family@assetId` as the CanvasKit leg,
 * so a re-run never double-adds a face. No-op (and never throws) where
 * FontFace/document.fonts are unavailable (jsdom/tests). */
async function registerLibraryFontFacesInDom(
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
        if (!isCurrent() || registeredDomFaceKeys.has(face.key)) return;
        document.fonts.add(fontFace);
        registeredDomFaceKeys.add(face.key);
      } catch (error) {
        // A DOM font registration failure must not affect the canvas leg. The
        // face never re-enters this function (its fetch succeeded, so it is in
        // `loadedLibraryFaceKeys`), making the failure session-permanent —
        // persist the diagnostic under its own leg-scoped key.
        if (!isCurrent()) return;
        const diagnostic = libraryDomFontFaceDiagnostic(
          face,
          error instanceof Error ? error.message : "registration failed"
        );
        persistentFaceDiagnostics.set(`dom:${face.key}`, diagnostic);
        onFaceDiagnostic?.(diagnostic);
      }
    })
  );
}
