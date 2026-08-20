import { describe, expect, it, vi } from "../../__tests__/vitest-shim";
import type { CanvasKit, Image } from "canvaskit-wasm";
import { CanvasKitImageCache } from "../canvaskit/imageCache";

/**
 * Step 2 (E0.1): the cache's control flow — one fetch+decode per asset, an
 * onLoad re-render trigger, and sticky failure (no retry storm) — verified with
 * a stubbed CanvasKit + fetcher so it runs without the wasm binary.
 */

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

function fakeCk(decode: (bytes: Uint8Array) => Image | null): CanvasKit {
  return { MakeImageFromEncoded: (bytes: Uint8Array) => decode(bytes) } as unknown as CanvasKit;
}

const fakeImage = (): Image => ({ delete: () => {} }) as unknown as Image;

describe("CanvasKitImageCache", () => {
  it("fetches+decodes once, returns the image, and fires onLoad", async () => {
    const image = fakeImage();
    const fetcher = vi.fn(async () => new ArrayBuffer(8));
    const onLoad = vi.fn();
    const cache = new CanvasKitImageCache(fakeCk(() => image), {
      resolveUrl: (id) => `/assets/${id}/bytes`,
      onLoad,
      fetcher
    });

    // First lookup: not decoded yet → null, and a load is kicked off.
    expect(cache.get("a")).toBeNull();
    await flush();

    // Decoded now; lookup is synchronous and stable; onLoad re-render fired once.
    expect(cache.get("a")).toBe(image);
    expect(cache.get("a")).toBe(image);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(onLoad).toHaveBeenCalledTimes(1);
  });

  it("does not retry after a failed fetch (placeholder stays)", async () => {
    const fetcher = vi.fn(async () => {
      throw new Error("network");
    });
    const cache = new CanvasKitImageCache(fakeCk(() => fakeImage()), {
      resolveUrl: (id) => `/assets/${id}/bytes`,
      fetcher
    });

    expect(cache.get("a")).toBeNull();
    await flush();
    expect(cache.get("a")).toBeNull();
    expect(cache.get("a")).toBeNull();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("marks an undecodable response as failed", async () => {
    const fetcher = vi.fn(async () => new ArrayBuffer(4));
    const onLoad = vi.fn();
    const cache = new CanvasKitImageCache(fakeCk(() => null), {
      resolveUrl: (id) => `/assets/${id}/bytes`,
      onLoad,
      fetcher
    });

    expect(cache.get("a")).toBeNull();
    await flush();
    expect(cache.get("a")).toBeNull();
    expect(onLoad).not.toHaveBeenCalled();
  });

  it("treats an unresolvable url as a failure without fetching", async () => {
    const fetcher = vi.fn(async () => new ArrayBuffer(8));
    const cache = new CanvasKitImageCache(fakeCk(() => fakeImage()), {
      resolveUrl: () => null,
      fetcher
    });

    expect(cache.get("a")).toBeNull();
    await flush();
    expect(cache.get("a")).toBeNull();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("re-attempts a failed asset when its resolved url CHANGES (new information)", async () => {
    // A later scene can supply the record's digest, flipping resolution from
    // the registry endpoint to the content-addressed one — that (and only
    // that) unfreezes a memoized failure. Same url → stays failed forever.
    const image = fakeImage();
    let url = "/assets/a/bytes";
    const fetcher = vi.fn(async (requested: string) => {
      if (requested === "/assets/a/bytes") {
        throw new Error("404");
      }
      return new ArrayBuffer(8);
    });
    const onLoad = vi.fn();
    const cache = new CanvasKitImageCache(fakeCk(() => image), {
      resolveUrl: () => url,
      onLoad,
      fetcher
    });

    expect(cache.get("a")).toBeNull();
    await flush();
    // Failed on the registry url; identical resolution never retries.
    expect(cache.get("a")).toBeNull();
    await flush();
    expect(fetcher).toHaveBeenCalledTimes(1);

    // The scene now carries a digest: resolution changes → one re-attempt.
    url = "/asset-store/da2488f9";
    expect(cache.get("a")).toBeNull();
    await flush();
    expect(cache.get("a")).toBe(image);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(onLoad).toHaveBeenCalledTimes(1);
  });

  it("invalidate() forces a re-fetch on the next lookup", async () => {
    const fetcher = vi.fn(async () => new ArrayBuffer(8));
    const cache = new CanvasKitImageCache(fakeCk(() => fakeImage()), {
      resolveUrl: (id) => `/assets/${id}/bytes`,
      fetcher
    });

    cache.get("a");
    await flush();
    expect(fetcher).toHaveBeenCalledTimes(1);

    cache.invalidate("a");
    cache.get("a");
    await flush();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});
