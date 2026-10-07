import type { Config, Fields } from "@puckeditor/core";
import type { BrandData } from "@/lib/brands";
import { fillClone, type SlotValues, type TextReplacement } from "@/lib/clone";
import { themeCss } from "@/lib/theme";

type ClonedSectionProps = {
  fragmentId: string;
  slots: SlotValues;
  replacements: TextReplacement[];
};

type Props = {
  TailwindProbe: { heading: string; body: string };
  TokenProbe: { heading: string; body: string };
  ClonedSection: ClonedSectionProps;
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

// One config per brand: the clone library is closed over, so fields and renders can read it
// without global state. The editor (client) and the published route (server) both call this.
export function makeConfig(brand: BrandData): Config {
  const cloneOptions = [
    { label: "Choose a section…", value: "" },
    ...Object.values(brand.clones).map((clone) => ({
      label: `${clone.label?.slice(0, 60)} (${new URL(clone.page_url).pathname})`,
      value: clone.id,
    })),
  ];

  const brandCss = themeCss(brand);

  const config: Config<Props> = {
    root: {
      render: ({ children }) => (
        <div className="brand-root">
          <style dangerouslySetInnerHTML={{ __html: brandCss }} />
          {children}
        </div>
      ),
    },
    components: {
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
      TailwindProbe: {
        fields: { heading: { type: "text" }, body: { type: "textarea" } },
        defaultProps: { heading: "Tailwind v4 probe", body: "Probe body." },
        render: ({ heading, body }) => (
          <section className="mx-auto max-w-[72rem] px-6 py-16 md:py-24">
            <h2 data-probe="heading" className="text-probe-size font-light tracking-[-0.02em] text-probe">
              {heading}
            </h2>
            <p data-probe="body" className="mt-4 max-w-prose text-lg text-slate-600">{body}</p>
            <div data-probe="box" className="mt-6 h-3 w-40 rounded-full bg-probe md:w-80" />
          </section>
        ),
      },

      ClonedSection: {
        label: "Cloned section",
        defaultProps: { fragmentId: "", slots: {}, replacements: [] },
        fields: {
          fragmentId: { type: "select", label: "Section", options: cloneOptions },
          slots: { type: "object", label: "Slots", objectFields: {} },
          replacements: {
            type: "array",
            label: "Text replacements (text with no slot)",
            arrayFields: { find: { type: "text" }, replace: { type: "text" } },
            getItemSummary: (item) => item.find || "New replacement",
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
          return {
            ...fields,
            slots: { type: "object", label: "Slots", objectFields },
          } as Fields<ClonedSectionProps>;
        },
        render: ({ fragmentId, slots, replacements }) => {
          const clone = brand.clones[fragmentId];
          if (!clone) {
            return (
              <div className="m-6 rounded border border-dashed border-slate-300 p-10 text-center text-slate-500">
                Choose a cloned section
              </div>
            );
          }
          const html = fillClone(clone, slots, replacements);
          return (
            <>
              <style dangerouslySetInnerHTML={{ __html: clone.css }} />
              <div
                className={`lumen-fragment ${clone.wrapper_class}`}
                data-lumen-fragment="true"
                data-fragment-id={clone.id}
                dangerouslySetInnerHTML={{ __html: html }}
              />
            </>
          );
        },
      },
    },
  };

  // Pages are loaded from storage as untyped Data, so callers take the config untyped.
  return config as unknown as Config;
}
