import { Component, type ReactNode } from "react";
import { z } from "zod";
import type { Config, Fields } from "@puckeditor/core";
import type { BrandData } from "./brand";
import type { Clone, LinkReplacement, SlotValues, TextReplacement } from "./clone";

/** A cloned section's markup from its clone and props. `fillClone` (./clone) is one; a live page
 * passes its own (live-page's liveConfig). `id` is the section's component id. */
export type CloneHtml = (
  clone: Clone,
  values: SlotValues,
  replacements: TextReplacement[],
  links: LinkReplacement[],
  extras: { id: string; newTab: readonly string[] },
) => string;
import { CloneMarkup } from "./clone-markup";
import { richPropPaths, richValuesAt } from "./agent-props";
import { hasMarkup, mapRichLinks } from "./rich";
import { rich } from "./rich-node";
import { ROOT_KEY, editsCss, editsOf, orderOf, withoutEdits, type Edits } from "./edits";
import { themeCss } from "./theme";
import { makeSections, StoredProps } from "./sections";
import { makeKit, type AgentSectionModule } from "./agent-kit";
import { buttonLookOptions } from "./looks";
import { SiteFooter, SiteHeader, type FooterProps, type HeaderProps } from "./shell";

type ClonedSectionProps = {
  fragmentId: string;
  slots: SlotValues;
  replacements: TextReplacement[];
  links: LinkReplacement[];
  /** Element keys of the links that open in a new tab. */
  newTab?: string[];
  /** Plan 5: alt texts of its images, by element key. */
  alts?: Record<string, string>;
  /** Plan 6: a template's menu labels by page, and links after the pages. */
  menuLabels?: Record<string, string>;
  menuExtra?: { label: string; href: string; newTab?: boolean }[];
};

const SLOT_FIELD = {
  text: { type: "textarea" },
  href: { type: "text" },
  image: { type: "text" },
  visibility: {
    type: "radio",
    options: [
      { label: "Shown", value: true },
      { label: "Hidden", value: false },
    ],
  },
} as const;

/** Editor-only pieces, injected by the editor route so published pages never bundle them. */
export type EditorParts = {
  CloneEditor: (props: {
    itemId: string;
    clone: import("./clone").Clone;
    html: string;
    /** The markup this section would have with one text slot set to `value` (CloneEditor redraws
     * when a write leaves the markup unchanged, so the canvas shows what will publish). */
    htmlFor: (key: string, value: string) => string;
  }) => React.ReactNode;
  AssetPicker: (props: { assets: BrandData["assets"]; value: string; onChange: (value: string) => void }) => React.ReactNode;
  /** A hook, called while an agent section draws in the editor: reads a section's props as stored
   * (plain strings, before Puck puts its in-place widgets in), by its id (S2a-2 §2.5). */
  useRawProps?: () => (id: string) => Record<string, unknown> | undefined;
  /** The rich text field (site-kit/editor's richTextField): our rich props edit as rich text (plan 2). */
  richField?: (label: string, options?: { links?: boolean }) => object;
};

export type ConfigOptions = {
  /** Where this site is served, e.g. "/s/garner-syracuse"; internal links ("/analysis") resolve under it.
   * Without one, internal links stay as written (a site served at its domain's root). */
  basePath?: string;
  editor?: EditorParts;
  /** The site's agent-written sections (E5), by section name; they join its pages. */
  agentSections?: Record<string, AgentSectionModule>;
  /** How a cloned section gets its markup: `fillClone` (./clone) in the editor and the server
   * render; on a live page in the browser, the markup the server drew (live-page's liveConfig).
   * Passed in, never imported here, so the published page's runtime carries no HTML parser. */
  cloneHtml: CloneHtml;
  /** "page": the clones' CSS is drawn once outside the tree (a live page, render-core); otherwise
   * each clone carries its own. */
  cloneCss?: "inline" | "page";
};

