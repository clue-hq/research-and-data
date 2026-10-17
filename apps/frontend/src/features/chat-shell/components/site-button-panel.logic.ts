// The site element inspector's button panel (plan 3), as pure decisions: what the Fill, Stroke and
// Layout rows show for the selected button, and the button box's whole new override after one change.
// The panel (site-button-panel.tsx) only draws these; the session writes the override as the section's
// `_edits` entry for the button's key. The label's typography is the text panel's (plan 1).
import type { StyleOverride } from "@clue/site-kit/edits";
import type { ComputedBox } from "@clue/site-kit/editor-protocol";

export type PaletteChoice = { label: string; value: string };
export type RadiusMode = "pill" | "number" | "custom";
export type WidthMode = "fit" | "fill" | "fixed";

export interface ButtonPanelValues {
  fill: string;
  fillToken: string | null;
  fillOpacity: string;
  fillNone: boolean;
  stroke: string;
  strokeToken: string | null;
  strokeOpacity: string;
  strokeNone: boolean;
  strokeWidth: string;
  radiusMode: RadiusMode;
  radius: string;
  corners: [string, string, string, string];
  paddingY: string;
  paddingX: string;
  widthMode: WidthMode;
  width: string;
}

export type ButtonPanelChange =
  | { kind: "fillToken" | "strokeToken"; token: string }
  | { kind: "fillHex" | "strokeHex"; hex: string }
  | { kind: "fillOpacity" | "strokeOpacity"; value: string }
  | { kind: "strokeNone" }
  | { kind: "strokeWidth" | "radius" | "paddingY" | "paddingX" | "width"; value: string }
  | { kind: "radiusPill" | "radiusNumber" | "radiusCustom" }
  | { kind: "corner"; index: 0 | 1 | 2 | 3; value: string }
  | { kind: "widthMode"; value: WidthMode };

export const BOX_RANGE = { max: 200, min: 0 } as const;
export const WIDTH_RANGE = { max: 2000, min: 1 } as const;

const round = (value: number) => String(Math.round(value * 10) / 10);
/** A drawn size as a starting value that can be written (a pill draws as 9999px, a wide box past 2000). */
const within = (value: string, range: { min: number; max: number }) => Math.min(range.max, Math.max(range.min, Number(value)));
type Color = NonNullable<StyleOverride["fill"]>;

function colourValues(color: Color | undefined, drawn: string, palette: readonly PaletteChoice[]) {
  const tokenValue = color && "token" in color ? palette.find((choice) => choice.label === color.token)?.value : undefined;
  return {
    hex: color ? ("hex" in color ? color.hex : (tokenValue ?? drawn)) : drawn,
    token: color && "token" in color ? color.token : null,
    opacity: `${color && "hex" in color ? color.opacity : 100}%`,
  };
}

/** What the rows show: the override where it sets something, else the button as drawn. */
export function buttonPanelValues(override: StyleOverride | null, box: ComputedBox, palette: readonly PaletteChoice[]): ButtonPanelValues {
  const fill = colourValues(override?.fill, box.fill || "#FFFFFF", palette);
  const stroke = colourValues(override?.borderColor, box.borderColor || "#000000", palette);
  const strokeWidth = override?.borderWidth ?? box.borderWidth;
  const radius = override?.radius;
  const corners = (Array.isArray(radius) ? radius : typeof radius === "number" ? [radius, radius, radius, radius] : box.radius).map(round) as ButtonPanelValues["corners"];
  const padding = override?.padding;
  const width = override?.width;
  return {
    fill: fill.hex,
    fillToken: fill.token,
    fillOpacity: fill.opacity,
    fillNone: !override?.fill && !box.fill,
    stroke: stroke.hex,
    strokeToken: stroke.token,
    strokeOpacity: stroke.opacity,
    strokeNone: strokeWidth === 0,
    strokeWidth: round(strokeWidth),
    radiusMode: radius === "pill" ? "pill" : Array.isArray(radius) ? "custom" : "number",
    radius: corners[0],
    corners,
    paddingY: round(padding === undefined ? box.paddingY : typeof padding === "number" ? padding : padding.y),
    paddingX: round(padding === undefined ? box.paddingX : typeof padding === "number" ? padding : padding.x),
    widthMode: width === "fill" ? "fill" : typeof width === "number" ? "fixed" : "fit",
    width: round(typeof width === "number" ? width : box.width),
  };
}

