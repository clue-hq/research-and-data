/**
 * A design document's gallery thumbnail renders in the background (2026-10-29): the design API
 * answers at once and says, in `X-Thumbnail-State`, what it sent —
 *
 * - `fresh`: this version's card;
 * - `stale`: an older version's card, while this one renders;
 * - `pending`: nothing yet (202, no image) — a brand-new document.
 *
 * The card shows what it got and asks again on this schedule until it is `fresh`.
 */
export type ThumbnailState = "fresh" | "stale" | "pending";

/** When a stale or pending card asks again: 3, 6, 12, 24 and 48 seconds, then it stops. */
export const THUMBNAIL_RETRY_DELAYS_MS = [3_000, 6_000, 12_000, 24_000, 48_000] as const;

/** What a thumbnail response is. An image with no header is final (any other image URL). */
export function thumbnailState(status: number, header: string | null): ThumbnailState {
  if (header === "stale" || header === "pending" || header === "fresh") return header;
  return status === 202 ? "pending" : "fresh";
}

/** How long to wait before asking again after `attempt` earlier retries, or null to stop. */
export function nextThumbnailRetry(state: ThumbnailState, attempt: number): number | null {
  if (state === "fresh") return null;
  return THUMBNAIL_RETRY_DELAYS_MS[attempt] ?? null;
}
