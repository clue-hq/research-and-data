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
    // CanvasKit unavailable → the editor stays on Konva.
    return null;
  }

  const fontProvider = await registerFont(ck, fontUrl, fetchImpl);
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
