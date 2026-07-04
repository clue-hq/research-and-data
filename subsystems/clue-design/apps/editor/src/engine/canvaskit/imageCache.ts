import type { CanvasKit, Image } from "canvaskit-wasm";

/**
 * Step 2 (E0.1): the async byte→pixel bridge for image nodes.
 *
 * The CanvasKit render loop is synchronous, but asset bytes are fetched over the
 * network and decoded asynchronously. This cache holds that gap: `get(assetId)`
 * is a synchronous lookup the interpreter calls during a draw pass — it returns
 * a decoded `Image` if ready, or `null` (draw the placeholder) while it kicks off
 * a one-time fetch + decode in the background. When the decode lands it calls
 * `onLoad`, which the stage wires to `invalidate()`, re-rendering with real pixels.
 *
 * One fetch per asset id: entries are memoized as loading / ready / failed, so a
 * 404 or decode failure never retries in a tight redraw loop (the placeholder
 * stays). Status-driven re-fetch on regenerate/replace is Step 5.
 */

/** What the descriptor interpreter needs: a synchronous decoded-image lookup. */
export interface CanvasKitImageSource {
  get(assetId: string): Image | null;
}

type Entry = { state: "loading" } | { state: "ready"; image: Image } | { state: "failed" };

export interface CanvasKitImageCacheOptions {
  /** Build the bytes URL for an asset id (`/assets/{id}/bytes`); null = unfetchable. */
  resolveUrl: (assetId: string) => string | null;
  /** Called once a decode succeeds so the stage can re-render. */
  onLoad?: () => void;
  /** Override the network fetch (tests inject bytes without a server). */
  fetcher?: (url: string) => Promise<ArrayBuffer>;
}

async function defaultFetcher(url: string): Promise<ArrayBuffer> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`asset bytes request failed: ${response.status}`);
  }
  return response.arrayBuffer();
}

export class CanvasKitImageCache implements CanvasKitImageSource {
  private readonly ck: CanvasKit;
  private readonly entries = new Map<string, Entry>();
  private readonly resolveUrl: (assetId: string) => string | null;
  private readonly onLoad?: () => void;
  private readonly fetcher: (url: string) => Promise<ArrayBuffer>;
  private disposed = false;

  constructor(ck: CanvasKit, options: CanvasKitImageCacheOptions) {
    this.ck = ck;
    this.resolveUrl = options.resolveUrl;
    this.onLoad = options.onLoad;
    this.fetcher = options.fetcher ?? defaultFetcher;
  }

  get(assetId: string): Image | null {
    const entry = this.entries.get(assetId);
    if (entry) {
      return entry.state === "ready" ? entry.image : null;
    }
    // First request for this id: memoize as loading and fetch once.
    this.entries.set(assetId, { state: "loading" });
    void this.load(assetId);
    return null;
  }

  private async load(assetId: string): Promise<void> {
    const url = this.resolveUrl(assetId);
    if (!url) {
      this.entries.set(assetId, { state: "failed" });
      return;
    }
    try {
      const buffer = await this.fetcher(url);
      if (this.disposed) {
        return;
      }
      const image = this.ck.MakeImageFromEncoded(new Uint8Array(buffer));
      if (!image) {
        this.entries.set(assetId, { state: "failed" });
        return;
      }
      this.entries.set(assetId, { state: "ready", image });
      this.onLoad?.();
    } catch {
      if (!this.disposed) {
        this.entries.set(assetId, { state: "failed" });
      }
    }
  }

  /** Drop a cached entry so the next draw re-fetches (Step 5: regenerate/replace). */
  invalidate(assetId: string): void {
    const entry = this.entries.get(assetId);
    if (entry?.state === "ready") {
      entry.image.delete();
    }
    this.entries.delete(assetId);
  }

  /** Release every decoded image; the cache is unusable afterward. */
  dispose(): void {
    this.disposed = true;
    for (const entry of this.entries.values()) {
      if (entry.state === "ready") {
        entry.image.delete();
      }
    }
    this.entries.clear();
  }
}
