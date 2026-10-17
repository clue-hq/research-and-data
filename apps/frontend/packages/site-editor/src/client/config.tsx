import type { ReactNode } from "react";
import { useGetPuck, type Config, type Fields } from "@puckeditor/core";
import { SURFACES, fillClone, makeConfig, surfaceChoices, type BrandData, type ShellData } from "@clue/site-kit";
import { AssetPicker, CloneEditor, richTextField } from "@clue/site-kit/editor";
import type { FieldDescription } from "@clue/site-kit/editor-protocol";
import type { SiteShell } from "@clue/site-kit/site-document";
import { describeFields, puckFieldsFromJsonSchema } from "./fields";
import type { LoadedSection } from "./sections";

type RenderFn = (props: Record<string, unknown>) => ReactNode;
type MutableConfig = Config & { components: Record<string, { fields?: Fields; render?: RenderFn }> };

const BUILT_IN_SURFACES = new Set<string>(SURFACES);

/** The colour utilities of the brand's own surfaces (canvas, elevated, accent and the bands measured
 * from the seller's site). site-kit names their classes at runtime (`bg-surface-${surface}`), so the
 * editor's build-time Tailwind compile never sees them; the frame writes them itself, in Tailwind's
 * utilities layer. The six built-in surfaces are literal in site-kit and compiled as usual. The
 * published page needs none of this: its CSS is compiled over the rendered HTML. */
export function surfaceUtilityCss(brand: BrandData): string {
  const rules = surfaceChoices(brand)
    .filter((choice) => !BUILT_IN_SURFACES.has(choice.value))
    .map(
      ({ value }) =>
        `.bg-surface-${value}{background-color:var(--brand-surface-${value})}` +
        `.text-on-surface-${value}{color:var(--brand-on-surface-${value})}`,
    );
  return rules.length ? `@layer utilities{${rules.join("")}}` : "";
}

/** S2a-2 §2.5: an agent section's props as Puck stores them (plain strings, before its in-place
 * widgets go in), for site-kit's one second try at drawing a section that failed in Edit mode.
 * Called while the section draws in Puck's preview, which shares Puck's React tree. */
function useRawProps(): (id: string) => Record<string, unknown> | undefined {
  const getPuck = useGetPuck();
  return (id) => {
    // Puck's getItemById throws for an id it has not indexed; that must cost this section its second
    // try (the failed marker), never the editor.
    try {
      return getPuck().getItemById(id)?.props as Record<string, unknown> | undefined;
    } catch {
      return undefined;
    }
  };
}

/** The page config: site-kit's sections, the seller's clones, the shell drawn around every page,
 * and this site's agent sections with fields from their own props schema. Each agent section sits
 * behind site-kit's own error boundary (its `SectionBoundary`): one that throws is left out on its
 * own as a `data-agent-section-failed` marker and never takes the page or the editor down. No
 * basePath: internal links stay "/analysis", and the editor intercepts them and switches pages
 * itself. */
export function buildPageConfig(brand: BrandData, shell: SiteShell | null, sections: readonly LoadedSection[]): Config {
  const config = makeConfig(brand, {
    agentSections: Object.fromEntries(sections.map((section) => [section.name, section.module])),
    editor: { AssetPicker, CloneEditor, richField: richTextField, useRawProps },
    cloneHtml: fillClone,
    mode: "page",
    shell: (shell ?? undefined) as ShellData | undefined,
  }) as MutableConfig;
  const surfaceCss = surfaceUtilityCss(brand);
  const rootRender = config.root?.render as RenderFn | undefined;
  if (surfaceCss && config.root && rootRender) {
    // One object per config: React 19 rewrites a style's innerHTML whenever this identity changes.
    const surfaceStyle = { __html: surfaceCss };
    (config.root as { render: RenderFn }).render = (props) => (
      <>
        <style data-site-surfaces="" dangerouslySetInnerHTML={surfaceStyle} />
        {rootRender(props)}
      </>
    );
  }
  for (const section of sections) {
    const component = config.components[section.name];
    if (!component) continue;
    component.fields = puckFieldsFromJsonSchema(section.propsSchema, brand, richTextField);
  }
  return config;
}

/** The header's and footer's fields, from site-kit's shell config. */
export function shellFieldDescriptions(brand: BrandData): { footer: FieldDescription[]; header: FieldDescription[] } {
  const config = makeConfig(brand, { mode: "shell", cloneHtml: fillClone }) as MutableConfig;
  return {
    footer: describeFields(config.components.SiteFooter?.fields ?? {}),
    header: describeFields(config.components.SiteHeader?.fields ?? {}),
  };
}
