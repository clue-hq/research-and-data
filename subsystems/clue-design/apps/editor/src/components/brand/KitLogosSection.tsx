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
 * reversed variants rendered on the ink backdrop. `onChoose` (when provided)
 * renders the human-curation affordance: pick the slot's logo from the
 * library when the scraper guessed wrong or found nothing. */
export function KitLogosSection({
  kitJson,
  apiBaseUrl,
  onChoose
}: {
  kitJson: any;
  apiBaseUrl: string;
  onChoose?: (slot: string) => void;
}): React.ReactElement | null {
  const groups = readLogos(kitJson);
  if (groups.length === 0 && !onChoose) return null;

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
          {onChoose ? (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              data-testid={`choose-logo-${group.usage}`}
              onClick={() => onChoose(group.usage)}
            >
              Change {group.usage} logo
            </button>
          ) : null}
        </div>
      ))}
      {groups.length === 0 && onChoose ? (
        <div className="kit-logo-group">
          <p className="eyebrow">No logo captured</p>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            data-testid="choose-logo-primary"
            onClick={() => onChoose("primary")}
          >
            Choose primary logo
          </button>
        </div>
      ) : null}
    </section>
  );
}
