"use client";

import { useEffect, useState } from "react";

import { assetFullUrl, assetPreviewUrl } from "@/engine/brandLibrary";

/**
 * Asset preview <img> that prefers the `/thumbnail` route and falls back to
 * `/bytes` on error (the thumbnail is not generated for every asset kind).
 */
export function AssetPreviewImage({
  apiBaseUrl,
  assetId,
  alt,
  full = false,
  className
}: {
  apiBaseUrl: string;
  assetId: string;
  alt: string;
  full?: boolean;
  className?: string;
}) {
  const primary = full
    ? assetFullUrl(apiBaseUrl, assetId)
    : assetPreviewUrl(apiBaseUrl, assetId);
  const [src, setSrc] = useState(primary);
  const [erroredOnce, setErroredOnce] = useState(false);

  useEffect(() => {
    setSrc(primary);
    setErroredOnce(false);
  }, [primary]);

  return (
    <img
      className={className}
      src={src}
      alt={alt}
      onError={() => {
        if (!erroredOnce && !full) {
          setErroredOnce(true);
          setSrc(assetFullUrl(apiBaseUrl, assetId));
        }
      }}
    />
  );
}
