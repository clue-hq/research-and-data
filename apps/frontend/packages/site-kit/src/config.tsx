import type { Config, Fields } from "@puckeditor/core";
import type { BrandData } from "./brand";
import {
  fillClone,
  slotDefaults,
  type LinkReplacement,
  type SlotValues,
  type TextReplacement,
} from "./clone";
import { CloneMarkup } from "./clone-markup";
import { themeCss } from "./theme";
import { makeSections } from "./sections";
import { makeKit, type AgentSectionModule } from "./agent-kit";
import { SiteFooter, SiteHeader, type FooterProps, type HeaderProps, type ShellData } from "./shell";

type ClonedSectionProps = {
  fragmentId: string;
  slots: SlotValues;
  replacements: TextReplacement[];
  links: LinkReplacement[];
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
  CloneEditor: (props: { itemId: string; clone: import("./clone").Clone; html: string }) => React.ReactNode;
  AssetPicker: (props: { assets: BrandData["assets"]; value: string; onChange: (value: string) => void }) => React.ReactNode;
};

export type ConfigOptions = {
  /** Where this site is served, e.g. "/s/garner-syracuse"; internal links ("/analysis") resolve under it.
   * Without one, internal links stay as written (a site served at its domain's root). */
  basePath?: string;
  shell?: ShellData;
  /** "page" edits a route; "shell" edits the shared header and footer. */
  mode?: "page" | "shell";
  editor?: EditorParts;
  /** The site's agent-written sections (E5), by section name; they join its pages. */
  agentSections?: Record<string, AgentSectionModule>;
};

