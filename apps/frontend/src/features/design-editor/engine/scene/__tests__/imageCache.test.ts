import { describe, expect, it, vi } from "../../__tests__/vitest-shim";
import type { CanvasKit, Image } from "canvaskit-wasm";
import { CanvasKitImageCache, sniffSvgText, type SvgRasterizer } from "../canvaskit/imageCache";

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
  it("replaces a fresh-generation placeholder after one byte fetch and decode", async () => {
    const image = fakeImage();
    const fetcher = vi.fn(async () => new ArrayBuffer(8));
    const onLoad = vi.fn();
    const decode = vi.fn(() => image);
    const cache = new CanvasKitImageCache(fakeCk(decode), {
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
    expect(decode).toHaveBeenCalledTimes(1);
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

  it("retries failed bytes after publication without discarding decoded images", async () => {
    let published = false;
    const image = fakeImage();
    const fetcher = vi.fn(async (url: string) => {
      if (url.endsWith("pending") && !published) throw new Error("404");
      return new ArrayBuffer(8);
    });
    const cache = new CanvasKitImageCache(fakeCk(() => image), {
      resolveUrl: (id) => `/asset-store/${id}`, fetcher,
    });
    cache.get("ready");
    cache.get("pending");
    await flush();
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(cache.get("ready")).toBe(image);
    expect(cache.get("pending")).toBeNull();

    published = true;
    cache.retryFailed();
    expect(cache.get("ready")).toBe(image);
    expect(cache.get("pending")).toBeNull();
    await flush();
    expect(cache.get("pending")).toBe(image);
    expect(fetcher).toHaveBeenCalledTimes(3);

    cache.retryFailed();
    expect(cache.get("ready")).toBe(image);
    expect(cache.get("pending")).toBe(image);
    await flush();
    expect(fetcher).toHaveBeenCalledTimes(3);
  });
});

// ---------------------------------------------------------------------------
// SVG branch: browser rasterization + the crispness ladder.
// The rasterizer seam is injected (this runtime cannot rasterize SVG); the
// REAL rendering proof is the browser tier — see the D3-class lesson: these
// tests cover the cache's control flow, not pixels.
// ---------------------------------------------------------------------------

const SVG_TEXT = `<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"></svg>`;

const textBuffer = (text: string): ArrayBuffer => {
  const bytes = new TextEncoder().encode(text);
  return bytes.buffer.slice(0, bytes.byteLength) as ArrayBuffer;
};

function svgCk(fromSource: () => Image | null, decode: () => Image | null = () => null): CanvasKit {
  return {
    MakeImageFromEncoded: decode,
    MakeImageFromCanvasImageSource: fromSource
  } as unknown as CanvasKit;
}

/** A rasterizer double applying the real cap arithmetic for a fixed intrinsic;
 * records every (scale, maxSide) it was asked for. */
function stubRasterizer(intrinsic: { width: number; height: number }) {
  const calls: Array<{ scale: number; maxSide: number }> = [];
  const rasterize: SvgRasterizer = async (_text, scale, maxSide) => {
    calls.push({ scale, maxSide });
    const longest = Math.max(intrinsic.width, intrinsic.height);
    let applied = scale;
    while (applied > 1 && longest * applied > maxSide) {
      applied /= 2;
    }
    return {
      source: {} as CanvasImageSource,
      intrinsicWidth: intrinsic.width,
      intrinsicHeight: intrinsic.height,
      scale: applied
    };
  };
  return { rasterize, calls };
}

describe("CanvasKitImageCache — SVG assets", () => {
  it("sniffs SVG documents, and only SVG documents", () => {
    expect(sniffSvgText(textBuffer(SVG_TEXT))).toBe(SVG_TEXT);
    expect(sniffSvgText(textBuffer('<?xml version="1.0"?>\n<svg xmlns="x"/>'))).not.toBeNull();
    expect(sniffSvgText(textBuffer('\uFEFF  <svg viewBox="0 0 2 2"/>'))).not.toBeNull();
    // PNG magic bytes are not a markup document.
    expect(sniffSvgText(new Uint8Array([0x89, 0x50, 0x4e, 0x47]).buffer as ArrayBuffer)).toBeNull();
    // Text MENTIONING <svg without being markup is not an SVG.
    expect(sniffSvgText(textBuffer("hello <svg> world"))).toBeNull();
  });

  it("routes SVG bytes to the rasterizer seam, never MakeImageFromEncoded", async () => {
    const image = fakeImage();
    let decoded = 0;
    const { rasterize, calls } = stubRasterizer({ width: 100, height: 50 });
    let loads = 0;
    const onLoad = () => {
      loads += 1;
    };
    const cache = new CanvasKitImageCache(
      svgCk(
        () => image,
        () => {
          decoded += 1;
          return null;
        }
      ),
      {
        resolveUrl: () => "/asset-store/aa",
        onLoad,
        fetcher: async () => textBuffer(SVG_TEXT),
        rasterizeSvg: rasterize
      }
    );

    expect(cache.get("a")).toBeNull();
    await flush();
    expect(cache.get("a")).toBe(image);
    expect(decoded).toBe(0);
    expect(calls.length).toBe(1);
    expect(calls[0]).toEqual({ scale: 1, maxSide: 4096 });
    expect(loads).toBe(1);
  });

  it("re-rasterizes sharper when zoom×dpr outgrows the raster, swapping the image", async () => {
    let firstDeleted = 0;
    const first = { delete: () => (firstDeleted += 1) } as unknown as Image;
    const second = fakeImage();
    const images = [first, second];
    const { rasterize, calls } = stubRasterizer({ width: 100, height: 50 });
    let loads = 0;
    const onLoad = () => {
      loads += 1;
    };
    const cache = new CanvasKitImageCache(svgCk(() => images.shift() ?? null), {
      resolveUrl: () => "/asset-store/aa",
      onLoad,
      fetcher: async () => textBuffer(SVG_TEXT),
      rasterizeSvg: rasterize
    });

    cache.get("a");
    await flush();
    expect(cache.get("a")).toBe(first);

    // The stage reports a deeper view: the draw keeps serving the softer
    // raster while the sharper one is produced, then swaps to it.
    cache.setViewScale(3.5);
    expect(cache.get("a")).toBe(first);
    await flush();
    expect(cache.get("a")).toBe(second);
    expect(calls.map((c) => c.scale)).toEqual([1, 4]);
    expect(firstDeleted).toBe(1);
    expect(loads).toBe(2);

    // Zooming back out never re-rasterizes (GPU minification is fine).
    cache.setViewScale(1);
    cache.get("a");
    await flush();
    expect(calls.length).toBe(2);
  });

  it("stops asking for sharper rasters at the memory cap", async () => {
    // Intrinsic 512 → the 4096-px side cap lands at scale 8; the first decode
    // is asked for the full demand and capped by the rasterizer itself.
    const { rasterize, calls } = stubRasterizer({ width: 512, height: 512 });
    const cache = new CanvasKitImageCache(svgCk(() => fakeImage()), {
      resolveUrl: () => "/asset-store/aa",
      fetcher: async () => textBuffer(SVG_TEXT),
      rasterizeSvg: rasterize
    });

    cache.setViewScale(32);
    cache.get("a");
    await flush();
    expect(calls.length).toBe(1);

    // Serving the cap already: repeated deep-zoom draws stay quiet.
    cache.get("a");
    cache.get("a");
    await flush();
    expect(calls.length).toBe(1);
  });

  it("keeps serving the current raster when a sharpen fails; retries only on a NEW scale", async () => {
    const first = fakeImage();
    const scales: number[] = [];
    const rasterize: SvgRasterizer = async (_text, scale) => {
      scales.push(scale);
      if (scale === 4) {
        throw new Error("decode failed");
      }
      return {
        source: {} as CanvasImageSource,
        intrinsicWidth: 100,
        intrinsicHeight: 50,
        scale
      };
    };
    let made = 0;
    const cache = new CanvasKitImageCache(
      svgCk(() => {
        made += 1;
        return made === 1 ? first : fakeImage();
      }),
      {
        resolveUrl: () => "/asset-store/aa",
        fetcher: async () => textBuffer(SVG_TEXT),
        rasterizeSvg: rasterize
      }
    );

    cache.get("a");
    await flush();
    cache.setViewScale(4);
    cache.get("a");
    await flush();
    // The sharpen failed: the working image keeps serving, and the SAME
    // demand never retries (a redraw loop must not become a retry storm)...
    expect(cache.get("a")).toBe(first);
    await flush();
    expect(scales).toEqual([1, 4]);

    // ...but a deeper zoom is new information and earns one retry.
    cache.setViewScale(8);
    cache.get("a");
    await flush();
    expect(scales).toEqual([1, 4, 8]);
    expect(cache.get("a")).not.toBe(first);
  });


  it("factors the PLACEMENT stretch into the raster demand (152×26 SVG placed at 280×56)", async () => {
    // The live repro behind this test: the Apollo lockup SVG is 152×26
    // intrinsic but placed into a 280×56 box — at 200% zoom on a retina
    // screen (view scale 4) a zoom-only ladder rasterized 608px and painted
    // it across ~1120 device px: visibly soft. The draw-size hint closes it.
    const { rasterize, calls } = stubRasterizer({ width: 152, height: 26 });
    const cache = new CanvasKitImageCache(svgCk(() => fakeImage()), {
      resolveUrl: () => "/asset-store/aa",
      fetcher: async () => textBuffer(SVG_TEXT),
      rasterizeSvg: rasterize
    });

    cache.noteDrawSize("a", 280, 56);
    cache.setViewScale(4);
    cache.get("a");
    await flush();
    // First decode runs before the intrinsic size is known (view scale only);
    // the very next draw sees the stretch (max ratio 56/26 ≈ 2.15 → demand
    // ≈ 8.6 → bucket 16) and re-rasterizes.
    cache.get("a");
    await flush();
    expect(calls.map((c) => c.scale)).toEqual([4, 16]);

    // Sharp enough now: further draws at this view stay quiet.
    cache.get("a");
    await flush();
    expect(calls.length).toBe(2);
  });

  it("drops a sharpen that lands after invalidate() — no resurrect, no double-free", async () => {
    let firstDeleted = 0;
    const first = { delete: () => (firstDeleted += 1) } as unknown as Image;
    let releaseSharpen: () => void = () => {};
    let rasterCalls = 0;
    let fetches = 0;
    const rasterize: SvgRasterizer = async (_text, scale) => {
      rasterCalls += 1;
      if (rasterCalls === 2) {
        await new Promise<void>((resolve) => {
          releaseSharpen = resolve;
        });
      }
      return {
        source: {} as CanvasImageSource,
        intrinsicWidth: 100,
        intrinsicHeight: 50,
        scale
      };
    };
    const cache = new CanvasKitImageCache(svgCk(() => first), {
      resolveUrl: () => "/asset-store/aa",
      fetcher: async () => {
        fetches += 1;
        return textBuffer(SVG_TEXT);
      },
      rasterizeSvg: rasterize
    });

    cache.get("a");
    await flush();
    cache.setViewScale(4);
    cache.get("a"); // sharpen starts and parks on releaseSharpen
    cache.invalidate("a");
    releaseSharpen();
    await flush();

    // The parked sharpen resolved AFTER the entry was dropped: it must not
    // resurrect the asset, must not re-fetch, and must not double-free.
    expect(firstDeleted).toBe(1); // invalidate's delete only
    expect(fetches).toBe(1);

    // The next draw starts a clean reload.
    expect(cache.get("a")).toBeNull();
    await flush();
    expect(fetches).toBe(2);
  });
});
