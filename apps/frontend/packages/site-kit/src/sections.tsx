// Our own sections (Wave 2 A9). Every style choice is a name from the brand kit — a surface, a
// heading role, a button style — and every value is the kit's: the theme (theme.ts) draws buttons,
// links, type colours, spacing and rules from its measured tokens. No style value lives in this file
// (test/style-literals.test.ts). Text fields are `contentEditable`, so they edit in place on the canvas.
// Every text element carries the inspector's key attribute (edits.ts ELEMENT_KEY_ATTR), named by the prop it draws,
// so the site inspector can select it and a section's `_edits` can style it.
import type { ComponentConfig } from "@puckeditor/core";
import { createContext, useContext, type ReactNode } from "react";
import type { BrandData } from "./brand";
import { buttonLookOptions, lookIcon, lookNamed } from "./looks";
import { richText } from "./rich";
import { newTabAttrs, rich, withoutLinks } from "./rich-node";
import { HEADING_ROLES } from "./schemas";
import { surfaceChoices } from "./surfaces";

export type Surface = "page" | "card" | "muted" | "brandSubtle" | "brand" | "inverse";
/** One of our six, or one of this brand's other surfaces by its choice name. A plain string: Puck's
 * render props (WithDeepSlots) map the `string & {}` of `Surface | (string & {})` to an object type. */
export type AnySurface = string;
export type HeadingRole = "display" | "headline" | "title";
type Text = string | ReactNode;

export const SURFACE_CLASS: Record<Surface, string> = {
  page: "bg-surface-page text-on-surface-page",
  card: "bg-surface-card text-on-surface-card",
  muted: "bg-surface-muted text-on-surface-muted",
  brandSubtle: "bg-surface-brand-subtle text-on-surface-brand-subtle",
  brand: "bg-surface-brand text-on-surface-brand",
  inverse: "bg-surface-inverse text-on-surface-inverse",
};

export function surfaceClass(surface: AnySurface): string {
  return SURFACE_CLASS[surface as Surface] ?? `bg-surface-${surface} text-on-surface-${surface}`;
}

const HEADING_CLASS: Record<HeadingRole, string> = {
  display: "font-display text-display brand-ink-display",
  headline: "font-headline text-headline brand-ink-headline",
  title: "font-title text-title brand-ink-title",
};

const headingRoleField = {
  type: "select" as const,
  label: "Heading size",
  options: HEADING_ROLES.map((value) => ({ label: value[0].toUpperCase() + value.slice(1), value })),
};
const text = (label: string) => ({ type: "text" as const, label, contentEditable: true });
const area = (label: string) => ({ type: "textarea" as const, label, contentEditable: true });

export const Shell = ({ surface, children }: { surface: AnySurface; children: ReactNode }) => (
  <section className={surfaceClass(surface)}>
    <div className="brand-content px-page-margin py-section">{children}</div>
  </section>
);

/** `el`: the element's key for the site inspector (edits.ts ELEMENT_KEY_ATTR). */
export const Eyebrow = ({ children, el }: { children: Text; el?: string }) =>
  children ? <p className="font-eyebrow text-eyebrow brand-ink-eyebrow" data-clue-el={el}>{children}</p> : null;

/** In the editor, the section's props as stored (the drawn ones hold Puck's in-place widgets, which
 * are never empty); null on a published page, whose drawn props are the stored ones. */
export const StoredProps = createContext<Record<string, unknown> | null>(null);

/** Whether the stored words have nothing to show. A prop the section does not have counts as empty
 * only where it is known to hold the words (`missingIsEmpty`: our own sections); an agent's button
 * may be named differently from the prop holding its words, so there a missing prop decides nothing. */
const noWords = (stored: Record<string, unknown>, prop: string, missingIsEmpty: boolean) => {
  if (!Object.hasOwn(stored, prop)) return missingIsEmpty;
  const value = stored[prop];
  return typeof value !== "string" || richText(value).trim() === "";
};

/** The kit's standard button, or one of the brand's looks by name, with that look's own icon. `el`
 * names it for the site inspector (plan 3): the box carries `el`, its words `<el>.label`. `words`:
 * the prop its words are stored in, so the editor draws no button where the published page draws
 * none (its words are empty). */
