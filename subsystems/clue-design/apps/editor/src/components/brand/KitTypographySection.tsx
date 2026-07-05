import React from "react";

import {
  fontSpecimenStack,
  readFonts,
  readTypographyRamp,
  type FontEntry
} from "./kitJson";

const FONT_SUGGESTIONS = ["Inter", "Work Sans", "DM Sans"];

function FontCard({ font }: { font: FontEntry }): React.ReactElement {
  const stack = fontSpecimenStack(font);
  const facesMissing = font.faces.length === 0;
  return (
    <div className="brand-card kit-font-card">
      <span className="title">{font.family}</span>
      {/* Specimen line rendered in the ingested family — data, not chrome. */}
      <p className="kit-font-specimen" style={{ fontFamily: stack }}>
        Aa Bb Cc 123
      </p>
      {facesMissing ? (
        <div className="kit-font-warning">
          <span className="status-pill is-draft">
            Font files not sourced — upload or pick an alternative
          </span>
          <div className="kit-font-suggestions">
            {FONT_SUGGESTIONS.map((name) => (
              <span className="chip" key={name}>
                {name}
              </span>
            ))}
          </div>
        </div>
      ) : (
        <table className="brand-table kit-faces-table">
          <thead>
            <tr>
              <th>Weight</th>
              <th>Style</th>
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {font.faces.map((face, index) => (
              <tr key={`${face.weight}-${face.style}-${index}`}>
                <td className="mono">{face.weight ?? "—"}</td>
                <td>{face.style ?? "—"}</td>
                <td>
                  {face.sourceUrl ? (
                    <span className="status-pill is-approved">sourced</span>
                  ) : (
                    <span className="status-pill is-draft">not sourced</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/** Section 3 — one card per brand font (specimen + faces table or the
 * availability warning), then the type ramp table from tokens.typography. */
export function KitTypographySection({ kitJson }: { kitJson: any }): React.ReactElement | null {
  const fonts = readFonts(kitJson);
  const ramp = readTypographyRamp(kitJson);
  if (fonts.length === 0 && ramp.length === 0) return null;

  return (
    <section className="brand-section" aria-label="Typography">
      <div className="brand-section-head">
        <span className="title">Typography</span>
      </div>
      {fonts.length > 0 ? (
        <div className="grid-cards kit-font-grid">
          {fonts.map((font) => (
            <FontCard key={font.key} font={font} />
          ))}
        </div>
      ) : null}
      {ramp.length > 0 ? (
        <table className="brand-table kit-type-ramp">
          <thead>
            <tr>
              <th>Role</th>
              <th>Family</th>
              <th>Size</th>
              <th>Weight</th>
              <th>Line height</th>
            </tr>
          </thead>
          <tbody>
            {ramp.map((row, index) => (
              <tr key={`${row.role}-${index}`}>
                <td>{row.role}</td>
                <td>{row.family || "—"}</td>
                <td className="mono">{row.size ?? "—"}</td>
                <td className="mono">{row.weight ?? "—"}</td>
                <td className="mono">{row.lineHeight ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}
