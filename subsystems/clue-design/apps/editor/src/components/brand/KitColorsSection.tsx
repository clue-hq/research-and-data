import React from "react";

import {
  groupColorsByRole,
  readColorTokens,
  readPaletteRamps,
  type ColorToken
} from "./kitJson";
import { KitSwatch } from "./KitSwatch";

function roleName(token: ColorToken): string {
  // Show the last two segments as the human role (e.g. "surface.brand").
  return token.token;
}

function ColorwayRows({
  label,
  tokens,
  dark
}: {
  label: string;
  tokens: ColorToken[];
  dark: boolean;
}): React.ReactElement | null {
  if (tokens.length === 0) return null;
  return (
    <div className="kit-colorway-group">
      <p className="eyebrow">{label}</p>
      {tokens.map((token) => {
        const hex = dark ? token.darkValue ?? token.value : token.value;
        return (
          <div className="kit-swatch-row" key={token.token}>
            <KitSwatch hex={hex} />
            <span className="kit-swatch-role">{roleName(token)}</span>
            <span className="mono kit-swatch-hex">{hex || "—"}</span>
          </div>
        );
      })}
    </div>
  );
}

function findToken(tokens: ColorToken[], name: string): ColorToken | undefined {
  return tokens.find((token) => token.token === name);
}

function ColorwayCard({
  title,
  tokens,
  dark,
  darkColorway
}: {
  title: string;
  tokens: ReturnType<typeof groupColorsByRole>;
  dark: boolean;
  darkColorway: string | null;
}): React.ReactElement {
  // The dark colorway is only judgeable ON its own dark surface (moda shows
  // dark cards dark) — the card paints itself with the kit's captured/derived
  // dark page + text values. Kit DATA, not chrome, so inline style is right.
  const page = findToken(tokens.backgrounds, "surface.page");
  const text = findToken(tokens.text, "text.primary");
  const darkStyle =
    dark && page?.darkValue && text?.darkValue
      ? { backgroundColor: page.darkValue, color: text.darkValue }
      : undefined;
  return (
    <div
      className={`brand-card kit-colorway-card${dark && darkStyle ? " is-dark" : ""}`}
      style={darkStyle}
    >
      <div className="kit-colorway-head">
        <span className="kit-colorway-title">{title}</span>
        {dark && darkColorway ? (
          <span className="status-pill kit-colorway-basis">{darkColorway}</span>
        ) : null}
      </div>
      <ColorwayRows label="Backgrounds" tokens={tokens.backgrounds} dark={dark} />
      <ColorwayRows label="Text" tokens={tokens.text} dark={dark} />
      <ColorwayRows label="Accent" tokens={tokens.accent} dark={dark} />
      <ColorwayRows label="Borders" tokens={tokens.borders} dark={dark} />
    </div>
  );
}

function Ramp({ label, tokens }: { label: string; tokens: ColorToken[] }): React.ReactElement | null {
  if (tokens.length === 0) return null;
  return (
    <div className="kit-ramp">
      <p className="eyebrow">{label}</p>
      <div className="ramp-row">
        {tokens.map((token) => (
          <KitSwatch key={token.token} hex={token.value} />
        ))}
      </div>
    </div>
  );
}

/** Section 2 — light + dark colorway cards side by side, then palette ramps and
 * extras. Dark values come from each token's `theme.dark` mode. */
export function KitColorsSection({
  kitJson,
  darkColorway
}: {
  kitJson: any;
  darkColorway: string | null;
}): React.ReactElement | null {
  const tokens = readColorTokens(kitJson);
  if (tokens.length === 0) return null;
  const grouped = groupColorsByRole(tokens);
  const ramps = readPaletteRamps(tokens);

  return (
    <section className="brand-section" aria-label="Colors">
      <div className="brand-section-head">
        <span className="title">Colors</span>
      </div>
      <div className="kit-colorway-grid">
        <ColorwayCard title="Light" tokens={grouped} dark={false} darkColorway={null} />
        <ColorwayCard
          title="Dark"
          tokens={grouped}
          dark
          darkColorway={darkColorway}
        />
      </div>
      {ramps.primary.length > 0 || ramps.neutral.length > 0 ? (
        <div className="kit-ramps">
          <Ramp label="Primary" tokens={ramps.primary} />
          <Ramp label="Neutral" tokens={ramps.neutral} />
        </div>
      ) : null}
      {ramps.extras.length > 0 ? (
        <div className="kit-extras">
          <p className="eyebrow">Extras</p>
          <div className="kit-extra-chips">
            {ramps.extras.map((token) => (
              <span className="chip" key={token.token}>
                <KitSwatch hex={token.value} />
                {token.token.replace("palette.extra.", "")}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
