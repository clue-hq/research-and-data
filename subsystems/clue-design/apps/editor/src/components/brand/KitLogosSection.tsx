import React from "react";

import { assetBytesUrl } from "@/engine/brandHub";
import { isReversedVariant, readLogos, type LogoVariant } from "./kitJson";

function LogoThumb({
  variant,
  apiBaseUrl,
  usage
}: {
  variant: LogoVariant;
  apiBaseUrl: string;
  usage: string;
}): React.ReactElement {
  const reversed = isReversedVariant(variant);
  return (
    <div className="kit-logo-cell">
      <div
        className="asset-thumb"
        // Reversed variants sit on the ink backdrop so a light-on-dark mark
        // reads — the permitted inline backgroundColor var reference.
        style={reversed ? { backgroundColor: "var(--ink)" } : undefined}
        data-testid={`logo-${variant.assetId ?? variant.name}`}
      >
        {variant.assetId ? (
          <img src={assetBytesUrl(apiBaseUrl, variant.assetId)} alt={`${usage} logo`} />
        ) : (
          <span className="caption">no asset</span>
        )}
      </div>
      {variant.colorMode ? <span className="chip">{variant.colorMode}</span> : null}
    </div>
  );
}

/** Section 4 — logo variants grouped by usage (primary / mark / wordmark),
 * reversed variants rendered on the ink backdrop. */
export function KitLogosSection({
  kitJson,
  apiBaseUrl
}: {
  kitJson: any;
  apiBaseUrl: string;
}): React.ReactElement | null {
  const groups = readLogos(kitJson);
  if (groups.length === 0) return null;

  return (
    <section className="brand-section" aria-label="Logos">
      <div className="brand-section-head">
        <span className="title">Logos</span>
      </div>
      {groups.map((group) => (
        <div className="kit-logo-group" key={group.key}>
          <p className="eyebrow">{group.usage}</p>
          <div className="grid-cards kit-logo-grid">
            {group.variants.map((variant, index) => (
              <LogoThumb
                key={`${variant.name}-${index}`}
                variant={variant}
                apiBaseUrl={apiBaseUrl}
                usage={group.usage}
              />
            ))}
          </div>
        </div>
      ))}
    </section>
  );
}
