import type { z } from "zod";
import type { BrandColorGroupSchema, BrandTypeface } from "./brand-context";

/**
 * The measured view the Brand page draws (Wave 2 A9, Task X6): plain, serializable data built on the
 * server by `measured-brand.ts`, plus the two small helpers the components need. It imports nothing
 * from site-kit, so the page's client bundle carries none of the reading code.
 */

type BrandColorGroup = z.infer<typeof BrandColorGroupSchema>;

export type SampleState = "rest" | "hover" | "pressed" | "focus" | "disabled";

/** One measured value: what it is, its CSS value, and the kit token that holds it. */
export interface MeasuredValue {
  part: string;
  label: string;
  value: string;
  token: string;
}

export interface MeasuredIcon {
  position: "start" | "end";
  glyph: string | null;
  /** The kit's own SVG as a data URL: drawn as an image, so its markup never runs on this page. */
  src: string | null;
  width: number | null;
  height: number | null;
  style: Record<string, string>;
}

/** A style in one state, drawn with its own measured values. */
export interface MeasuredSample {
  state: SampleState;
  name: string;
  /** React style for the drawn element: measured values only, plus inline-flex alignment. */
  style: Record<string, string>;
  /** The preview's background: the kit's page colour, or its inverse when the style would not show. */
  backdrop: string | null;
  icon: MeasuredIcon | null;
  /** Rest lists every measured value; another state lists only what it changes. */
  values: MeasuredValue[];
  note: string | null;
}

export interface MeasuredStyleView {
  id: string;
  component: string;
  variant: string;
  name: string;
  /** The word drawn in the sample ("Button"): the seller's own words are not captured. */
  word: string;
  /** The measured font family, to load the kit's typeface for the sample. */
  family: string | null;
  samples: MeasuredSample[];
  transitions: MeasuredValue[];
}

export interface MeasuredGroup {
  id: string;
  title: string;
  styles: MeasuredStyleView[];
}

export interface SpacingStep {
  id: string;
  name: string;
  value: string;
  token: string;
  measured: boolean;
}

export interface MotionCard {
  id: string;
  name: string;
  headline: string;
  lines: string[];
}

export interface MeasuredBrandView {
  /** "Section backgrounds", then one group per measured style: added to the Colors panel. */
  colorGroups: BrandColorGroup[];
  /** Minted colour tokens shown in `colorGroups`, so "Semantic roles" leaves them out. */
  movedColors: string[];
  groups: MeasuredGroup[];
  spacing: SpacingStep[];
  animations: MotionCard[];
  reveals: MotionCard[];
  scripted: MotionCard[];
}

export type MeasuredSection = "components" | "spacing" | "motion";

/** The Brand-kit sections this kit has something to show in, in sidebar order. */
export function measuredSections(view: MeasuredBrandView | null): MeasuredSection[] {
  if (!view) return [];
  const sections: MeasuredSection[] = [];
  if (view.groups.length) sections.push("components");
  if (view.spacing.length) sections.push("spacing");
  if (view.animations.length || view.reveals.length || view.scripted.length) sections.push("motion");
  return sections;
}

/** The kit's typeface for a measured family, so the sample can load it (case-insensitive). */
export function typefaceFor(typefaces: readonly BrandTypeface[], family: string | null): BrandTypeface | null {
  if (!family) return null;
  const wanted = family.toLocaleLowerCase();
  return typefaces.find((typeface) => typeface.family.toLocaleLowerCase() === wanted) ?? null;
}
