"use client";

import { useAssetPreviewUrl } from "@/hooks/useAssetPreviewUrl";

/**
 * Asset preview <img> on the public content-addressed URL
 * (`/asset-store/{digest}`) — the only shape an <img> can fetch, since it
 * cannot send the workspace header the registry endpoints demand. The
 * thumbnail digest is preferred and full bytes are the built-in fallback
 * (both inside useAssetPreviewUrl), which retires this component's old
 * onError retry dance against the registry routes. Null (still resolving, or
 * a digest-less record) renders nothing rather than a guaranteed-401 image.
 */
export function AssetPreviewImage({
  assetId,
  alt,
  full = false,
  className
}: {
  assetId: string;
  alt: string;
  full?: boolean;
  className?: string;
}) {
  const src = useAssetPreviewUrl(assetId, full ? "bytes" : "thumbnail");
  return src ? <img className={className} src={src} alt={alt} /> : null;
}