// One config per brand and site. Fields and renders close over the brand's clone library and
// assets; the editor (client) and the published route (server) both call this.
export function makeConfig(brand: BrandData, options: ConfigOptions): Config {
  const href = (value: string) =>
    options.basePath && value && value.startsWith("/") && !value.startsWith("//")
      ? `${options.basePath}${value === "/" ? "" : value}`
      : value;
  const brandCss = themeCss(brand);
  const BrandRoot = ({ children, withShell }: { children: React.ReactNode; withShell: boolean }) => (
    <div className="brand-root">
      <style dangerouslySetInnerHTML={{ __html: brandCss }} />
      {withShell && options.shell ? <SiteHeader brand={brand} header={options.shell.header} href={href} /> : null}
      {children}
      {withShell && options.shell ? <SiteFooter brand={brand} footer={options.shell.footer} href={href} /> : null}
    </div>
  );

  if (options.mode === "shell") {
    const shellConfig: Config<{ SiteHeader: HeaderProps; SiteFooter: FooterProps }> = {
      root: { render: ({ children }) => <BrandRoot withShell={false}>{children}</BrandRoot> },
      components: {
        SiteHeader: {
          label: "Site header",
          fields: {
            preparedFor: { type: "text", label: "Prepared for" },
            accountLogo: { type: "text", label: "Account logo URL (optional)" },
            ctaLabel: { type: "text", label: "Button label" },
            ctaHref: { type: "text", label: "Button link" },
            nav: {
              type: "array",
              label: "Navigation links",
              arrayFields: { label: { type: "text" }, href: { type: "text", label: "Link (/page or URL)" } },
              getItemSummary: (item: { label?: string }) => item.label || "Link",
            },
          } as never,
          render: (props) => <SiteHeader brand={brand} header={props} href={href} />,
        },
        SiteFooter: {
          label: "Site footer",
          fields: {
            legal: { type: "text", label: "Legal line" },
            privacyHref: { type: "text", label: "Privacy link" },
            termsHref: { type: "text", label: "Terms link" },
          },
          render: (props) => <SiteFooter brand={brand} footer={props} href={href} />,
        },
      },
    };
    return shellConfig as unknown as Config;
  }

  const cloneOptions = [
    { label: "Choose a section…", value: "" },
    ...Object.values(brand.clones).map((clone) => ({
      label: `${clone.label?.slice(0, 60)} (${new URL(clone.page_url).pathname})`,
      value: clone.id,
    })),
  ];
  const sections = makeSections(brand, href, options.editor?.AssetPicker);
  // This site's agent-written sections (E5): rendered with the same kit our sections use; no edit fields.
  const kit = makeKit(href);
  const agentSections = Object.fromEntries(
    Object.entries(options.agentSections ?? {}).map(([name, module]) => [
      name,
      {
        label: `${name} (agent)`,
        fields: {},
        // The wrapper lets compare_section find the component whatever its root element is.
        render: (props: never) => <div data-agent-section={name}>{module.render(props, kit)}</div>,
      },
    ]),
  );

  const config: Config<{
    ClonedSection: ClonedSectionProps;
    StatsBand: Record<string, unknown>;
    FeatureSplit: Record<string, unknown>;
    ProofCard: Record<string, unknown>;
    CtaBand: Record<string, unknown>;
    TokenProbe: { heading: string; body: string };
  }> = {
    root: { render: ({ children }) => <BrandRoot withShell>{children}</BrandRoot> },
    categories: {
      clones: { title: "The seller's sections", components: ["ClonedSection"] },
      brand: { title: "Brand sections", components: ["StatsBand", "FeatureSplit", "ProofCard", "CtaBand"] },
      ...(Object.keys(agentSections).length
        ? { agent: { title: "Agent sections", components: Object.keys(agentSections) as never } }
        : {}),
    },
    components: {
      // Test fixture for the G3 token check (export/check_tokens.py); not offered in the menu.
      TokenProbe: {
        fields: { heading: { type: "text" }, body: { type: "textarea" } },
        defaultProps: { heading: "Brand token probe", body: "Body text in the brand's body role." },
        render: ({ heading, body }) => (
          <section data-probe="token-section" className="bg-surface-brand px-6 py-16">
            <h2 data-probe="token-headline" className="font-headline text-headline text-ink-inverse">{heading}</h2>
            <p data-probe="token-body" className="mt-4 font-body text-body text-ink-inverse">{body}</p>
            <span data-probe="token-button" className="mt-6 inline-block rounded-button bg-surface-page px-5 py-3 font-cta text-cta text-ink-primary">Request the analysis</span>
          </section>
        ),
      },
      ...(sections as unknown as Record<"StatsBand" | "FeatureSplit" | "ProofCard" | "CtaBand", never>),
      ...(agentSections as unknown as Record<string, never>),
      ClonedSection: {
        label: "Cloned section",
        defaultProps: { fragmentId: "", slots: {}, replacements: [], links: [] },
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
        // Choosing a different section pre-fills its slots with the clone's own wording. Puck also
        // runs this when the editor loads (every prop then counts as "changed"), so the test is
        // against the previous data, never the `changed` flag alone.
        resolveData: (data, { lastData }) => {
          const clone = brand.clones[data.props.fragmentId];
          const previous = lastData?.props?.fragmentId;
          if (!clone || !lastData || previous === data.props.fragmentId) return data;
          return { ...data, props: { ...data.props, slots: slotDefaults(clone) } };
        },
        render: ({ id, fragmentId, slots, replacements, links, puck }) => {
          const clone = brand.clones[fragmentId];
          if (!clone) {
            return (
              <div className="m-6 rounded border border-dashed border-slate-300 p-10 text-center text-slate-500">
                Choose a cloned section
              </div>
            );
          }
          const resolvedSlots = Object.fromEntries(
            Object.entries(slots ?? {}).map(([key, value]) => [
              key,
              clone.slots[key]?.kind === "href" && typeof value === "string" ? href(value) : value,
            ]),
          );
          const resolvedLinks = (links ?? []).map((link) => ({ ...link, replace: href(link.replace) }));
          const html = fillClone(clone, resolvedSlots, replacements, resolvedLinks);
          const Editor = options.editor?.CloneEditor;
          if (puck?.isEditing && Editor) return <Editor itemId={id} clone={clone} html={html} />;
          return <CloneMarkup clone={clone} html={html} />;
        },
      },
    },
  };

  // Pages are loaded from storage as untyped Data, so callers take the config untyped.
  return config as unknown as Config;
}