/** A number typed in a box ("12", "12px"), or null when it is not one within [min, max]. */
function size(value: string, range: { min: number; max: number }): number | null {
  const text = value.trim().replace(/px$/i, "").trim();
  if (!/^\d+(\.\d+)?$/.test(text)) return null;
  const number = Number(text);
  return number >= range.min && number <= range.max ? number : null;
}

function colourPatch(base: StyleOverride, prop: "fill" | "borderColor", change: ButtonPanelChange, drawn: string): Color | null {
  if (change.kind === "fillToken" || change.kind === "strokeToken") return change.token ? { token: change.token } : null;
  const current = base[prop];
  if (change.kind === "fillHex" || change.kind === "strokeHex") {
    if (!/^#[0-9A-Fa-f]{6}$/.test(change.hex)) return null;
    return { hex: change.hex.toUpperCase(), opacity: current && "hex" in current ? current.opacity : 100 };
  }
  if (change.kind === "fillOpacity" || change.kind === "strokeOpacity") {
    const text = change.value.trim().replace(/%$/, "").trim();
    if (!/^\d{1,3}$/.test(text) || Number(text) > 100) return null;
    return { hex: current && "hex" in current ? current.hex : drawn, opacity: Number(text) };
  }
  return null;
}

/** The button box's whole new override after one change, or null when the input cannot be a value
 * (refused, never clamped). Choosing what is already shown returns the override as it was, so no save
 * is made for it. */
export function buttonPanelPatch(override: StyleOverride | null, change: ButtonPanelChange, box: ComputedBox): StyleOverride | null {
  const base: StyleOverride = override ?? {};
  const shown = buttonPanelValues(base, box, []);
  switch (change.kind) {
    case "fillToken":
    case "fillHex":
    case "fillOpacity": {
      const fill = colourPatch(base, "fill", change, box.fill || "#FFFFFF");
      return fill ? { ...base, fill } : null;
    }
    case "strokeToken":
    case "strokeHex":
    case "strokeOpacity": {
      const borderColor = colourPatch(base, "borderColor", change, box.borderColor || "#000000");
      if (!borderColor) return null;
      // A colour on a button that has no stroke gives it one, so the change shows.
      const width = base.borderWidth ?? box.borderWidth;
      return { ...base, borderColor, ...(width > 0 ? {} : { borderWidth: 1 }) };
    }
    case "strokeNone": {
      const rest = { ...base };
      delete rest.borderColor;
      return { ...rest, borderWidth: 0 };
    }
    case "strokeWidth": {
      const value = size(change.value, BOX_RANGE);
      if (value === null) return null;
      return String(value) === shown.strokeWidth ? base : { ...base, borderWidth: value };
    }
    case "radius": {
      const value = size(change.value, BOX_RANGE);
      if (value === null) return null;
      return shown.radiusMode === "number" && String(value) === shown.radius ? base : { ...base, radius: value };
    }
    case "radiusPill":
      return base.radius === "pill" ? base : { ...base, radius: "pill" };
    case "radiusNumber":
      return typeof base.radius === "number" ? base : { ...base, radius: within(shown.corners[0], BOX_RANGE) };
    case "radiusCustom":
      return Array.isArray(base.radius) ? base : { ...base, radius: shown.corners.map((corner) => within(corner, BOX_RANGE)) };
    case "corner": {
      const value = size(change.value, BOX_RANGE);
      if (value === null) return null;
      const corners = shown.corners.map((corner) => within(corner, BOX_RANGE));
      if (corners[change.index] === value && Array.isArray(base.radius)) return base;
      corners[change.index] = value;
      return { ...base, radius: corners };
    }
    case "paddingY":
    case "paddingX": {
      const value = size(change.value, BOX_RANGE);
      if (value === null) return null;
      const y = change.kind === "paddingY" ? value : within(shown.paddingY, BOX_RANGE);
      const x = change.kind === "paddingX" ? value : within(shown.paddingX, BOX_RANGE);
      if (String(y) === shown.paddingY && String(x) === shown.paddingX) return base;
      return { ...base, padding: { y, x } };
    }
    case "widthMode":
      if (change.value === shown.widthMode) return base;
      return { ...base, width: change.value === "fixed" ? within(shown.width, WIDTH_RANGE) : change.value };
    case "width": {
      const value = size(change.value, WIDTH_RANGE);
      if (value === null) return null;
      return { ...base, width: value };
    }
  }
}