/** The one error boundary around every agent section, in the editor and on the published page
 * alike. A section that fails while drawing in the browser — for example because the editor's
 * policy refused something it tried — takes only itself down and leaves an empty
 * data-agent-section-failed marker where it was; the rest of the page, and the editor, stay alive
 * (an uncaught render error unmounts a whole React root; Review focus 1 of live publishing). `name`
 * is the section, which the live page's error report reads from the boundary that caught the error
 * (hydrateSite). While nothing fails it renders no element of its own, so the server HTML is
 * unchanged (boundaries do nothing on the server: a section that throws there fails the render). */
export class SectionBoundary extends Component<
  { name: string; children: ReactNode; retry?: () => ReactNode | null },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch() {
    if (this.props.retry) {
      console.warn(`The agent section ${this.props.name} failed with its text editable on the canvas; it is drawn with its stored props and edited in the side panel.`);
    }
  }
  render() {
    if (!this.state.failed) return this.props.children;
    // The editor's one second try (S2a-2 §2.5); a failure there is the marker.
    const retry = this.props.retry?.();
    return retry ? <SectionBoundary name={this.props.name}>{retry}</SectionBoundary> : <div data-agent-section-failed={this.props.name} />;
  }
}

const noRawProps = () => () => undefined;

/** Whether a clone slot's text holds a link (only then are its links resolved under the base path;
 * any other value reaches the filler as written, so one equal to the captured words keeps them). */
const hasRichLink = (value: string) => /<a\b/i.test(value);

/** An agent section's rich prop paths, read from its zod schema; none when it cannot be read. */
function richPathsOf(module: AgentSectionModule): string[] {
  try {
    return richPropPaths(z.toJSONSchema(module.schema as z.ZodType) as Parameters<typeof richPropPaths>[0]);
  } catch {
    return [];
  }
}

/** The props with each rich string that holds markup replaced by its drawn element (copies only what
 * changes). */
function withRichProps<T extends Record<string, unknown>>(props: T, paths: readonly string[], href: (value: string) => string): T {
  let out: Record<string, unknown> = props;
  for (const { path, value } of richValuesAt(props, paths)) {
    if (!hasMarkup(value)) continue;
    out = setPath(out, path.split("."), rich(value, href));
  }
  return out as T;
}

function setPath(target: unknown, parts: string[], value: unknown): Record<string, unknown> {
  const [head, ...rest] = parts;
  const copy: Record<string, unknown> | unknown[] = Array.isArray(target) ? [...target] : { ...(target as Record<string, unknown>) };
  const current = (copy as Record<string, unknown>)[head];
  (copy as Record<string, unknown>)[head] = rest.length ? setPath(current, rest, value) : value;
  return copy as Record<string, unknown>;
}

