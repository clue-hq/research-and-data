import type { CanvasKit, TypefaceFontProvider } from "canvaskit-wasm";
import { effectiveFaceMeta, faceAlias, parseFaceMeta, selectFace, type RegisteredFace } from "./fontFaces";

/** The default family scenes/the design system request and every
 * unresolvable family falls back to — mirrors the server's
 * `DEFAULT_FONT_FAMILY`. */
export const INTER_FAMILY = "Inter";

/** The exact static Inter faces the server embeds from the repo `fonts/`
 * directory (weights 400/600/700/800) — the cross-runtime parity contract.
 * The canvas registers the SAME bytes so weight snapping matches exports
 * byte-for-byte. (A variable TTF is useless here: CanvasKit never applies
 * the weight axis, so it only ever renders the default 400 instance.) */
const DEFAULT_INTER_FONT_URLS = [
  "/vendor/fonts/Inter-Regular.ttf",
  "/vendor/fonts/Inter-SemiBold.ttf",
  "/vendor/fonts/Inter-Bold.ttf",
  "/vendor/fonts/Inter-ExtraBold.ttf"
];

/**
 * Wave 3 C0: load the CanvasKit (Skia/WASM) module exactly once.
 *
 * The ~2.9 MB gzip wasm and the Inter TTFs are lazy — this runs only when the
 * CanvasKit editor canvas first mounts, never on the first-paint path. A
 * failed/missing load resolves to `null`, and the editor stays on the Konva
 * renderer (mirroring the WASM-core degrade-to-server pattern): CanvasKit is
 * additive, never a hard dependency.
 *
 * Pinned to canvaskit-wasm 0.41.1 — the version the spike proved at 0.003%
 * render parity against the canonical Skia export. Fonts must be TTF/OTF
 * (CanvasKit's FontMgr cannot read woff2).
 */

export interface CanvasKitBundle {
  ck: CanvasKit;
  /** A font provider with the Inter statics registered under `INTER_FAMILY`
   * (+ their weight aliases), or `null` when no face could be fetched — text
   * falls back to the CanvasKit default face rather than failing the whole
   * canvas. The paragraph builders require a TypefaceFontProvider (a plain
   * FontMgr is rejected by `MakeFromFontProvider`). */
  fontProvider: TypefaceFontProvider | null;
}

export interface LoadCanvasKitOptions {
  /** Where `canvaskit.wasm` is served from (default `/vendor/canvaskit`). */
  baseUrl?: string;
  /** The Inter static TTF URLs (default: the four server-parity faces). */
  fontUrls?: string[];
  /** Test seam: replaces the wasm-pack-style module init. */
  init?: (options: { locateFile: (file: string) => string }) => Promise<CanvasKit>;
  /** Test seam for the font fetch. */
  fetchImpl?: typeof fetch;
}

let bundlePromise: Promise<CanvasKitBundle | null> | null = null;

/**
 * Live status of the on-canvas text-measurement path. The wasm engine uses a
 * crude heuristic measurer until a CanvasKit measurement pass feeds it real
 * SkParagraph metrics (see `skiaMeasurements`); that pass only runs when this
 * bundle resolves WITH a `fontProvider`. So this is the single observable
 * signal for "is canvas text geometry exact or approximate?":
 *   - `pending`   — no CanvasKit load has resolved yet (initial / not mounted).
 *   - `skia`      — CanvasKit + a font provider are live; measurement is exact.
 *   - `heuristic` — CanvasKit failed to load, OR the font (Inter/kit faces)
 *                   could not be fetched, so no provider exists and the engine
 *                   stays on the heuristic measurer. Text geometry is degraded.
 * The editor subscribes to this to raise a loud, always-on banner rather than
 * silently laying out (and sometimes dropping) text.
 */
export type TextMeasurementStatus = "pending" | "skia" | "heuristic";

let textMeasurementStatus: TextMeasurementStatus = "pending";
const measurementStatusListeners = new Set<() => void>();

function setTextMeasurementStatus(next: TextMeasurementStatus): void {
  if (next === textMeasurementStatus) {
    return;
  }
  textMeasurementStatus = next;
  for (const listener of measurementStatusListeners) {
    listener();
  }
}