export function Button({ brand, label, href, surface, look, disabled, el, newTab, words, missingIsEmpty = false }: {
  brand: BrandData; label: Text; href: string; surface: AnySurface; look?: string; disabled?: boolean; el?: string; newTab?: boolean;
  words?: string; missingIsEmpty?: boolean;
}) {
  const stored = useContext(StoredProps);
  if (!label || (stored && words && noWords(stored, words, missingIsEmpty))) return null;
  const chosen = lookNamed(brand, "button", look);
  const icon = lookIcon(brand, chosen);
  const mark = icon
    ? icon.svg
      ? <span aria-hidden className="brand-btn-icon" dangerouslySetInnerHTML={{ __html: icon.svg }} />
      : <span aria-hidden className="brand-btn-icon">{icon.glyph}</span>
    : null;
  return (
    <a
      href={disabled ? undefined : href || "#"}
      {...newTabAttrs(newTab)}
      aria-disabled={disabled || undefined}
      className={chosen ? `brand-btn brand-look-${chosen.index}` : "brand-btn"}
      data-surface={surface}
      data-clue-el={el}
    >
      {icon?.position === "start" ? mark : null}
      <span data-clue-el={el ? `${el}.label` : undefined}>{withoutLinks(label)}</span>
      {icon?.position === "end" ? mark : null}
    </a>
  );
}

export type Href = (value: string) => string;

/** The rich text field of the editor (richTextField in site-kit/editor), injected so published pages
 * never load TipTap. Without it a rich prop keeps its plain in-place field. */
export type RichField = (label: string, options?: { links?: boolean }) => object;