// One config per brand and site. Fields and renders close over the brand's clone library and
// assets; the editor (client) and the published route (server) both call this.
export function makeConfig(brand: BrandData, options: ConfigOptions): Config {
  const href = (value: string) =>
    options.basePath && value && value.startsWith("/") && !value.startsWith("//")
      ? `${options.basePath}${value === "/" ? "" : value}`
      : value;
  const brandCss = themeCss(brand);
  // The header and footer are the page's first and last sections (plan 6: shell-entries.ts), so the
  // root draws only the brand's stylesheet around the page.
  const BrandRoot = ({ children }: { children: React.ReactNode }) => (
    <div className="brand-root">
      <style dangerouslySetInnerHTML={{ __html: brandCss }} />
      {children}
    </div>
  );

  const cloneOptions = [
    { label: "Choose a section…", value: "" },
    ...Object.values(brand.clones).map((clone) => ({
      label: `${clone.label?.slice(0, 60)} (${new URL(clone.page_url).pathname})`,
      value: clone.id,
    })),
  ];
  const sections = makeSections(brand, href, options.editor?.AssetPicker, options.editor?.richField);
  // Plan 6 (ruling R7): the fallback header and footer, sections of the page that only shell.json
  // places (the save check refuses them on a page). Their words edit in place like our sections'.
  const words = (label: string, links: boolean) =>
    options.editor?.richField?.(label, { links }) ?? { type: "text" as const, label, contentEditable: true };
  const yesNo = (label: string) => ({ type: "radio" as const, label, options: [{ label: "Yes", value: true }, { label: "No", value: false }] });
  // Written from the panels (images, alt texts) or on the canvas (menu labels), never typed in a field.
  const fromPanel = (label: string) => ({ type: "custom" as const, label, render: () => <span /> });
  const shellComponents = {
    SiteHeader: {
      label: "Header",
      fields: {
        accountLine: words("Account line", false),
        accountLogo: fromPanel("Account logo"),
        accountLogoAlt: fromPanel("Account logo alt text"),
        logo: fromPanel("Logo"),
        logoAlt: fromPanel("Logo alt text"),
        ctaLabel: words("Button label", false),
        ctaHref: { type: "text" as const, label: "Button link" },
        ctaNewTab: yesNo("Open the button's link in a new tab"),
        ...(buttonLookOptions(brand).length > 1 ? { ctaLook: { type: "select" as const, label: "Button style", options: buttonLookOptions(brand) } } : {}),
        menuLabels: fromPanel("Menu labels"),
        menuExtra: fromPanel("Extra menu links"),
      },
      render: (props: Record<string, unknown>) => <SiteHeader brand={brand} header={props as unknown as HeaderProps} href={href} />,
    },
    SiteFooter: {
      label: "Footer",
      fields: {
        legal: words("Legal line", true),
        logo: fromPanel("Logo"),
        logoAlt: fromPanel("Logo alt text"),
        privacyLabel: words("Privacy link words", false),
        privacyHref: { type: "text" as const, label: "Privacy link" },
        privacyNewTab: yesNo("Open the privacy link in a new tab"),
        termsLabel: words("Terms link words", false),
        termsHref: { type: "text" as const, label: "Terms link" },
        termsNewTab: yesNo("Open the terms link in a new tab"),
      },
      render: (props: Record<string, unknown>) => <SiteFooter brand={brand} footer={props as unknown as FooterProps} href={href} />,
    },
  };
  // This site's agent-written sections (E5): rendered with the same kit our sections use; no edit
  // fields (the editor gives them fields from their props schema).
  const kit = makeKit(href, brand);
  const useRawProps = options.editor?.useRawProps ?? noRawProps;
  const agentSections = Object.fromEntries(
    Object.entries(options.agentSections ?? {}).map(([name, module]) => {
      type SectionProps = Record<string, unknown> & { id?: string; puck?: { isEditing?: boolean } };
      // The section draws inside its own component, so its boundary catches what it throws. This is
      // the one place module.render is called. Props travel whole (not spread), so none is dropped.
      // kit.editing: true while the marketer edits the page (Puck's puck.isEditing), so the section
      // shows its first state and starts nothing.
      // `_edits` is the page's styling of the section, never one of its props: it is dropped here
      // too because the editor's second try below draws from the props as stored.
      // Its rich props (the ones it marked for editing in place, plan 2): a stored string with markup
      // reaches it as an element, drawn as the published page draws rich text; plain text stays a string.
      const richPaths = richPathsOf(module);
      const Drawn = ({ props }: { props: SectionProps }) =>
        module.render(withRichProps(withoutEdits(props), richPaths, href) as never, { ...kit, editing: Boolean(props.puck?.isEditing) });
      // In Edit mode, a section that throws with Puck's in-place widgets in its props is drawn once
      // more with its stored props (S2a-2 §2.5): edited in the side panel, never an empty box. The
      // boundary is keyed by the mode, so leaving Edit mode draws the section afresh.
      const Mounted = ({ props }: { props: SectionProps }) => {
        const rawProps = useRawProps();
        const editing = Boolean(props.puck?.isEditing);
        const retry = () => {
          const raw = rawProps(String(props.id ?? ""));
          return raw ? <Drawn props={{ ...raw, puck: props.puck }} /> : null;
        };
        // Outside Edit mode the editor draws the section from its props as stored, as the published
        // page does: Puck turns a rich text prop into its own read-only widget even in preview, and a
        // section may treat its text as a string (plan 2).
        const stored = !editing && options.editor?.useRawProps ? rawProps(String(props.id ?? "")) : undefined;
        return (
          <SectionBoundary key={editing ? "edit" : "view"} name={name} retry={editing && options.editor?.useRawProps ? retry : undefined}>
            <Drawn props={stored ? { ...stored, puck: props.puck } : props} />
          </SectionBoundary>
        );
      };
      return [
        name,
        {
          label: `${name} (agent)`,
          fields: {},
          // The wrapper lets compare_section find the component whatever its root element is.
          render: (props: SectionProps) => (
            <div data-agent-section={name}>
              <Mounted props={props} />
            </div>
          ),
        },
      ];
    }),
  );

  const config: Config<{
    ClonedSection: ClonedSectionProps;
    StatsBand: Record<string, unknown>;
    FeatureSplit: Record<string, unknown>;
    ProofCard: Record<string, unknown>;
    CtaBand: Record<string, unknown>;
  }> = {
    root: { render: ({ children }) => <BrandRoot>{children}</BrandRoot> },
    categories: {
      clones: { title: "The seller's sections", components: ["ClonedSection"] },
      brand: { title: "Brand sections", components: ["StatsBand", "FeatureSplit", "ProofCard", "CtaBand"] },
      ...(Object.keys(agentSections).length
        ? { agent: { title: "Agent sections", components: Object.keys(agentSections) as never } }
        : {}),
    },
    components: {
      ...(sections as unknown as Record<"StatsBand" | "FeatureSplit" | "ProofCard" | "CtaBand", never>),
      ...(shellComponents as unknown as Record<string, never>),
      ...(agentSections as unknown as Record<string, never>),
      ClonedSection: {
        label: "Cloned section",
        defaultProps: { fragmentId: "", slots: {}, replacements: [], links: [], newTab: [] },
        fields: {
          fragmentId: { type: "select", label: "Section", options: cloneOptions },
          slots: { type: "object", label: "Slots", objectFields: {} },
          replacements: {
            type: "array",
            label: "Text replacements (text with no slot)",
            arrayFields: { find: { type: "text" }, replace: { type: "text" } },
            getItemSummary: (item) => item.find || "New replacement",
          },
          links: {
            type: "array",
            label: "Link replacements (* = every link)",
            arrayFields: { find: { type: "text" }, replace: { type: "text" } },
            getItemSummary: (item) => item.find || "New link",
          },
          // Set from the link panel (site element inspector, plan 2), never typed in a field.
          newTab: { type: "custom", label: "Links opening in a new tab", render: () => <span /> },
          // Set from the image panel (plan 5), never typed in a field.
          alts: { type: "custom", label: "Image alt texts", render: () => <span /> },
          // Plan 6: a template's menu, written in place on the canvas or by the agent.
          menuLabels: { type: "custom", label: "Menu labels", render: () => <span /> },
          menuExtra: { type: "custom", label: "Extra menu links", render: () => <span /> },
        },
        resolveFields: (data, { fields }) => {
          const clone = brand.clones[data.props.fragmentId];
          const objectFields = Object.fromEntries(
            Object.entries(clone?.slots ?? {}).map(([key, slot]) => [
              key,
              { ...SLOT_FIELD[slot.kind], label: `${key} (${slot.kind})` },
            ]),
          );
          return { ...fields, slots: { type: "object", label: "Slots", objectFields } } as Fields<ClonedSectionProps>;
        },
        // No resolveData (review finding S1-1). Puck runs it on every page mount against the last
        // section it saw with the same id on ANY page or site in the frame (a module-wide cache), so
        // a rule that pre-filled the slots when the clone changed reset the agent's copy to the seller's wording on
        // a page switch, and the frame saved it. Nothing swaps a clone through this path: the agent
        // writes its slots itself, and the dock never changes `fragmentId`.
        // The second argument comes from the section wrapper below: the edits of the section, for `order`.
        render: ((
          { id, fragmentId, slots, replacements, links, newTab, alts, puck }: ClonedSectionProps & { id: string; puck?: { isEditing?: boolean } },
          context?: { edits: Edits },
        ) => {
          const clone = brand.clones[fragmentId];
          if (!clone) {
            return (
              <div className="p-card-padding text-center font-body text-body text-ink-muted">
                Choose a cloned section
              </div>
            );
          }
          const fill = options.cloneHtml;
          const resolvedSlots = Object.fromEntries(
            Object.entries(slots ?? {}).map(([key, value]) => [
              key,
              clone.slots[key]?.kind === "href" && typeof value === "string"
                ? href(value)
                : clone.slots[key]?.kind === "text" && typeof value === "string" && hasRichLink(value)
                  ? mapRichLinks(value, href)
                  : value,
            ]),
          );
          const resolvedLinks = (links ?? []).map((link) => ({ ...link, replace: href(link.replace) }));
          const extras = { id, newTab: newTab ?? [], order: orderOf(context?.edits ?? {}), alts: alts ?? {} };
          const html = fill(clone, resolvedSlots, replacements, resolvedLinks, extras);
          const Editor = options.editor?.CloneEditor;
          if (puck?.isEditing && Editor) {
            const htmlFor = (key: string, value: string) =>
              fill(clone, { ...resolvedSlots, [key]: hasRichLink(value) ? mapRichLinks(value, href) : value }, replacements, resolvedLinks, extras);
            return <Editor itemId={id} clone={clone} html={html} htmlFor={htmlFor} />;
          }
          return <CloneMarkup clone={clone} html={html} inlineCss={options.cloneCss !== "page"} />;
        }) as never,
      },
    },
  };

  // Every page section — ours, the clones and the agent's — draws inside the box that scopes its
  // manual styling (site element inspector, spec §4.5): its `_edits` as a stylesheet first, then the
  // section, which never sees `_edits`. Done once, here, so the editor, the static render and both
  // sides of a live page draw the same tree. The box is display:contents (themeCss), so it takes no
  // part in the page's layout. The header and footer are sections too (plan 6), so they draw in it.
  //
  // In the editor `_edits` is read from the section AS STORED (useRawProps): Puck's text transforms
  // match props by key name at any depth, so a section with a rich `heading` field receives
  // `_edits.heading` as Puck's widget, not the override. Elsewhere the drawn props are the stored ones.
  // The section is drawn from its edits too (plan 4: a copied section's `order` rearranges its markup).
  const SectionScope = ({ id, drawn, children }: { id: string; drawn: Record<string, unknown>; children: (edits: Edits) => ReactNode }) => {
    // Anywhere in the editor: Puck puts its widgets in the drawn props in Edit mode, and its read-only
    // rich text widget in preview too (plan 2). A published page has no raw props to read.
    const rawProps = useRawProps();
    const stored = rawProps(id);
    const edits = editsOf(stored ?? drawn);
    const css = editsCss(id, edits, brand);
    // Plan 6 (ruling R10): the header's own placement; the save check keeps these to its root.
    const placement = edits[ROOT_KEY];
    return (
      <div
        data-clue-section={id}
        className="clue-section"
        data-clue-sticky={placement?.sticky ? "" : undefined}
        data-clue-overlay={placement?.overlay ? "" : undefined}
      >
        {css ? <style data-clue-edits="" dangerouslySetInnerHTML={{ __html: css }} /> : null}
        <StoredProps.Provider value={stored ?? null}>{children(edits)}</StoredProps.Provider>
      </div>
    );
  };
  type Render = (props: Record<string, unknown>, context?: { edits: Edits }) => ReactNode;
  const components = config.components as unknown as Record<string, { render: Render }>;
  for (const [type, component] of Object.entries(components)) {
    const render = component.render;
    components[type] = {
      ...component,
      render: (props) => (
        <SectionScope drawn={props} id={String(props.id ?? "")}>
          {(edits) => render(withoutEdits(props), { edits })}
        </SectionScope>
      ),
    };
  }

  // Pages are loaded from storage as untyped Data, so callers take the config untyped.
  return config as unknown as Config;
}