/** Subscribe to text-measurement-status changes (useSyncExternalStore). */
export function subscribeTextMeasurementStatus(listener: () => void): () => void {
  measurementStatusListeners.add(listener);
  return () => {
    measurementStatusListeners.delete(listener);
  };
}

/** Current text-measurement status (useSyncExternalStore snapshot). */
export function textMeasurementStatusSnapshot(): TextMeasurementStatus {
  return textMeasurementStatus;
}

/** One brand-kit font face for the canvas: raw TTF/OTF bytes registered
 * under the kit's declared family (paragraphs request that family after
 * K1.5 type resolution). `key` dedupes registration across kit refetches. */
export interface KitFontFace {
  key: string;
  family: string;
  bytes: ArrayBuffer;
  /** Declared manifest/kit weight. Fallback only: the face's OS/2 weight
   * parsed from `bytes` wins when it parses (server truth). */
  weight?: number;
  /** Declared "italic" | "normal". Fallback only, same as `weight`. */
  style?: string;
}

/**
 * A7b (D5): the DOM `FontFace` descriptors for a face, from its effective
 * (byte-parsed, declared-fallback) weight/style. Passing these makes italic
 * and upright faces of one family register as DISTINCT `document.fonts`
 * entries — without them both land at the default (family, normal, 400) and
 * the browser picks one nondeterministically. Both DOM registration legs
 * (library + kit) share this so the collision fix stays in one place; they
 * always pass an explicit weight (`effectiveFaceMeta` defaults to 400), the
 * omission branch is defense for direct callers.
 */
export function fontFaceDescriptors(face: { weight?: number; style?: string }): FontFaceDescriptors {
  const descriptors: FontFaceDescriptors = {
    style: face.style === "italic" ? "italic" : "normal"
  };
  if (typeof face.weight === "number") {
    descriptors.weight = String(face.weight);
  }
  return descriptors;
}

const registeredKitFaceKeys = new Set<string>();
let pendingKitFaces: PendingFace[] = [];
let liveFontProvider: TypefaceFontProvider | null = null;

/**
 * The face registry: every registered face's style identity per family.
 * CanvasKit's provider does NO style matching (first face registered under a
 * name wins, whatever `fontStyle` asks), so the editor selects faces itself:
 * each face registers under a style-qualified alias in addition to its plain
 * family, and `resolveFontFamilies` maps a (family, weight, italic) request
 * to the alias of the face Skia's CSS3 matching would pick — the same snap
 * the server performs. Face styles are byte-parsed (OS/2), with declared
 * manifest/kit metadata as fallback, matching the byte-parsing server.
 */
const familyFaces = new Map<string, RegisteredFace[]>();

/** A face recorded in the registry plus which provider names it must claim.
 * `registerFont` copies the bytes into the wasm heap per name and is
 * first-wins per name, so a face only registers names that are NEW: the
 * plain family for a family's first face (later same-family registrations
 * would be unreachable dead weight), and the alias when no earlier face
 * already holds it (duplicate style in one family — also unreachable). */
interface PendingFace {
  bytes: ArrayBuffer;
  family: string;
  alias: string;
  aliasIsNew: boolean;
  familyIsNew: boolean;
}

function recordFace(
  face: { bytes: ArrayBuffer; family: string },
  meta: { weight: number; italic: boolean }
): PendingFace {
  const alias = faceAlias(face.family, meta.weight, meta.italic);
  const existing = familyFaces.get(face.family);
  const familyIsNew = existing === undefined;
  const faces = existing ?? [];
  const aliasIsNew = !faces.some((registered) => registered.alias === alias);
  if (aliasIsNew) {
    faces.push({ alias, weight: meta.weight, italic: meta.italic });
    familyFaces.set(face.family, faces);
  }
  return { bytes: face.bytes, family: face.family, alias, aliasIsNew, familyIsNew };
}

function applyFaceToProvider(provider: TypefaceFontProvider, face: PendingFace): void {
  if (face.aliasIsNew) {
    provider.registerFont(face.bytes, face.alias);
  }
  if (face.familyIsNew) {
    provider.registerFont(face.bytes, face.family);
  }
}

