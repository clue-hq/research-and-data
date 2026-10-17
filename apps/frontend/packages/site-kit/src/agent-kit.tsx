// The kit a section written by the agent (E5) builds with (Wave 2 A9): the same Shell, Button and
// Eyebrow our own sections use, plus Link and Card, so a new section takes the brand's surfaces,
// buttons, links, cards and motion exactly as the seller's site draws them. Image takes only files
// from the brand's assets (the validator checks the path); Link, Button and Card point a /route at
// wherever the site is served.
import type { ReactElement, ReactNode } from "react";
import type { BrandData } from "./brand";
import { lookNamed } from "./looks";
import { ElementKeySchema } from "./edits";
import { Button as BrandButton, Eyebrow, Shell, type AnySurface, type Href } from "./sections";
import { logoFiles } from "./shell";

/** A prop the section marks `.meta({ edit: "inline" })` (S2a-2): text on the published page and in
 * Preview, but while the marketer edits the page an editable piece of it. Put it into the page as it
 * is (`{props.headline}`), never handle it as text. The section check types marked props as this. */
export type EditableText = string | ReactElement;

export type Kit = {
  /** surface: any surface brand.md lists (page, canvas, band-014036). */
  Shell: (props: { surface: AnySurface; children: ReactNode }) => ReactNode;
  /** look: a button style brand.md lists (Buttons); none is the kit's standard button. */
  Button: (props: { label: ReactNode; href: string; surface: AnySurface; look?: string; disabled?: boolean }) => ReactNode;
  /** look: a card style brand.md lists (Cards); href makes the whole card a link. */
  Card: (props: { look?: string; href?: string; children: ReactNode }) => ReactNode;
  /** el: a name for this text in the site inspector (letters and digits, with dots, underscores or
   * dashes between them; unique in the section), so the marketer can select and style it. Without
   * one it is not selectable. */
  Eyebrow: (props: { children: ReactNode; el?: string }) => ReactNode;
  /** A text link (an https:// URL, a /route of this site or a #anchor), drawn like the seller's links.
   * el: as for Eyebrow. */
  Link: (props: { href: string; children: ReactNode; el?: string }) => ReactNode;
  /** fit="fill": covers its positioned parent (a background photo). fit="contain": the whole image
   * inside its box, never cropped or rounded (a logo). Neither: full width with the brand's corners.
   * A logo from the brand kit is always shown whole. */
  Image: (props: { src: string; alt?: string; fit?: "fill" | "contain"; className?: never }) => ReactNode;
  /** True while the marketer edits this page in the editor's Edit mode: show the section's first
   * state and start nothing (no timers, no autoplay), so a click selects it instead of driving it. */
  editing: boolean;
};

export type AgentSectionModule = {
  schema: { safeParse: (value: unknown) => { success: boolean } };
  render: (props: never, kit: Kit) => ReactNode;
};

const IMAGE_CLASS = {
  fill: "absolute inset-0 h-full w-full object-cover",
  contain: "h-full w-full object-contain",
  standard: "w-full rounded-card object-cover",
} as const;

/** The agent's name for an element, when it is one the inspector can address; otherwise none. */
const elementKey = (el: string | undefined) => (el !== undefined && ElementKeySchema.safeParse(el).success ? el : undefined);

export function makeKit(href: Href, brand: BrandData): Kit {
  const logos = logoFiles(brand);
  return {
    Shell,
    Button: ({ label, href: target, surface, look, disabled }) => (
      <BrandButton brand={brand} label={label} href={href(target)} surface={surface} look={look} disabled={disabled} />
    ),
    Card: ({ look, href: target, children }) => {
      const chosen = lookNamed(brand, "card", look);
      const className = chosen ? `brand-card brand-card-look-${chosen.index}` : "brand-card";
      return target ? <a href={href(target) || "#"} className={className}>{children}</a> : <div className={className}>{children}</div>;
    },
    Eyebrow: ({ children, el }) => <Eyebrow el={elementKey(el)}>{children}</Eyebrow>,
    Link: ({ href: target, children, el }) => (
      <a href={href(target) || "#"} className="brand-link" data-clue-el={elementKey(el)}>{children}</a>
    ),
    // eslint-disable-next-line @next/next/no-img-element
    Image: ({ src, alt, fit }) =>
      src ? <img src={src} alt={alt ?? ""} className={IMAGE_CLASS[fit ?? (logos.has(src) ? "contain" : "standard")]} /> : null,
    editing: false,
  };
}