export function makeSections(
  brand: BrandData,
  href: Href,
  AssetPicker?: (props: { assets: BrandData["assets"]; value: string; onChange: (v: string) => void }) => ReactNode,
  richField?: RichField,
) {
  // Our rich props (schemas.ts RICH_PROPS) edit as rich text in the editor (plan 2).
  const richText = (label: string) => richField?.(label) ?? text(label);
  const richArea = (label: string) => richField?.(label) ?? area(label);
  // A button's words: rich text without links (plan 3).
  const buttonText = (label: string) => richField?.(label, { links: false }) ?? text(label);
  const newTabField = (label: string) => ({ type: "radio" as const, label, options: [{ label: "Yes", value: true }, { label: "No", value: false }] });
  const imageField = {
    type: "custom" as const,
    label: "Image (brand assets)",
    render: ({ value, onChange }: { value: string; onChange: (v: string) => void }) =>
      AssetPicker ? <AssetPicker assets={brand.assets} value={value} onChange={onChange} /> : <span />,
  };
  const surfaceField = {
    type: "select" as const,
    label: "Surface",
    options: surfaceChoices(brand).map((choice) => ({ label: choice.label, value: choice.value })),
  };
  const lookOptions = buttonLookOptions(brand);
  /** Left out when the brand has no button styles: there would be nothing to choose. */
  const buttonLookField = lookOptions.length > 1 ? { buttonLook: { type: "select" as const, label: "Button style", options: lookOptions } } : {};

  const StatsBand: ComponentConfig<{
    surface: AnySurface; align: "left" | "center"; eyebrow: Text; heading: Text; intro: Text;
    stats: { value: string; label: string }[]; source: Text;
  }> = {
    label: "Stats band",
    fields: {
      surface: surfaceField,
      align: { type: "radio", label: "Alignment", options: [{ label: "Left", value: "left" }, { label: "Centre", value: "center" }] },
      eyebrow: richText("Eyebrow"), heading: richText("Heading"), intro: richArea("Intro"),
      stats: {
        type: "array", label: "Stats", max: 4,
        arrayFields: { value: { type: "text" }, label: { type: "textarea" } },
        getItemSummary: (item: { value?: string }) => item.value || "Stat",
      },
      source: richText("Source line"),
    } as never,
    defaultProps: {
      surface: "brandSubtle", align: "left", eyebrow: "", heading: "A headline about the result", intro: "",
      stats: [{ value: "7.4%", label: "What the number means" }], source: "",
    },
    render: ({ surface, align, eyebrow, heading, intro, stats, source }) => {
      const r = (value: unknown) => rich(value, href);
      const centered = align === "center";
      const columns = ["", "sm:grid-cols-1", "sm:grid-cols-2", "sm:grid-cols-3", "sm:grid-cols-2 lg:grid-cols-4"][stats.length] ?? "sm:grid-cols-3";
      return (
        <Shell surface={surface}>
          <div className={centered ? "mx-auto text-center [&>*]:mx-auto" : ""}>
            <Eyebrow el="eyebrow">{r(eyebrow)}</Eyebrow>
            <h2 className="mt-stack-tight max-w-[24ch] font-title text-title brand-ink-title" data-clue-el="heading">{r(heading)}</h2>
            {intro ? <p className="mt-stack-default max-w-[60ch] font-body text-body brand-ink-body" data-clue-el="intro">{r(intro)}</p> : null}
          </div>
          <dl className={`mt-stack-loose grid gap-stack-loose ${columns} ${centered ? "text-center [&_dd]:mx-auto" : ""}`}>
            {stats.map((stat, index) => (
              <div key={index} className="brand-rule-t pt-stack-default">
                <dt className="font-headline text-headline brand-ink-headline" data-clue-el={`stats.${index}.value`}>{stat.value}</dt>
                <dd className="mt-stack-tight max-w-[32ch] font-body text-body brand-ink-body" data-clue-el={`stats.${index}.label`}>{stat.label}</dd>
              </div>
            ))}
          </dl>
          {source ? <p className={`mt-stack-loose font-caption text-caption brand-ink-caption ${centered ? "text-center" : ""}`} data-clue-el="source">{r(source)}</p> : null}
        </Shell>
      );
    },
  };

  const FeatureSplit: ComponentConfig<{
    surface: AnySurface; eyebrow: Text; heading: Text; headingRole: HeadingRole; body: Text;
    image: string; imageSide: "left" | "right"; buttonLabel: Text; buttonHref: string; buttonLook: string; buttonNewTab?: boolean;
  }> = {
    label: "Feature split",
    fields: {
      surface: surfaceField, eyebrow: richText("Eyebrow"), heading: richText("Heading"),
      headingRole: headingRoleField, body: richArea("Body"), image: imageField,
      imageSide: { type: "radio", label: "Image side", options: [{ label: "Left", value: "left" }, { label: "Right", value: "right" }] },
      buttonLabel: buttonText("Button label"), buttonHref: { type: "text", label: "Button link" }, ...buttonLookField,
      buttonNewTab: newTabField("Open the button's link in a new tab"),
    } as never,
    defaultProps: {
      surface: "page", eyebrow: "", heading: "What this does for them", headingRole: "title",
      body: "One or two plain sentences.", image: "", imageSide: "left", buttonLabel: "", buttonHref: "", buttonLook: "",
    },
    render: ({ surface, eyebrow, heading, headingRole, body, image, imageSide, buttonLabel, buttonHref, buttonLook, buttonNewTab }) => (
      <Shell surface={surface}>
        {/* No image: one text column, not an empty frame beside the words. */}
        <div className={image ? "grid items-center gap-stack-loose md:grid-cols-2" : "max-w-[60ch]"}>
          {image ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={image} alt="" className={`w-full rounded-card object-cover ${imageSide === "right" ? "md:order-2" : ""}`} />
          ) : null}
          <div>
            <Eyebrow el="eyebrow">{rich(eyebrow, href)}</Eyebrow>
            <h2 className={`mt-stack-tight ${HEADING_CLASS[headingRole]}`} data-clue-el="heading">{rich(heading, href)}</h2>
            <p className="mt-stack-default max-w-[52ch] font-body text-body brand-ink-body" data-clue-el="body">{rich(body, href)}</p>
            <div className="mt-stack-loose">
              <Button brand={brand} label={rich(buttonLabel, href)} href={href(buttonHref)} surface={surface} look={buttonLook} el="button" newTab={buttonNewTab} words="buttonLabel" missingIsEmpty />
            </div>
          </div>
        </div>
      </Shell>
    ),
  };

  const ProofCard: ComponentConfig<{
    surface: AnySurface; kicker: Text; metric: Text; metricLabel: Text; heading: Text; body: Text;
    source: Text; linkLabel: Text; linkHref: string; linkNewTab?: boolean;
  }> = {
    label: "Proof card",
    fields: {
      surface: surfaceField, kicker: richText("Kicker (whose result)"), metric: richText("Metric"),
      metricLabel: richText("Metric label"), heading: richText("Heading"), body: richArea("Body"),
      source: richText("Source line"), linkLabel: text("Link label"), linkHref: { type: "text", label: "Link" },
      linkNewTab: { type: "radio", label: "Open the link in a new tab", options: [{ label: "Yes", value: true }, { label: "No", value: false }] },
    } as never,
    defaultProps: {
      surface: "card", kicker: "Customer or study", metric: "13%", metricLabel: "what changed",
      heading: "What they did", body: "", source: "", linkLabel: "", linkHref: "",
    },
    render: ({ surface, kicker, metric, metricLabel, heading, body, source, linkLabel, linkHref, linkNewTab }) => (
      <Shell surface="page">
        <div className={`grid gap-stack-loose rounded-card p-card-padding md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] ${surfaceClass(surface)}`}>
          <div>
            <Eyebrow el="kicker">{rich(kicker, href)}</Eyebrow>
            <p className="mt-stack-default font-display text-display brand-ink-display" data-clue-el="metric">{rich(metric, href)}</p>
            <p className="mt-stack-tight font-body text-body brand-ink-body" data-clue-el="metricLabel">{rich(metricLabel, href)}</p>
          </div>
          <div className="self-end">
            <h3 className="font-title text-title brand-ink-title" data-clue-el="heading">{rich(heading, href)}</h3>
            {body ? <p className="mt-stack-default font-body text-body brand-ink-body" data-clue-el="body">{rich(body, href)}</p> : null}
            {source ? <p className="mt-stack-default font-caption text-caption brand-ink-caption" data-clue-el="source">{rich(source, href)}</p> : null}
            {linkLabel ? (
              <a href={href(linkHref) || "#"} {...newTabAttrs(linkNewTab)} className="brand-link mt-stack-default inline-block font-cta text-cta" data-clue-el="linkLabel">{linkLabel}</a>
            ) : null}
          </div>
        </div>
      </Shell>
    ),
  };

  const CtaBand: ComponentConfig<{
    surface: AnySurface; heading: Text; body: Text; buttonLabel: Text; buttonHref: string; buttonLook: string; buttonNewTab?: boolean;
  }> = {
    label: "Call to action band",
    fields: {
      surface: surfaceField, heading: richText("Heading"), body: richArea("Body"),
      buttonLabel: buttonText("Button label"), buttonHref: { type: "text", label: "Button link" }, ...buttonLookField,
      buttonNewTab: newTabField("Open the button's link in a new tab"),
    } as never,
    defaultProps: { surface: "brand", heading: "The one next step", body: "", buttonLabel: "Get started", buttonHref: "", buttonLook: "" },
    render: ({ surface, heading, body, buttonLabel, buttonHref, buttonLook, buttonNewTab }) => (
      <Shell surface={surface}>
        <div className="mx-auto max-w-[60ch] text-center">
          <h2 className="font-headline text-headline brand-ink-headline" data-clue-el="heading">{rich(heading, href)}</h2>
          {body ? <p className="mt-stack-default font-body text-body brand-ink-body" data-clue-el="body">{rich(body, href)}</p> : null}
          <div className="mt-stack-loose">
            <Button brand={brand} label={rich(buttonLabel, href)} href={href(buttonHref)} surface={surface} look={buttonLook} el="button" newTab={buttonNewTab} words="buttonLabel" missingIsEmpty />
          </div>
        </div>
      </Shell>
    ),
  };

  return { StatsBand, FeatureSplit, ProofCard, CtaBand };
}
