import type { CanvasKit, TypefaceFontProvider } from "canvaskit-wasm";

/** The family scenes/the design system request; the variable Inter TTF is
 * registered under this alias (its intrinsic name is "Inter Variable", which
 * would otherwise not match a "Inter" request). */
export const INTER_FAMILY = "Inter";

/**
 * Wave 3 C0: load the CanvasKit (Skia/WASM) module exactly once.
 *
 * The ~2.9 MB gzip wasm and the Inter TTF are lazy — this runs only when the
 * CanvasKit editor canvas first mounts, never on the first-paint path. A
 * failed/missing load resolves to `null`, and the editor stays on the Konva
 * renderer (mirroring the WASM-core degrade-to-server pattern): CanvasKit is
 * additive, never a hard dependency.
 *
 * Pinned to canvaskit-wasm 0.41.1 — the version the spike proved at 0.003%
 * render parity against the canonical Skia export. Fonts must be TTF/OTF
 * (CanvasKit's FontMgr cannot read woff2); the variable InterVariable.ttf
 * covers all weights in one ~460 KB gzip fetch.
 */

export interface CanvasKitBundle {
  ck: CanvasKit;
  /** A font provider with the Inter TTF registered under the `INTER_FAMILY`
   * alias, or `null` when the font could not be fetched — text falls back to
   * the CanvasKit default face rather than failing the whole canvas. The
   * paragraph builders require a TypefaceFontProvider (a plain FontMgr is
   * rejected by `MakeFromFontProvider`). */
  fontProvider: TypefaceFontProvider | null;
}

export interface LoadCanvasKitOptions {
  /** Where `canvaskit.wasm` is served from (default `/canvaskit`). */
  baseUrl?: string;
  /** The variable Inter TTF URL (default `/fonts/InterVariable.ttf`). */
  fontUrl?: string;
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
}

const registeredKitFaceKeys = new Set<string>();
let pendingKitFaces: KitFontFace[] = [];
let liveFontProvider: TypefaceFontProvider | null = null;

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
  for (const face of fresh) {
    registeredKitFaceKeys.add(face.key);
  }
  if (fresh.length === 0) {
    return false;
  }
  if (liveFontProvider) {
    for (const face of fresh) {
      liveFontProvider.registerFont(face.bytes, face.family);
    }
    return true;
  }
  pendingKitFaces.push(...fresh);
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
  setTextMeasurementStatus("pending");
}

async function initBundle(options: LoadCanvasKitOptions): Promise<CanvasKitBundle | null> {
  const baseUrl = options.baseUrl ?? "/canvaskit";
  const fontUrl = options.fontUrl ?? "/fonts/InterVariable.ttf";
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

  const fontProvider = await registerFont(ck, fontUrl, fetchImpl);
  if (fontProvider) {
    liveFontProvider = fontProvider;
    for (const face of pendingKitFaces) {
      fontProvider.registerFont(face.bytes, face.family);
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

async function registerFont(
  ck: CanvasKit,
  fontUrl: string,
  fetchImpl: typeof fetch | undefined
): Promise<TypefaceFontProvider | null> {
  if (!fetchImpl) {
    return null;
  }
  try {
    const response = await fetchImpl(fontUrl);
    if (!response.ok) {
      return null;
    }
    const bytes = await response.arrayBuffer();
    const provider = ck.TypefaceFontProvider.Make();
    // Register under the requested alias AND the font's intrinsic name so both
    // a "Inter" request (the design system) and "Inter Variable" resolve.
    provider.registerFont(bytes, INTER_FAMILY);
    provider.registerFont(bytes, "Inter Variable");
    return provider;
  } catch {
    return null;
  }
}