/** A7b D2: whether requesting `Slant::Italic` for this family selects a real
 * face — byte-parsed at registration, like the server. CanvasKit's paragraph
 * layer applies a SYNTHETIC oblique when asked for an unsatisfiable italic
 * slant (same skparagraph behavior the server gates against), so the
 * paragraph builders request Italic only when this says a real face exists.
 * Unknown families mirror the server's fallback resolution (Inter). */
export function hasItalicFace(family: string): boolean {
  const resolved = familyFaces.has(family) ? family : INTER_FAMILY;
  return (familyFaces.get(resolved) ?? []).some((face) => face.italic);
}

const REGULAR_REQUEST = 400;
const BOLD_REQUEST = 700;

/**
 * Plan 1 item B (2026-09-04): whether asking this family for Bold (700) selects a
 * DIFFERENT registered face than Regular (400) does. Neither renderer synthesises
 * bold, so when the answer is no, the Bold toggle would write a weight nobody can
 * paint — the toolbar disables it and says why. Same Inter fallback as
 * `hasItalicFace`: an unregistered family renders in Inter, so Inter's faces answer.
 */
export function boldChangesFace(family: string): boolean {
  const resolved = familyFaces.has(family) ? family : INTER_FAMILY;
  const faces = familyFaces.get(resolved) ?? [];
  if (faces.length === 0) {
    return false;
  }
  const regular = selectFace(faces, REGULAR_REQUEST, false);
  const bold = selectFace(faces, BOLD_REQUEST, false);
  return regular !== null && bold !== null && regular.alias !== bold.alias;
}

/**
 * The `fontFamilies` chain a paragraph/text style should request for a
 * (family, weight, italic) triple — the canvas twin of the server's
 * `resolve_family` + CSS3 face matching:
 *
 *   1. the style-qualified alias of the face the request selects (weight
 *      snap + italic↔upright snap identical to the server's), when the
 *      family is registered;
 *   2. the plain family (safety net; also preserves behavior for providers
 *      populated outside this registry, e.g. tests);
 *   3. Inter at the same requested style, then plain Inter — the server's
 *      whole-family fallback for unknown families AND its deterministic
 *      per-glyph fallback for missing glyphs.
 */
export function resolveFontFamilies(family: string, weight: number, italic: boolean): string[] {
  const chain: string[] = [];
  const push = (name: string) => {
    if (!chain.includes(name)) {
      chain.push(name);
    }
  };
  const faces = familyFaces.get(family);
  if (faces && faces.length > 0) {
    const face = selectFace(faces, weight, italic);
    if (face) {
      push(face.alias);
    }
  }
  push(family);
  const inter = familyFaces.get(INTER_FAMILY);
  if (family !== INTER_FAMILY && inter && inter.length > 0) {
    const face = selectFace(inter, weight, italic);
    if (face) {
      push(face.alias);
    }
    push(INTER_FAMILY);
  }
  return chain;
}

/**
 * K3: register brand-kit font faces into the shared font provider so canvas
 * text shapes and measures in the kit's real faces instead of the CanvasKit
 * default. Faces registered before the bundle initializes are queued and
 * applied when the provider is created; duplicates (same `key`) are ignored.
 * Returns true when at least one NEW face was applied to a live provider —
 * the caller's signal to invalidate measurement/render memos.
 */
export function registerKitFontFaces(faces: KitFontFace[]): boolean {
  const fresh = faces.filter((face) => !registeredKitFaceKeys.has(face.key));
  if (fresh.length === 0) {
    return false;
  }
  const prepared = fresh
    .map((face) => {
      registeredKitFaceKeys.add(face.key);
      return recordFace(face, effectiveFaceMeta(face));
    })
    // A face claiming no new name (same family + style already registered)
    // is unreachable in the provider — skip it, and don't churn memos for it.
    .filter((face) => face.aliasIsNew || face.familyIsNew);
  if (prepared.length === 0) {
    return false;
  }
  if (liveFontProvider) {
    for (const face of prepared) {
      applyFaceToProvider(liveFontProvider, face);
    }
    return true;
  }
  pendingKitFaces.push(...prepared);
  return false;
}

