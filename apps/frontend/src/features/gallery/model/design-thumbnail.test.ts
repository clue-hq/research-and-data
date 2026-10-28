import assert from "node:assert/strict";
import { it } from "node:test";
import {
  THUMBNAIL_RETRY_DELAYS_MS,
  nextThumbnailRetry,
  thumbnailState,
} from "./design-thumbnail";

/**
 * Gallery thumbnails render in the background since 2026-10-29 (production: 705 renders for
 * 180 versions, site renders ~52 s each, all inside the request). The design API answers at
 * once: `fresh` (this version's card), `stale` (an older card while this one renders) or
 * `pending` (202, nothing yet). The card shows what it got and asks again until it is fresh.
 */

it("reads the readiness the design API sends", () => {
  assert.equal(thumbnailState(200, "fresh"), "fresh");
  assert.equal(thumbnailState(200, "stale"), "stale");
  assert.equal(thumbnailState(202, "pending"), "pending");
});

it("an image with no readiness header is final, and a bare 202 is still pending", () => {
  assert.equal(thumbnailState(200, null), "fresh");
  assert.equal(thumbnailState(202, null), "pending");
});

it("a stale or pending card asks again after 3, 6, 12, 24 and 48 seconds, then stops", () => {
  assert.deepEqual(THUMBNAIL_RETRY_DELAYS_MS, [3_000, 6_000, 12_000, 24_000, 48_000]);
  for (const state of ["stale", "pending"] as const) {
    const delays = [0, 1, 2, 3, 4].map((attempt) => nextThumbnailRetry(state, attempt));
    assert.deepEqual(delays, THUMBNAIL_RETRY_DELAYS_MS, state);
    assert.equal(nextThumbnailRetry(state, 5), null, state);
  }
});

it("a fresh card never asks again", () => {
  assert.equal(nextThumbnailRetry("fresh", 0), null);
});
