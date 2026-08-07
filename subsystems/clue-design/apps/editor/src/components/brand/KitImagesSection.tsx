import React, { useState } from "react";

import { assetBytesUrl } from "@/engine/brandHub";
import { readImages } from "./kitJson";

const VISIBLE_DEFAULT = 8;

/** Section 5 — image assets as thumbnails. Captions render only when the kit
 * carries a real title/description; a wall of cells each captioned "photo" is
 * noise. Long sets collapse behind "Show all". */
export function KitImagesSection({
  kitJson,
  apiBaseUrl
}: {
  kitJson: any;
  apiBaseUrl: string;
}): React.ReactElement | null {
  const images = readImages(kitJson);
  const [expanded, setExpanded] = useState(false);
  if (images.length === 0) return null;
  const visible = expanded ? images : images.slice(0, VISIBLE_DEFAULT);
  const hidden = images.length - visible.length;

  return (
    <section className="brand-section" aria-label="Images">
      <div className="brand-section-head">
        <span className="title">Images</span>
        <span className="caption">{images.length} captured</span>
      </div>
      <div className="grid-cards kit-image-grid">
        {visible.map((image) => (
          <div className="kit-image-cell" key={image.key} data-testid={`image-${image.key}`}>
            <div className="asset-thumb">
              {image.assetId ? (
                <img
                  src={assetBytesUrl(apiBaseUrl, image.assetId)}
                  alt={image.title ?? image.role ?? image.key}
                />
              ) : (
                <span className="caption">no asset</span>
              )}
            </div>
            {image.title ? <p className="kit-image-title">{image.title}</p> : null}
            {image.description ? (
              <p className="caption kit-image-desc">{image.description}</p>
            ) : null}
          </div>
        ))}
      </div>
      {hidden > 0 ? (
        <button type="button" className="btn btn-quiet btn-sm" onClick={() => setExpanded(true)}>
          Show all {images.length}
        </button>
      ) : null}
    </section>
  );
}