/**
 * Resolve the shared CanvasKit bundle (init + font), caching the promise so
 * the wasm instantiates exactly once per page. Concurrent callers share it.
 * Returns `null` if CanvasKit itself cannot load.
 */
export function loadCanvasKit(options: LoadCanvasKitOptions = {}): Promise<CanvasKitBundle | null> {
  bundlePromise ??= initBundle(options);
  return bundlePromise;
}

/** Test-only: drop the cached singleton so a fresh load can be exercised. */
export function resetCanvasKitForTests(): void {
  bundlePromise = null;
  registeredKitFaceKeys.clear();
  pendingKitFaces = [];
  liveFontProvider = null;
  familyFaces.clear();
  setTextMeasurementStatus("pending");
}

async function initBundle(options: LoadCanvasKitOptions): Promise<CanvasKitBundle | null> {
  const baseUrl = options.baseUrl ?? "/vendor/canvaskit";
  const fontUrls = options.fontUrls ?? DEFAULT_INTER_FONT_URLS;
  const fetchImpl = options.fetchImpl ?? (typeof fetch !== "undefined" ? fetch : undefined);

  let ck: CanvasKit;
  try {
    const init = options.init ?? (await defaultInit());
    ck = await init({ locateFile: (file: string) => `${baseUrl}/${file}` });
  } catch {
    // CanvasKit unavailable → the editor stays on Konva, and the measurement
    // pass can never run, so on-canvas text geometry is heuristic. Make it loud.
    setTextMeasurementStatus("heuristic");
    return null;
  }

  const fontProvider = await registerInterFaces(ck, fontUrls, fetchImpl);
  if (fontProvider) {
    liveFontProvider = fontProvider;
    for (const face of pendingKitFaces) {
      applyFaceToProvider(fontProvider, face);
    }
    pendingKitFaces = [];
  }
  // Without a font provider the measure-then-inject pass (skiaMeasurements)
  // short-circuits and the engine keeps its heuristic measurer — a silent
  // degradation until now. Record the real state for the editor to surface.
  setTextMeasurementStatus(fontProvider ? "skia" : "heuristic");
  return { ck, fontProvider };
}

/** The real wasm-pack-style init, loaded only in the browser bundle. */
async function defaultInit(): Promise<
  (options: { locateFile: (file: string) => string }) => Promise<CanvasKit>
> {
  const mod = (await import("canvaskit-wasm")) as unknown as {
    default: (options: { locateFile: (file: string) => string }) => Promise<CanvasKit>;
  };
  return mod.default;
}

/** Fetch + register the static Inter faces (the server-parity set). Each face
 * registers under its byte-parsed weight alias and the plain `INTER_FAMILY`.
 * Any face that loads yields a provider; a face that fails its fetch degrades
 * that weight to the CSS3 snap over the loaded set (never fatal). Only a
 * total miss returns `null` (canvas text keeps the CanvasKit default face). */
async function registerInterFaces(
  ck: CanvasKit,
  fontUrls: string[],
  fetchImpl: typeof fetch | undefined
): Promise<TypefaceFontProvider | null> {
  if (!fetchImpl) {
    return null;
  }
  const loaded = await Promise.all(
    fontUrls.map(async (url) => {
      try {
        const response = await fetchImpl(url);
        if (!response.ok) {
          return null;
        }
        return await response.arrayBuffer();
      } catch {
        return null;
      }
    })
  );
  const faces = loaded.filter((bytes): bytes is ArrayBuffer => bytes !== null);
  if (faces.length === 0) {
    return null;
  }
  const provider = ck.TypefaceFontProvider.Make();
  for (const bytes of faces) {
    // Bundled Inter statics carry correct OS/2 meta; the default is pure
    // defense against a corrupted fetch that still parsed as a typeface.
    const meta = parseFaceMeta(bytes) ?? { weight: 400, italic: false };
    applyFaceToProvider(provider, recordFace({ bytes, family: INTER_FAMILY }, meta));
  }
  return provider;
}
