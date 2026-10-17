// The site element inspector's text panel, as pure decisions (plan 1): what each control shows for the
// selected text element, and the element's whole new override after one change. The panel
// (site-text-panel.tsx) only draws these; the session writes the override as the section's `_edits`.
import type { StyleOverride } from "@clue/site-kit/edits";
import type { ComputedTypography } from "@clue/site-kit/editor-protocol";

export type TextAlign = ComputedTypography["textAlign"];
export type FontChoice = { family: string; weights: readonly number[] };
export type PaletteChoice = { label: string; value: string };

export interface TextPanelValues {
  /** The colour the swatch paints: a token's colour, the custom hex, or what the browser draws now. */
  color: string;
  /** The brand token in use, or null (a custom colour, or none set). */
  colorToken: string | null;
  opacity: string;
  fontFamily: string;
  fontSize: string;
  fontWeight: string;
  bold: boolean;
  italic: boolean;
  underline: boolean;
  textAlign: TextAlign;
}

export type TextPanelChange =
  | { kind: "colorToken"; token: string }
  | { kind: "colorHex"; hex: string }
  | { kind: "opacity"; value: string }
  | { kind: "fontFamily"; value: string }
  | { kind: "fontSize"; value: string }
  | { kind: "fontWeight"; value: string }
  | { kind: "bold" | "italic" | "underline"; on: boolean }
  | { kind: "textAlign"; value: TextAlign };

/** The ad editor's weight names (image-inspector FONT_WEIGHT_OPTIONS). */
const WEIGHT_NAMES: Record<number, string> = {
  100: "Thin", 200: "Extra Light", 300: "Light", 400: "Regular", 500: "Medium",
  600: "Semi Bold", 700: "Bold", 800: "Extra Bold", 900: "Black",
};
const ALL_WEIGHTS = [100, 200, 300, 400, 500, 600, 700, 800, 900];
export const FONT_SIZE_RANGE = { max: 200, min: 8 } as const;

export function weightLabel(weight: number): string {
  return `${weight} ${WEIGHT_NAMES[weight] ?? ""}`.trim();
}

/** The weights a family offers: a brand family's own faces; any other family, the nine. */
function weightsOf(fonts: readonly FontChoice[], family: string): readonly number[] {
  return fonts.find((font) => font.family === family)?.weights ?? ALL_WEIGHTS;
}

/** The Weight list for a family, labelled as the ad editor labels weights. */
export function weightOptions(fonts: readonly FontChoice[], family: string): string[] {
  return weightsOf(fonts, family).map(weightLabel);
}

/** What the panel shows: the element's override where it sets something, else what the browser
 * draws now. */
export function textPanelValues(
  override: StyleOverride | null,
  computed: ComputedTypography,
  palette: readonly PaletteChoice[],
): TextPanelValues {
  const color = override?.color;
  const tokenColor = color && "token" in color ? palette.find((choice) => choice.label === color.token)?.value : undefined;
  const fontWeight = override?.fontWeight ?? computed.fontWeight;
  return {
    color: color ? ("hex" in color ? color.hex : (tokenColor ?? computed.color)) : computed.color,
    colorToken: color && "token" in color ? color.token : null,
    opacity: `${color && "hex" in color ? color.opacity : 100}%`,
    fontFamily: override?.fontFamily ?? computed.fontFamily,
    fontSize: String(override?.fontSize ?? Math.round(computed.fontSize * 10) / 10),
    fontWeight: weightLabel(fontWeight),
    bold: fontWeight >= 700,
    italic: override?.italic ?? computed.italic,
    underline: override?.underline ?? computed.underline,
    textAlign: override?.textAlign ?? computed.textAlign,
  };
}

/** The element's whole new override after one change, or null when the input cannot be a value
 * (a size outside 8–200 or not a number, a malformed hex, a weight the family lacks): refused, never
 * clamped or guessed. */
export function textPanelPatch(
  override: StyleOverride | null,
  change: TextPanelChange,
  computed: ComputedTypography,
  fonts: readonly FontChoice[],
): StyleOverride | null {
  const base: StyleOverride = override ?? {};
  const family = base.fontFamily ?? computed.fontFamily;
  // Choosing what the text already shows changes nothing: the override comes back as it was, so no
  // save and no undo step is made for a click that changes nothing on the page.
  const shownSize = base.fontSize ?? Math.round(computed.fontSize * 10) / 10;
  const unchanged =
    (change.kind === "fontFamily" && change.value === family) ||
    (change.kind === "fontWeight" && Number.parseInt(change.value, 10) === (base.fontWeight ?? computed.fontWeight)) ||
    (change.kind === "fontSize" && Number(change.value.trim().replace(/px$/i, "").trim()) === shownSize) ||
    (change.kind === "textAlign" && change.value === (base.textAlign ?? computed.textAlign));
  if (unchanged) return base;
  switch (change.kind) {
    case "colorToken":
      return change.token ? { ...base, color: { token: change.token } } : null;
    case "colorHex": {
      if (!/^#[0-9A-Fa-f]{6}$/.test(change.hex)) return null;
      const opacity = base.color && "hex" in base.color ? base.color.opacity : 100;
      return { ...base, color: { hex: change.hex.toUpperCase(), opacity } };
    }
    case "opacity": {
      const text = change.value.trim().replace(/%$/, "").trim();
      if (!/^\d{1,3}$/.test(text) || Number(text) > 100) return null;
      // Opacity belongs to a custom colour: on a brand colour it starts from what is drawn now.
      const hex = base.color && "hex" in base.color ? base.color.hex : computed.color;
      return { ...base, color: { hex, opacity: Number(text) } };
    }
    case "fontFamily": {
      if (!fonts.some((font) => font.family === change.value)) return null;
      const next: StyleOverride = { ...base, fontFamily: change.value };
      // A weight the new family lacks would be refused on save: it goes, and the family's own applies.
      if (next.fontWeight !== undefined && !weightsOf(fonts, change.value).includes(next.fontWeight)) delete next.fontWeight;
      return next;
    }
    case "fontSize": {
      const text = change.value.trim().replace(/px$/i, "").trim();
      if (!/^\d+(\.\d+)?$/.test(text)) return null;
      const size = Number(text);
      if (size < FONT_SIZE_RANGE.min || size > FONT_SIZE_RANGE.max) return null;
      return { ...base, fontSize: size };
    }
    case "fontWeight": {
      const weight = Number.parseInt(change.value, 10);
      if (!weightsOf(fonts, family).includes(weight)) return null;
      return { ...base, fontWeight: weight };
    }
    case "bold": {
      // On: the family's lightest weight from 700 up (else its heaviest). Off: 400, or the family's
      // nearest below it — an explicit weight, so text that is bold by default stops being bold.
      const weights = weightsOf(fonts, family);
      const weight = change.on
        ? (weights.find((w) => w >= 700) ?? Math.max(...weights))
        : (weights.includes(400) ? 400 : ([...weights].reverse().find((w) => w < 700) ?? Math.min(...weights)));
      return { ...base, fontWeight: weight };
    }
    case "italic":
      return { ...base, italic: change.on };
    case "underline":
      return { ...base, underline: change.on };
    case "textAlign":
      return { ...base, textAlign: change.value };
  }
}
